import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models


CENT = Decimal("0.01")
AMOUNTS_PER_100K = {
    "daily": Decimal("4000.00"),
    "weekly": Decimal("20000.00"),
    "biweekly": Decimal("40000.00"),
}


def _due_date(start_date, frequency, installment_number):
    if frequency == "daily":
        return start_date + timedelta(days=installment_number)
    if frequency == "weekly":
        return start_date + timedelta(days=7 * installment_number)
    if frequency == "biweekly":
        return start_date + timedelta(days=14 * installment_number)

    month_index = start_date.month - 1 + installment_number
    year = start_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def create_frequency_schedules(apps, schema_editor):
    Loan = apps.get_model("loans", "Loan")
    LoanInstallment = apps.get_model("loans", "LoanInstallment")
    PaymentAllocation = apps.get_model("loans", "PaymentAllocation")
    database = schema_editor.connection.alias

    loans = Loan._base_manager.using(database).filter(is_open_ended=True)
    for loan in loans.iterator():
        amount_per_100k = AMOUNTS_PER_100K.get(loan.frequency)
        if amount_per_100k is None:
            continue
        if PaymentAllocation._base_manager.using(database).filter(
            installment__loan_id=loan.pk
        ).exists():
            raise RuntimeError(
                f"Cannot rebuild loan {loan.pk}: payment allocations already exist."
            )

        collection_amount = (
            loan.principal * amount_per_100k / Decimal("100000")
        ).quantize(CENT, rounding=ROUND_HALF_UP)
        if collection_amount <= 0:
            raise RuntimeError(f"Calculated quota is not positive for loan {loan.pk}.")

        total_cents = int(loan.total_payable * 100)
        collection_cents = int(collection_amount * 100)
        installment_count = (total_cents + collection_cents - 1) // collection_cents
        if installment_count < 1:
            raise RuntimeError(f"Calculated schedule is empty for loan {loan.pk}.")

        LoanInstallment._base_manager.using(database).filter(
            loan_id=loan.pk
        ).delete()
        amount_paid_remaining = loan.opening_paid
        for number in range(1, installment_count + 1):
            amount_due = min(
                collection_amount,
                loan.total_payable - collection_amount * (number - 1),
            )
            amount_paid = min(amount_paid_remaining, amount_due)
            LoanInstallment._base_manager.using(database).create(
                tenant_id=loan.tenant_id,
                loan_id=loan.pk,
                number=number,
                due_date=_due_date(loan.start_date, loan.frequency, number),
                amount_due=amount_due,
                amount_paid=amount_paid,
                status=(
                    "paid"
                    if amount_paid == amount_due
                    else "partial"
                    if amount_paid > 0
                    else "pending"
                ),
            )
            amount_paid_remaining -= amount_paid

        if amount_paid_remaining != 0:
            raise RuntimeError(f"Opening paid amount does not fit loan {loan.pk}.")
        loan.collection_amount = collection_amount
        loan.installments = installment_count
        loan.balance = loan.total_payable - loan.opening_paid
        loan.status = "paid" if loan.balance == 0 else "active"
        loan.save(
            using=database,
            update_fields=[
                "collection_amount",
                "installments",
                "balance",
                "status",
            ],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0005_open_ended_and_excel_import"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="collection_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.RunPython(
            create_frequency_schedules,
            migrations.RunPython.noop,
        ),
    ]
