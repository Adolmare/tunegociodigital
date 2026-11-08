import pytest
from django.db import connection

from core.context import clear_tenant, set_tenant
from core.models import TenantContextMissing
from customers.models import Customer
from tenants.models import BusinessType, Membership, TenantTool, Tool
from tenants.services import create_tenant, enable_tool


@pytest.mark.django_db
def test_health_check_reports_database_connectivity(client):
    response = client.get("/health/")

    assert response.status_code == 204


def test_tenant_manager_fails_without_tenant_context():
    clear_tenant()

    with pytest.raises(TenantContextMissing):
        Customer.objects.all()


@pytest.mark.django_db
def test_tenant_owned_model_rejects_a_different_tenant(two_tenants):
    set_tenant(two_tenants["tenant_a"])
    try:
        customer = Customer(
            tenant=two_tenants["tenant_b"],
            full_name="Cliente ajeno",
        )
        with pytest.raises(PermissionError):
            customer.save()
    finally:
        clear_tenant()


@pytest.mark.django_db
def test_create_tenant_adds_owner_and_enables_core_and_template_tools(two_tenants):
    core_tool = Tool.objects.create(code="accounting", name="Contabilidad", is_core=True)
    template_tool = Tool.objects.create(code="reservations", name="Reservas")
    business_type = BusinessType.objects.create(
        code="barberia",
        name="Barbería",
    )
    business_type.tools.add(template_tool)
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", [str(two_tenants["user_a"].pk)])
        cursor.execute("SELECT set_config('app.tenant_id', '', true)")

    tenant = create_tenant(
        two_tenants["user_a"],
        name="Barbería Nueva",
        slug="barberia-nueva",
        business_type=business_type,
    )

    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant.pk)])
    assert Membership.objects.filter(
        user=two_tenants["user_a"],
        tenant=tenant,
        role=Membership.Role.OWNER,
        is_active=True,
    ).exists()
    assert set(
        TenantTool.objects.filter(tenant=tenant, is_enabled=True).values_list("tool_id", flat=True)
    ) == {core_tool.pk, template_tool.pk}


@pytest.mark.django_db
def test_enable_tool_enables_its_dependencies(two_tenants):
    dependency = Tool.objects.create(code="catalog", name="Catálogo")
    tool = Tool.objects.create(code="reservations", name="Reservas")
    tool.depends_on.add(dependency)
    tenant = two_tenants["tenant_a"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant.pk)])

    enable_tool(tenant, tool)

    assert set(
        TenantTool.objects.filter(tenant=tenant, is_enabled=True).values_list("tool_id", flat=True)
    ) == {dependency.pk, tool.pk}


def test_prod_settings_warns_without_r2_and_rejects_partial_r2(monkeypatch):
    import runpy
    from django.core.checks.registry import registry
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.test")
    monkeypatch.setenv("SECRET_KEY", "test-only-prod-secret-key-with-32-chars!!")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "https://example.com")
    for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"):
        monkeypatch.delenv(var, raising=False)

    original_checks = set(registry.deployment_checks)
    try:
        with pytest.warns(RuntimeWarning, match="Cloudflare R2 no está configurado"):
            ns = runpy.run_module("config.settings.prod")
        assert ns["STORAGES"]["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
        warnings_list = ns["check_production_media_storage"](None)
        assert [w.id for w in warnings_list] == ["core.W001"]

        monkeypatch.setenv("R2_BUCKET_NAME", "only-bucket")
        with pytest.raises(ImproperlyConfigured, match="Configuración incompleta de Cloudflare R2"):
            runpy.run_module("config.settings.prod")
    finally:
        registry.deployment_checks = original_checks
