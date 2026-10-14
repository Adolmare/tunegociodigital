from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        enable_rls("catalog_category"),
        enable_rls("catalog_item"),
    ]
