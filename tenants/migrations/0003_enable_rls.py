from django.db import migrations

from core.db import enable_rls


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0002_tenantapikey"),
    ]

    operations = [
        enable_rls("tenants_membership"),
        migrations.RunSQL(
            sql="""
                DROP POLICY tenant_isolation ON tenants_membership;
                CREATE POLICY tenant_isolation ON tenants_membership
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
                )
                WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
                );
            """,
            reverse_sql="""
                DROP POLICY tenant_isolation ON tenants_membership;
                CREATE POLICY tenant_isolation ON tenants_membership
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
                WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                );
            """,
        ),
        enable_rls("tenants_tenanttool"),
        enable_rls("tenants_tenantapikey"),
    ]
