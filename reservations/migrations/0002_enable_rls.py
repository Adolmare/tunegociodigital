from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("reservations", "0001_initial"),
    ]

    operations = [
        enable_rls("reservations_reservation"),
        enable_rls("reservations_reservationitem"),
    ]
