# Generated for collector cash-flow tracking.
import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CollectorDailyCash",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("date", models.DateField(default=django.utils.timezone.localdate)),
                ("opening_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("notes", models.CharField(blank=True, default="", max_length=240)),
                ("collector", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="daily_cash_openings", to="employees.employee")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["-date", "collector__full_name"]},
        ),
        migrations.AddConstraint(
            model_name="collectordailycash",
            constraint=models.UniqueConstraint(fields=("tenant", "collector", "date"), name="uniq_collector_daily_cash"),
        ),
        migrations.AddConstraint(
            model_name="collectordailycash",
            constraint=models.CheckConstraint(condition=models.Q(("opening_amount__gte", 0)), name="collector_opening_amount_nonnegative"),
        ),
        migrations.CreateModel(
            name="CollectorExpense",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("spent_on", models.DateField(default=django.utils.timezone.localdate)),
                ("category", models.CharField(choices=[("transport", "Transporte"), ("food", "Alimentación"), ("supplies", "Papelería e insumos"), ("other", "Otro")], default="other", max_length=16)),
                ("description", models.CharField(max_length=240)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("notes", models.TextField(blank=True, default="")),
                ("collector", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="daily_expenses", to="employees.employee")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="tenants.tenant")),
            ],
            options={"ordering": ["-spent_on", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="collectorexpense",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="collector_expense_amount_positive"),
        ),
        migrations.RunSQL(
            sql=[
                "ALTER TABLE loans_collectordailycash ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE loans_collectordailycash FORCE ROW LEVEL SECURITY",
                "CREATE POLICY tenant_isolation ON loans_collectordailycash USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
                "ALTER TABLE loans_collectorexpense ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE loans_collectorexpense FORCE ROW LEVEL SECURITY",
                "CREATE POLICY tenant_isolation ON loans_collectorexpense USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
            ],
            reverse_sql=[
                "DROP POLICY IF EXISTS tenant_isolation ON loans_collectorexpense",
                "ALTER TABLE loans_collectorexpense DISABLE ROW LEVEL SECURITY",
                "DROP POLICY IF EXISTS tenant_isolation ON loans_collectordailycash",
                "ALTER TABLE loans_collectordailycash DISABLE ROW LEVEL SECURITY",
            ],
        ),
    ]
