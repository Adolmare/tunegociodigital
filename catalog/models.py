from django.db import models

from core.models import TenantOwnedModel


class Category(TenantOwnedModel):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_catalog_category_tenant_name")
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Item(TenantOwnedModel):
    KIND_CHOICES = [
        ("product", "Producto"),
        ("service", "Servicio"),
    ]

    category = models.ForeignKey("Category", on_delete=models.PROTECT, related_name="items")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="product")
    name = models.CharField(max_length=160)
    price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    duration_minutes = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "category", "name"], name="uniq_catalog_item_tenant_category_name")
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name
