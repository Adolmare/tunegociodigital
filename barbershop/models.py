from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import TenantOwnedModel


class BarberProfile(TenantOwnedModel):
    """Datos propios de un barbero (el empleado es el registro compartido de la plataforma)."""

    employee = models.OneToOneField(
        "employees.Employee", on_delete=models.CASCADE, related_name="barber_profile"
    )
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("50.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )

    class Meta:
        ordering = ["employee__full_name"]

    def __str__(self):
        return f"{self.employee.full_name} ({self.commission_percent}%)"


class ServiceSale(TenantOwnedModel):
    """Cobro de una cita o venta rapida; congela precios y comision al momento de cobrar."""

    PAYMENT_METHODS = [
        ("cash", "Efectivo"),
        ("transfer", "Transferencia"),
        ("card", "Tarjeta"),
        ("other", "Otro"),
    ]

    reservation = models.OneToOneField(
        "reservations.Reservation", on_delete=models.PROTECT, related_name="sale"
    )
    barber = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT, related_name="barber_sales"
    )
    customer_name = models.CharField(max_length=160, blank=True, default="")
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    tip = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(max_length=16, choices=PAYMENT_METHODS, default="cash")
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0) & models.Q(tip__gte=0),
                name="chk_servicesale_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "paid_at"]),
            models.Index(fields=["tenant", "barber", "paid_at"]),
        ]
        ordering = ["-paid_at"]
