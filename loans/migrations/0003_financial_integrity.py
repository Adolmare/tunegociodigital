import uuid
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

from core.db import enable_rls


def backfill_financial_data(apps, schema_editor):
    Loan = apps.get_model("loans", "Loan")
    LoanInstallment = apps.get_model("loans", "LoanInstallment")
    LoanPayment = apps.get_model("loans", "LoanPayment")
    PaymentAllocation = apps.get_model("loans", "PaymentAllocation")
    connection = schema_editor.connection
    db_alias = connection.alias
    cent = Decimal("0.01")

    # The migration runs in one transaction; temporarily bypass existing tenant RLS
    # so historical rows across tenants can be backfilled consistently.
    schema_editor.execute("ALTER TABLE loans_loan DISABLE ROW LEVEL SECURITY")
    schema_editor.execute("ALTER TABLE loans_loanpayment DISABLE ROW LEVEL SECURITY")
    try:
        for loan in Loan._base_manager.using(db_alias).order_by("pk").iterator():
            principal = loan.principal.quantize(cent, rounding=ROUND_HALF_UP)
            rate = loan.interest_rate
            if principal <= 0 or rate < 0 or loan.installments < 1:
                raise RuntimeError(
                    f"Loan {loan.pk} has invalid principal, interest rate, or installment count; "
                    "review the record before applying financial-integrity migration."
                )

            total = (
                principal + (principal * rate / Decimal("100")).quantize(
                    cent,
                    rounding=ROUND_HALF_UP,
                )
            ).quantize(cent, rounding=ROUND_HALF_UP)
            total_cents = int(total * 100)
            if loan.installments > total_cents:
                raise RuntimeError(
                    f"Loan {loan.pk} has more installments than payable cents; "
                    "review the record before applying financial-integrity migration."
                )

            base_cents, remainder = divmod(total_cents, loan.installments)
            schedule = []
            for number in range(1, loan.installments + 1):
                if loan.frequency == "daily":
                    due_date = loan.start_date + timedelta(days=number)
                elif loan.frequency == "weekly":
                    due_date = loan.start_date + timedelta(days=7 * number)
                elif loan.frequency == "biweekly":
                    due_date = loan.start_date + timedelta(days=14 * number)
                else:
                    month_index = loan.start_date.month - 1 + number
                    year = loan.start_date.year + month_index // 12
                    month = month_index % 12 + 1
                    day = min(loan.start_date.day, calendar.monthrange(year, month)[1])
                    due_date = date(year, month, day)
                amount = Decimal(base_cents + (number <= remainder)) / 100
                schedule.append(
                    LoanInstallment.objects.using(db_alias).create(
                        tenant_id=loan.tenant_id,
                        loan_id=loan.pk,
                        number=number,
                        due_date=due_date,
                        amount_due=amount,
                    )
                )

            remaining = total
            payments = LoanPayment._base_manager.using(db_alias).filter(
                loan_id=loan.pk,
                direction="payment",
            ).order_by("paid_at", "pk")
            for payment in payments:
                if payment.amount <= 0 or payment.amount > remaining:
                    raise RuntimeError(
                        f"Loan payment {payment.pk} is invalid or exceeds the recalculated "
                        "loan balance; review the ledger before applying this migration."
                    )
                unapplied = payment.amount
                for installment in schedule:
                    due = installment.amount_due - installment.amount_paid
                    if due <= 0:
                        continue
                    applied = min(unapplied, due)
                    installment.amount_paid += applied
                    installment.status = (
                        "paid"
                        if installment.amount_paid == installment.amount_due
                        else "partial"
                    )
                    installment.save(using=db_alias, update_fields=["amount_paid", "status"])
                    PaymentAllocation.objects.using(db_alias).create(
                        tenant_id=loan.tenant_id,
                        payment_id=payment.pk,
                        installment_id=installment.pk,
                        amount=applied,
                    )
                    unapplied -= applied
                    if unapplied == 0:
                        break
                if unapplied != 0:
                    raise RuntimeError(
                        f"Loan payment {payment.pk} could not be allocated; "
                        "review the ledger before applying this migration."
                    )
                remaining -= payment.amount

            loan.total_payable = total
            loan.balance = remaining
            if loan.status != "cancelled":
                if remaining == 0:
                    loan.status = "paid"
                elif any(
                    installment.due_date < date.today()
                    and installment.amount_paid < installment.amount_due
                    for installment in schedule
                ):
                    loan.status = "delinquent"
                else:
                    loan.status = "active"
            loan.save(using=db_alias, update_fields=["total_payable", "balance", "status"])
    finally:
        if not connection.needs_rollback:
            schema_editor.execute("ALTER TABLE loans_loan ENABLE ROW LEVEL SECURITY")
            schema_editor.execute("ALTER TABLE loans_loan FORCE ROW LEVEL SECURITY")
            schema_editor.execute("ALTER TABLE loans_loanpayment ENABLE ROW LEVEL SECURITY")
            schema_editor.execute("ALTER TABLE loans_loanpayment FORCE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("loans", "0002_enable_rls"),
    ]

    operations = [
        migrations.CreateModel(
            name="LoanInstallment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("number", models.PositiveIntegerField()),
                ("due_date", models.DateField()),
                ("amount_due", models.DecimalField(decimal_places=2, max_digits=14)),
                (
                    "amount_paid",
                    models.DecimalField(decimal_places=2, default=0, max_digits=14),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendiente"),
                            ("partial", "Parcial"),
                            ("paid", "Pagada"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "loan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedule",
                        to="loans.loan",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"ordering": ["number"]},
        ),
        migrations.CreateModel(
            name="PaymentAllocation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                (
                    "installment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="allocations",
                        to="loans.loaninstallment",
                    ),
                ),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="allocations",
                        to="loans.loanpayment",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenants.tenant",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="loanpayment",
            name="direction",
            field=models.CharField(
                choices=[("payment", "Abono"), ("reversal", "Reversa")],
                default="payment",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="loanpayment",
            name="reversal_of",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reversals",
                to="loans.loanpayment",
            ),
        ),
        migrations.AddField(
            model_name="loanpayment",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="loan_payment_entries",
                to="accounts.user",
            ),
        ),
        migrations.RunPython(
            backfill_financial_data,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="loan",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("daily", "Diario"),
                    ("weekly", "Semanal"),
                    ("biweekly", "Quincenal"),
                    ("monthly", "Mensual"),
                ],
                default="monthly",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(
                condition=Q(("principal__gt", 0)),
                name="loan_principal_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(
                condition=Q(("interest_rate__gte", 0)),
                name="loan_interest_rate_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(
                condition=Q(("installments__gt", 0)),
                name="loan_installments_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(
                condition=Q(("total_payable__gte", 0)),
                name="loan_total_payable_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(
                condition=Q(("balance__gte", 0)),
                name="loan_balance_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="loaninstallment",
            constraint=models.UniqueConstraint(
                fields=("loan", "number"),
                name="uniq_loan_installment_number",
            ),
        ),
        migrations.AddConstraint(
            model_name="loaninstallment",
            constraint=models.CheckConstraint(
                condition=Q(("number__gt", 0)),
                name="loan_installment_number_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="loaninstallment",
            constraint=models.CheckConstraint(
                condition=Q(("amount_due__gt", 0)),
                name="loan_installment_amount_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="loaninstallment",
            constraint=models.CheckConstraint(
                condition=Q(("amount_paid__gte", 0))
                & Q(("amount_paid__lte", models.F("amount_due"))),
                name="loan_installment_paid_in_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="loanpayment",
            constraint=models.CheckConstraint(
                condition=Q(("amount__gt", 0)),
                name="loan_payment_amount_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="loanpayment",
            constraint=models.CheckConstraint(
                condition=(
                    Q(("direction", "payment"), ("reversal_of__isnull", True))
                    | Q(("direction", "reversal"), ("reversal_of__isnull", False))
                ),
                name="loan_payment_direction_matches_reversal",
            ),
        ),
        migrations.AddConstraint(
            model_name="loanpayment",
            constraint=models.UniqueConstraint(
                condition=Q(("direction", "reversal")),
                fields=("reversal_of",),
                name="uniq_loan_payment_reversal",
            ),
        ),
        migrations.AddConstraint(
            model_name="paymentallocation",
            constraint=models.UniqueConstraint(
                fields=("payment", "installment"),
                name="uniq_payment_installment_allocation",
            ),
        ),
        migrations.AddConstraint(
            model_name="paymentallocation",
            constraint=models.CheckConstraint(
                condition=Q(("amount__gt", 0)),
                name="payment_allocation_amount_positive",
            ),
        ),
        enable_rls("loans_loaninstallment"),
        enable_rls("loans_paymentallocation"),
    ]
