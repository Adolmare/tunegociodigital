from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("loans", "0001_initial"),
    ]

    operations = [
        enable_rls("loans_loan"),
        enable_rls("loans_loanpayment"),
        enable_rls("loans_collectionroute"),
        enable_rls("loans_routestop"),
    ]
