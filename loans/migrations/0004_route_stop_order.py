from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0003_financial_integrity"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="routestop",
            options={"ordering": ["route__date", "visit_order", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="routestop",
            constraint=models.CheckConstraint(
                condition=Q(("visit_order__gt", 0)),
                name="route_stop_visit_order_positive",
            ),
        ),
    ]
