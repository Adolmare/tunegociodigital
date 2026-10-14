from rest_framework import serializers

from tenants.api import TenantScopedRelatedField

from .models import CollectionRoute, Loan, LoanPayment, RouteStop


class LoanSerializer(serializers.ModelSerializer):
    customer = TenantScopedRelatedField()
    collector = TenantScopedRelatedField(required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from customers.models import Customer
        from employees.models import Employee

        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["collector"].queryset = Employee.objects.all()

    class Meta:
        model = Loan
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class LoanPaymentSerializer(serializers.ModelSerializer):
    loan = TenantScopedRelatedField()
    collector = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from employees.models import Employee

        self.fields["loan"].queryset = Loan.objects.all()
        self.fields["collector"].queryset = Employee.objects.all()

    class Meta:
        model = LoanPayment
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class CollectionRouteSerializer(serializers.ModelSerializer):
    collector = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from employees.models import Employee

        self.fields["collector"].queryset = Employee.objects.all()

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

    class Meta:
        model = RouteStop
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")
