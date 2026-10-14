from django.db import models

from core.models import TenantOwnedModel


class DeliveryOrder(TenantOwnedModel):
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("assigned", "Asignada"),
        ("in_route", "En ruta"),
        ("delivered", "Entregada"),
        ("cancelled", "Cancelada"),
    ]
    CHANNEL_CHOICES = [
        ("ai_agent", "Agente IA"),
        ("manual", "Manual"),
        ("web", "Web"),
    ]
    PAYMENT_METHOD_CHOICES = [
        ("cash", "Efectivo"),
        ("card", "Tarjeta"),
        ("invoice", "Factura"),
    ]

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="delivery_orders")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    address = models.TextField()
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="manual")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default="cash")
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)


class DeliveryOrderItem(TenantOwnedModel):
    order = models.ForeignKey(DeliveryOrder, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey("catalog.Item", on_delete=models.PROTECT, related_name="delivery_items")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "order", "item"], name="uniq_delivery_order_item")
        ]
