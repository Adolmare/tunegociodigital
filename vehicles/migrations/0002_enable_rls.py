from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0001_initial"),
    ]

    operations = [
        enable_rls("vehicles_vehicle"),
    ]
