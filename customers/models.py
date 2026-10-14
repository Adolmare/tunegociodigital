from django.contrib.gis.db import models

from core.models import TenantOwnedModel


class Customer(TenantOwnedModel):
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True, default="")
    document_id = models.CharField(max_length=40, blank=True, default="")
    address = models.TextField(blank=True)
    location = models.PointField(srid=4326, null=True, blank=True)
    notes = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "document_id"], name="uniq_customer_tenant_document", condition=models.Q(document_id__gt=""))
        ]
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name
