from django.db import transaction
from .models import Tenant, Membership, TenantTool, Tool

@transaction.atomic
def enable_tool(tenant, tool, source="manual"):
    for dep in tool.depends_on.all():
        enable_tool(tenant, dep, source)
    TenantTool.objects.update_or_create(tenant=tenant, tool=tool,
                                        defaults={"is_enabled": True, "source": source})

@transaction.atomic
def create_tenant(user, name, slug, business_type=None):
    tenant = Tenant.objects.create(name=name, slug=slug, business_type=business_type)
    Membership.objects.create(user=user, tenant=tenant, role=Membership.Role.OWNER)
    tools = set(Tool.objects.filter(is_core=True))
    if business_type:
        tools |= set(business_type.tools.all())
    for tool in tools:
        enable_tool(tenant, tool)
    return tenant