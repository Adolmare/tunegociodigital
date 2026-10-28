import django.db.models.deletion
import uuid
from django.db import migrations, models


TENANT_TABLES = [
    "loans_loan",
    "loans_loaninstallment",
    "loans_loanpayment",
    "loans_paymentallocation",
    "loans_collectionroute",
    "loans_routestop",
]


def enable_tenant_rls(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_TABLES:
            condition = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
            cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            cursor.execute(
                f"CREATE POLICY tenant_isolation ON {table} USING ({condition}) WITH CHECK ({condition})"
            )


def disable_tenant_rls(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in reversed(TENANT_TABLES):
            cursor.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("loans", "0002_collector_cashflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="is_open_ended",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="loan",
            name="collection_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="loan",
            name="paperwork_fee",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="loan",
            name="opening_paid",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="loan",
            name="import_reference",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AlterField(
            model_name="loan",
            name="frequency",
            field=models.CharField(
                choices=[("daily", "Diario"), ("weekly", "Semanal"), ("biweekly", "Quincenal"), ("monthly", "Mensual")],
                default="monthly",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(condition=models.Q(("principal__gt", 0)), name="loan_principal_positive"),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(condition=models.Q(("interest_rate__gte", 0)), name="loan_interest_rate_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(condition=models.Q(("installments__gt", 0)), name="loan_installments_positive"),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(condition=models.Q(("total_payable__gte", 0)), name="loan_total_payable_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(condition=models.Q(("paperwork_fee__gte", 0)), name="loan_paperwork_fee_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(
                condition=models.Q(("opening_paid__gte", 0), ("opening_paid__lte", models.F("total_payable"))),
                name="loan_opening_paid_in_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(condition=models.Q(("balance__gte", 0)), name="loan_balance_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.UniqueConstraint(
                condition=models.Q(("import_reference__gt", "")),
                fields=("tenant", "import_reference"),
                name="uniq_loan_tenant_import_reference",
            ),
        ),
        migrations.AddField(
            model_name="loanpayment",
            name="direction",
            field=models.CharField(choices=[("payment", "Abono"), ("reversal", "Reversa")], default="payment", max_length=16),
        ),
        migrations.AddField(
            model_name="loanpayment",
            name="reversal_of",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reversals", to="loans.loanpayment"),
        ),
        migrations.AddField(
            model_name="loanpayment",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="loan_payment_entries", to="accounts.user"),
        ),
        migrations.AddConstraint(
            model_name="loanpayment",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="loan_payment_amount_positive"),
        ),
        migrations.AddConstraint(
            model_name="loanpayment",
            constraint=models.CheckConstraint(
                condition=models.Q(("direction", "payment"), ("reversal_of__isnull", True))
                | models.Q(("direction", "reversal"), ("reversal_of__isnull", False)),
                name="loan_payment_direction_matches_reversal",
            ),
        ),
        migrations.AddConstraint(
            model_name="loanpayment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("direction", "reversal")),
                fields=("reversal_of",),
                name="uniq_loan_payment_reversal",
            ),
        ),
        migrations.CreateModel(
            name="LoanInstallment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("number", models.PositiveIntegerField()),
                ("due_date", models.DateField()),
                ("amount_due", models.DecimalField(decimal_places=2, max_digits=14)),
                ("amount_paid", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("partial", "Parcial"), ("paid", "Pagada")], default="pending", max_length=16)),
                ("loan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="schedule", to="loans.loan")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["number"]},
        ),
        migrations.AddConstraint(
            model_name="loaninstallment",
            constraint=models.UniqueConstraint(fields=("loan", "number"), name="uniq_loan_installment_number"),
        ),
        migrations.AddConstraint(
            model_name="loaninstallment",
            constraint=models.CheckConstraint(condition=models.Q(("number__gt", 0)), name="loan_installment_number_positive"),
        ),
        migrations.AddConstraint(
            model_name="loaninstallment",
            constraint=models.CheckConstraint(condition=models.Q(("amount_due__gt", 0)), name="loan_installment_amount_positive"),
        ),
        migrations.AddConstraint(
            model_name="loaninstallment",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount_paid__gte", 0), ("amount_paid__lte", models.F("amount_due"))),
                name="loan_installment_paid_in_range",
            ),
        ),
        migrations.CreateModel(
            name="PaymentAllocation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("installment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="loans.loaninstallment")),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allocations", to="loans.loanpayment")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
        ),
        migrations.AddConstraint(
            model_name="paymentallocation",
            constraint=models.UniqueConstraint(fields=("payment", "installment"), name="uniq_payment_installment_allocation"),
        ),
        migrations.AddConstraint(
            model_name="paymentallocation",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="payment_allocation_amount_positive"),
        ),
        migrations.AddConstraint(
            model_name="routestop",
            constraint=models.CheckConstraint(condition=models.Q(("visit_order__gt", 0)), name="route_stop_visit_order_positive"),
        ),
        migrations.RunPython(enable_tenant_rls, disable_tenant_rls),
    ]
