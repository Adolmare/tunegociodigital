import uuid
from django.conf import settings
from django.db import models

class BusinessType(models.Model):          # plantilla: barbería, restaurante...
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    tools = models.ManyToManyField("Tool", blank=True)   # herramientas por defecto

class Tenant(models.Model):
    class Status(models.TextChoices):
        TRIAL = "trial"; ACTIVE = "active"; SUSPENDED = "suspended"; CANCELLED = "cancelled"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    business_type = models.ForeignKey(BusinessType, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.TRIAL)
    timezone = models.CharField(max_length=50, default="UTC")
    currency = models.CharField(max_length=3, default="USD")
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
