import uuid
from django.conf import settings
from django.db import models

class BusinessType(models.Model):          # plantilla: barbería, restaurante...
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    tools = models.ManyToManyField("Tool", blank=True)   # herramientas por defecto

def generate_join_code():
    return uuid.uuid4().hex[:10].upper()


class Tenant(models.Model):
    class Status(models.TextChoices):
        TRIAL = "trial"; ACTIVE = "active"; SUSPENDED = "suspended"; CANCELLED = "cancelled"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    join_code = models.CharField(max_length=10, unique=True, default=generate_join_code, editable=False)
    business_type = models.ForeignKey(BusinessType, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.TRIAL)
    timezone = models.CharField(max_length=50, default="UTC")
    currency = models.CharField(max_length=3, default="COP")
    created_at = models.DateTimeField(auto_now_add=True)

class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner"; ADMIN = "admin"; MANAGER = "manager"; EMPLOYEE = "employee"
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "tenant"], name="uniq_user_tenant")]

class Tool(models.Model):                  # catalog, reservations, deliveries, loans, accounting
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    is_core = models.BooleanField(default=False)
    depends_on = models.ManyToManyField("self", symmetrical=False, blank=True)

class TenantTool(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="tools")
    tool = models.ForeignKey(Tool, on_delete=models.PROTECT)
    is_enabled = models.BooleanField(default=True)
    source = models.CharField(max_length=10, default="manual")   # manual / plan
    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "tool"], name="uniq_tenant_tool")]


class TenantApiKey(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=80)
    key_hash = models.CharField(max_length=128, unique=True)
    scopes = models.JSONField(default=list, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="uniq_tenant_apikey_name")]


class TenantJoinRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        ACCEPTED = "accepted", "Aceptada"
        REJECTED = "rejected", "Rechazada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="join_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tenant_join_requests")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reviewed_tenant_join_requests",
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user"],
                condition=models.Q(status="pending"),
                name="uniq_pending_tenant_join_request",
            ),
        ]
