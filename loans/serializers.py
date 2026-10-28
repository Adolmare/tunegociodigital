from decimal import Decimal

from django.db.models import F
from django.utils import timezone
from rest_framework import serializers
from rest_framework_gis.fields import GeometryField

from customers.models import Customer
from tenants.api import TenantScopedRelatedField

from employees.models import Employee

from .models import (
    CollectionRoute,
    CollectorDailyClose,
    CollectorExpense,
    Loan,
    LoanInstallment,
    LoanPayment,
    PaymentAllocation,
    RouteStop,
)


class LoanLedgerQuerySerializer(serializers.Serializer):
    PERIOD_CHOICES = (
        ("year", "Anual"),
        ("month", "Mensual"),
        ("week", "Semanal"),
        ("fortnight", "Quincenal"),
        ("day", "Diario"),
    )
    FREQUENCY_CHOICES = (
        ("all", "Todos"),
        ("daily", "Diario"),
        ("weekly", "Semanal"),
        ("biweekly", "Quincenal"),
        ("monthly", "Mensual"),
    )

    period = serializers.ChoiceField(choices=PERIOD_CHOICES, default="day")
    date = serializers.DateField(required=False, default=timezone.localdate)
    frequency = serializers.ChoiceField(
        choices=FREQUENCY_CHOICES,
        required=False,
        default="all",
    )


class LoanCustomerInputSerializer(serializers.ModelSerializer):
    location = GeometryField(required=False, allow_null=True)

    def validate_neighborhood(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Selecciona o escribe un barrio.")
        return value

    class Meta:
        model = Customer
        fields = ("full_name", "document_id", "neighborhood", "location")
        extra_kwargs = {
            "full_name": {"required": True},
            "document_id": {"required": True, "allow_blank": False},
            "neighborhood": {"required": True, "allow_blank": False},
        }


class LoanInstallmentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="loan.customer.full_name", read_only=True)
    document_id = serializers.CharField(source="loan.customer.document_id", read_only=True)
    neighborhood = serializers.CharField(source="loan.customer.neighborhood", read_only=True)
    is_open_ended = serializers.BooleanField(source="loan.is_open_ended", read_only=True)
    frequency = serializers.CharField(source="loan.frequency", read_only=True)
    location = GeometryField(source="loan.customer.location", read_only=True)
    pending_amount = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    principal_due = serializers.SerializerMethodField()
    interest_due = serializers.SerializerMethodField()
    payment_history = serializers.SerializerMethodField()

    def get_pending_amount(self, obj):
        return obj.amount_due - obj.amount_paid

    def get_is_overdue(self, obj):
        return obj.due_date < timezone.localdate() and obj.amount_paid < obj.amount_due

    def get_status(self, obj):
        if obj.amount_paid == obj.amount_due:
            return "paid"
        if self.get_is_overdue(obj):
            return "delinquent"
        if obj.amount_paid > 0:
            return "partial"
        return "pending"

    def get_principal_due(self, obj):
        loan = obj.loan
        base_cents, remainder = divmod(int(loan.principal * 100), loan.installments)
        return Decimal(base_cents + (1 if obj.number <= remainder else 0)) / 100

    def get_interest_due(self, obj):
        return obj.amount_due - self.get_principal_due(obj)

    def get_payment_history(self, obj):
        allocations = PaymentAllocation.objects.filter(
            installment=obj,
        ).select_related("payment", "payment__collector").order_by("payment__paid_at", "payment_id")
        return [
            {
                "payment_id": str(allocation.payment_id),
                "paid_at": allocation.payment.paid_at.isoformat(),
                "amount": str(
                    -allocation.amount
                    if allocation.payment.direction == "reversal"
                    else allocation.amount
                ),
                "direction": allocation.payment.direction,
                "collector": allocation.payment.collector.full_name,
            }
            for allocation in allocations
        ]

    class Meta:
        model = LoanInstallment
        exclude = ("tenant",)
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "loan",
            "number",
            "due_date",
            "amount_due",
            "amount_paid",
            "status",
            "principal_due",
            "interest_due",
            "payment_history",
        )


class LoanSerializer(serializers.ModelSerializer):
    customer = TenantScopedRelatedField(required=False, allow_null=True)
    customer_details = LoanCustomerInputSerializer(write_only=True, required=False)
    collector = TenantScopedRelatedField(required=False, allow_null=True)
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    document_id = serializers.CharField(source="customer.document_id", read_only=True)
    neighborhood = serializers.CharField(source="customer.neighborhood", read_only=True)
    location = GeometryField(source="customer.location", read_only=True)
    status = serializers.SerializerMethodField()
    installment_schedule = LoanInstallmentSerializer(
        source="schedule",
        many=True,
        read_only=True,
    )
    principal = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    installments = serializers.IntegerField(min_value=1, required=False)
    paperwork_fee = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        default=Decimal("0.00"),
    )
    collection_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    interest_rate = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.00"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(
            deleted_at__isnull=True,
        )
        collector_queryset = Employee.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
        )
        request = self.context.get("request")
        if request is not None and getattr(request, "membership", None) is not None:
            if request.membership.role == "employee":
                collector_queryset = collector_queryset.filter(user=request.user)
        self.fields["collector"].queryset = collector_queryset
        if self.instance is not None:
            for field_name in (
                "customer",
                "principal",
                "interest_rate",
                "installments",
                "is_open_ended",
                "paperwork_fee",
                "frequency",
                "start_date",
            ):
                self.fields[field_name].read_only = True

    def to_internal_value(self, data):
        server_managed_fields = {
            "total_payable",
            "opening_paid",
            "balance",
            "status",
            "import_reference",
            "collection_amount",
        }
        supplied = server_managed_fields.intersection(data)
        if supplied:
            raise serializers.ValidationError({
                field: "Este valor lo calcula el servidor y no puede enviarse."
                for field in sorted(supplied)
            })
        return super().to_internal_value(data)

    def validate(self, attrs):
        if self.instance is None:
            if not attrs.get("is_open_ended", False) and "installments" not in attrs:
                raise serializers.ValidationError(
                    {"installments": "Indica el número de cuotas del préstamo."}
                )
            customer = attrs.get("customer")
            customer_details = attrs.get("customer_details")
            if (customer is None) == (customer_details is None):
                raise serializers.ValidationError(
                    "Envía un cliente existente o customer_details para registrar uno nuevo."
                )
        return attrs

    def get_status(self, obj):
        if obj.status == "cancelled":
            return "cancelled"
        if obj.balance == 0:
            return "paid"
        if obj.schedule.filter(
            due_date__lt=timezone.localdate(),
            amount_paid__lt=F("amount_due"),
        ).exists():
            return "delinquent"
        return obj.status

    class Meta:
        model = Loan
        exclude = ("tenant",)
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "total_payable",
            "collection_amount",
            "opening_paid",
            "balance",
            "status",
            "import_reference",
            "installment_schedule",
            "customer_name",
            "document_id",
            "location",
        )


class LoanPaymentSerializer(serializers.ModelSerializer):
    loan = TenantScopedRelatedField()
    collector = TenantScopedRelatedField(required=False)
    signed_amount = serializers.SerializerMethodField()
    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["loan"].queryset = Loan.objects.all()
        collector_queryset = Employee.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
        )
        request = self.context.get("request")
        if request is not None and getattr(request, "membership", None) is not None:
            if request.membership.role == "employee":
                collector_queryset = collector_queryset.filter(user=request.user)
                self.fields["loan"].queryset = Loan.objects.filter(collector__user=request.user)
        self.fields["collector"].queryset = collector_queryset

    def get_signed_amount(self, obj):
        return -obj.amount if obj.direction == "reversal" else obj.amount

    class Meta:
        model = LoanPayment
        exclude = ("tenant",)
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "paid_at",
            "direction",
            "reversal_of",
            "created_by",
            "signed_amount",
        )


class CollectionRouteSerializer(serializers.ModelSerializer):
    collector = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collector"].queryset = Employee.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
        )

    class Meta:
        model = CollectionRoute
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class RouteStopSerializer(serializers.ModelSerializer):
    route = TenantScopedRelatedField()
    loan = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["route"].queryset = CollectionRoute.objects.all()
        self.fields["loan"].queryset = Loan.objects.all()
        request = self.context.get("request")
        if request is not None and getattr(request, "membership", None) is not None:
            if request.membership.role == "employee":
                for field_name in ("route", "loan", "visit_order"):
                    self.fields[field_name].read_only = True

    class Meta:
        model = RouteStop
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class CollectorDailyCloseSerializer(serializers.ModelSerializer):
    collector = TenantScopedRelatedField(required=False)
    collector_name = serializers.CharField(source="collector.full_name", read_only=True)
    opening_cash = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    paperwork_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collector"].queryset = Employee.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
        )

    class Meta:
        model = CollectorDailyClose
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at", "collector_name")


class CollectorExpenseSerializer(serializers.ModelSerializer):
    collector = TenantScopedRelatedField(required=False)
    collector_name = serializers.CharField(source="collector.full_name", read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collector"].queryset = Employee.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
        )

    class Meta:
        model = CollectorExpense
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at", "collector_name")
