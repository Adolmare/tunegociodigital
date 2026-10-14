from django.db import models

from core.models import TenantOwnedModel


class Reservation(TenantOwnedModel):
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("confirmed", "Confirmada"),
        ("in_progress", "En progreso"),
        ("completed", "Completada"),
        ("cancelled", "Cancelada"),
        ("no_show", "No se presentó"),
    ]

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="reservations")
    employee = models.ForeignKey("employees.Employee", null=True, blank=True, on_delete=models.SET_NULL, related_name="reservations")
    vehicle = models.ForeignKey("vehicles.Vehicle", null=True, blank=True, on_delete=models.SET_NULL, related_name="reservations")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="chk_reservation_valid_window",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "starts_at"]),
            models.Index(fields=["tenant", "employee", "starts_at"]),
        ]


class ReservationItem(TenantOwnedModel):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey("catalog.Item", on_delete=models.PROTECT, related_name="reservation_items")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reservation", "item"], name="uniq_reservation_item")
        ]
