from django.db import models
from django.db.models import Q

from core.models import TenantOwnedModel


class Loan(TenantOwnedModel):
    FREQUENCY_CHOICES = [
        ("daily", "Diario"),
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

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(principal__gt=0),
                name="loan_principal_positive",
            ),
            models.CheckConstraint(
                condition=Q(interest_rate__gte=0),
                name="loan_interest_rate_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(installments__gt=0),
                name="loan_installments_positive",
            ),
            models.CheckConstraint(
                condition=Q(total_payable__gte=0),
                name="loan_total_payable_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(balance__gte=0),
                name="loan_balance_nonnegative",
            ),
        ]


class LoanInstallment(TenantOwnedModel):
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("partial", "Parcial"),
        ("paid", "Pagada"),
    ]

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="schedule")
    number = models.PositiveIntegerField()
    due_date = models.DateField()
    amount_due = models.DecimalField(max_digits=14, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "number"],
                name="uniq_loan_installment_number",
            ),
            models.CheckConstraint(
                condition=Q(number__gt=0),
                name="loan_installment_number_positive",
            ),
            models.CheckConstraint(
                condition=Q(amount_due__gt=0),
                name="loan_installment_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0) & Q(amount_paid__lte=models.F("amount_due")),
                name="loan_installment_paid_in_range",
            ),
        ]


class LoanPayment(TenantOwnedModel):
    DIRECTION_CHOICES = [
        ("payment", "Abono"),
        ("reversal", "Reversa"),
    ]

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="payments")
    collector = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="loan_payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_at = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=16, default="cash")
    direction = models.CharField(max_length=16, choices=DIRECTION_CHOICES, default="payment")
    reversal_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversals",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loan_payment_entries",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="loan_payment_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(direction="payment", reversal_of__isnull=True)
                    | Q(direction="reversal", reversal_of__isnull=False)
                ),
                name="loan_payment_direction_matches_reversal",
            ),
            models.UniqueConstraint(
                fields=["reversal_of"],
                condition=Q(direction="reversal"),
                name="uniq_loan_payment_reversal",
            ),
        ]


class PaymentAllocation(TenantOwnedModel):
    payment = models.ForeignKey(
        LoanPayment,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    installment = models.ForeignKey(
        LoanInstallment,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "installment"],
                name="uniq_payment_installment_allocation",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payment_allocation_amount_positive",
            ),
        ]


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

    class Meta:
        ordering = ["route__date", "visit_order", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(visit_order__gt=0),
                name="route_stop_visit_order_positive",
            ),
        ]
