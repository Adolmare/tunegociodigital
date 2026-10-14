from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("deliveries", "0001_initial"),
    ]

    operations = [
        enable_rls("deliveries_deliveryorder"),
        enable_rls("deliveries_deliveryorderitem"),
    ]
