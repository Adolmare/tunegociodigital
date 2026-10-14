from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0001_initial"),
    ]

    operations = [
        enable_rls("accounting_account"),
        enable_rls("accounting_fiscalperiod"),
        enable_rls("accounting_journalentry"),
        enable_rls("accounting_journalline"),
        enable_rls("accounting_document"),
        enable_rls("accounting_documentextraction"),
        enable_rls("accounting_eventinbox"),
    ]
