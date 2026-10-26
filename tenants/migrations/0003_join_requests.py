import uuid

import django.db.models.deletion
import tenants.models
from django.conf import settings
from django.db import migrations, models


def populate_join_codes(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.filter(join_code__isnull=True).iterator():
        code = uuid.uuid4().hex[:10].upper()
        while Tenant.objects.filter(join_code=code).exists():
            code = uuid.uuid4().hex[:10].upper()
        Tenant.objects.filter(pk=tenant.pk).update(join_code=code)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("tenants", "0002_tenantapikey"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="join_code",
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.RunPython(populate_join_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tenant",
            name="join_code",
            field=models.CharField(default=tenants.models.generate_join_code, editable=False, max_length=10, unique=True),
        ),
        migrations.CreateModel(
            name="TenantJoinRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("accepted", "Aceptada"), ("rejected", "Rechazada")], default="pending", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_tenant_join_requests", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="join_requests", to="tenants.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tenant_join_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.AddConstraint(
            model_name="tenantjoinrequest",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "pending")), fields=("tenant", "user"), name="uniq_pending_tenant_join_request"),
        ),
        migrations.RunSQL(
            sql=[
                "ALTER TABLE tenants_tenantjoinrequest ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE tenants_tenantjoinrequest FORCE ROW LEVEL SECURITY",
                "CREATE POLICY tenant_isolation ON tenants_tenantjoinrequest USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
            ],
            reverse_sql=[
                "DROP POLICY IF EXISTS tenant_isolation ON tenants_tenantjoinrequest",
                "ALTER TABLE tenants_tenantjoinrequest DISABLE ROW LEVEL SECURITY",
            ],
        ),
    ]
