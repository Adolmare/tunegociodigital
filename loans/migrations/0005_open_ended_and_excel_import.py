from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0004_route_stop_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="is_open_ended",
            field=models.BooleanField(default=False),
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
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(
                condition=Q(("paperwork_fee__gte", 0)),
                name="loan_paperwork_fee_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.CheckConstraint(
                condition=Q(("opening_paid__gte", 0))
                & Q(("opening_paid__lte", models.F("total_payable"))),
                name="loan_opening_paid_in_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="loan",
            constraint=models.UniqueConstraint(
                condition=Q(("import_reference__gt", "")),
                fields=("tenant", "import_reference"),
                name="uniq_loan_tenant_import_reference",
            ),
        ),
    ]
