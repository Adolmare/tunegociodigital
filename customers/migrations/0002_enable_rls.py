from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0001_initial"),
    ]

    operations = [
        enable_rls("customers_customer"),
    ]
