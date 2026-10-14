from django.db import models

from core.models import TenantOwnedModel


class Loan(TenantOwnedModel):
    FREQUENCY_CHOICES = [
        ("weekly", "Semanal"),
        ("biweekly", "Quincenal"),
        ("monthly", "Mensual"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("active", "Activo"),
        ("paid", "Pagado"),
        ("delinquent", "Moroso"),
        ("cancelled", "Cancelado"),
    ]

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="loans")
    collector = models.ForeignKey("employees.Employee", null=True, blank=True, on_delete=models.SET_NULL, related_name="collections")
    principal = models.DecimalField(max_digits=14, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    installments = models.PositiveIntegerField(default=1)
    frequency = models.CharField(max_length=16, choices=FREQUENCY_CHOICES, default="monthly")
    start_date = models.DateField()
    total_payable = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")


class LoanPayment(TenantOwnedModel):
    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="payments")
    collector = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="loan_payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_at = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=16, default="cash")


class CollectionRoute(TenantOwnedModel):
    collector = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="routes")
    name = models.CharField(max_length=150)
    date = models.DateField()


class RouteStop(TenantOwnedModel):
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("visited", "Visitado"),
        ("paid", "Pagado"),
        ("partial", "Parcial"),
        ("not_paid", "No pagado"),
        ("rescheduled", "Reprogramado"),
    ]

    route = models.ForeignKey(CollectionRoute, on_delete=models.CASCADE, related_name="stops")
    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="route_stops")
    visit_order = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    rescheduled_to = models.DateField(null=True, blank=True)
