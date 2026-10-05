import uuid
from django.db import models
from .context import get_tenant

class TenantContextMissing(Exception):
    pass

class TenantManager(models.Manager):
    def get_queryset(self):
        tenant = get_tenant()
        if tenant is None:
            raise TenantContextMissing("No hay tenant activo")   # falla cerrado
        return super().get_queryset().filter(tenant=tenant)

class TenantOwnedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT,
                               related_name="+", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()        # primero: es el manager por defecto
    unscoped = models.Manager()      # solo tareas internas, siempre auditado

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        ctx = get_tenant()
        if self.tenant_id is None:
            self.tenant = ctx
        elif ctx is not None and self.tenant_id != ctx.id:
            raise PermissionError("Tenant distinto al del contexto")
        super().save(*args, **kwargs)