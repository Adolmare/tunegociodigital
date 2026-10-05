from django.db import migrations

def enable_rls(table):
    cond = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    return migrations.RunSQL(
        f"""ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table} USING ({cond}) WITH CHECK ({cond});""",
        f"""DROP POLICY tenant_isolation ON {table};
            ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;""",
    )