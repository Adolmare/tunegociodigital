from django.db import transaction
from django.db import connection
from .models import Tenant, Membership, TenantTool, Tool

@transaction.atomic
def enable_tool(tenant, tool, source="manual"):
    for dep in tool.depends_on.all():
        enable_tool(tenant, dep, source)
    TenantTool.objects.update_or_create(tenant=tenant, tool=tool,
                                        defaults={"is_enabled": True, "source": source})

def sync_catalog():
    """Crea o actualiza las herramientas y tipos de negocio (idempotente)."""
    from .catalog_specs import BUSINESS_TYPE_SPECS, TOOL_SPECS
    from .models import BusinessType

    tools = {}
    for code, payload in TOOL_SPECS.items():
        tool, _ = Tool.objects.update_or_create(
            code=code,
            defaults={"name": payload["name"], "is_core": payload["is_core"]},
        )
        tools[code] = tool
        for dep_code in payload["depends_on"]:
            tool.depends_on.add(tools[dep_code])
    for code, tool_codes in BUSINESS_TYPE_SPECS.items():
        business_type, _ = BusinessType.objects.update_or_create(
            code=code, defaults={"name": code.title()}
        )
        business_type.tools.set([tools[tool_code] for tool_code in tool_codes])


def ensure_business_type(code):
    """Garantiza que el tipo de negocio y sus herramientas existan (por ejemplo en una base nueva)."""
    from .models import BusinessType

    sync_catalog()
    return BusinessType.objects.get(code=code)


@transaction.atomic
def create_tenant(user, name, slug, business_type=None):
    tenant = Tenant.objects.create(name=name, slug=slug, business_type=business_type)
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant.pk)])
    Membership.objects.create(user=user, tenant=tenant, role=Membership.Role.OWNER)
    tools = set(Tool.objects.filter(is_core=True))
    if business_type:
        tools |= set(business_type.tools.all())
    for tool in tools:
        enable_tool(tenant, tool)
    return tenant