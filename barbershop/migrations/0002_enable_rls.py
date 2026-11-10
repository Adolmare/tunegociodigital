from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("barbershop", "0001_initial"),
    ]

    operations = [
        enable_rls("barbershop_barberprofile"),
        enable_rls("barbershop_servicesale"),
    ]
