from django.db import migrations


TABLES = (
    "accounting_account",
    "accounting_fiscalperiod",
    "accounting_journalentry",
    "accounting_journalline",
    "accounting_document",
    "accounting_documentextraction",
    "accounting_eventinbox",
    "catalog_category",
    "catalog_item",
    "customers_customer",
    "deliveries_deliveryorder",
    "deliveries_deliveryorderitem",
    "employees_employee",
    "loans_loan",
    "loans_loaninstallment",
    "loans_loanpayment",
    "loans_paymentallocation",
    "loans_collectionroute",
    "loans_routestop",
    "reservations_reservation",
    "reservations_reservationitem",
    "tenants_tenantapikey",
    "tenants_tenanttool",
    "tenants_membership",
    "vehicles_vehicle",
)


def enable_platform_admin_access(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            if table == "tenants_membership":
                condition = """
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
                """
            else:
                condition = (
                    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
                )
            cursor.execute(
                f"""
                ALTER POLICY tenant_isolation ON {table}
                USING ({condition} OR current_setting('app.admin_access', true) = 'on')
                WITH CHECK ({condition} OR current_setting('app.admin_access', true) = 'on')
                """
            )


def disable_platform_admin_access(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            if table == "tenants_membership":
                condition = """
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
                """
            else:
                condition = (
                    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
                )
            cursor.execute(
                f"""
                ALTER POLICY tenant_isolation ON {table}
                USING ({condition})
                WITH CHECK ({condition})
                """
            )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0002_enable_rls"),
        ("catalog", "0002_enable_rls"),
        ("customers", "0002_enable_rls"),
        ("deliveries", "0002_enable_rls"),
        ("employees", "0002_enable_rls"),
        ("loans", "0003_financial_integrity"),
        ("reservations", "0002_enable_rls"),
        ("tenants", "0003_enable_rls"),
        ("vehicles", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunPython(
            enable_platform_admin_access,
            reverse_code=disable_platform_admin_access,
        ),
    ]
