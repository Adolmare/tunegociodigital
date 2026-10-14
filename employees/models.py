from django.conf import settings
from django.db import models

from core.models import TenantOwnedModel


class Employee(TenantOwnedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True)
    position = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="uniq_employee_tenant_user", condition=models.Q(user__isnull=False))
        ]
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name
