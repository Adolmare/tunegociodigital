from django.db import models

from core.models import TenantOwnedModel


class Vehicle(TenantOwnedModel):
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="vehicles")
    plate = models.CharField(max_length=20)
    brand = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=80, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    color = models.CharField(max_length=40, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "plate"], name="uniq_vehicle_tenant_plate")
        ]
        ordering = ["plate"]

    def __str__(self):
        return f"{self.brand} {self.model} ({self.plate})".strip()
