from rest_framework import serializers

from tenants.api import TenantScopedRelatedField

from .models import Reservation, ReservationItem


class ReservationSerializer(serializers.ModelSerializer):
    customer = TenantScopedRelatedField()
    employee = TenantScopedRelatedField(required=False, allow_null=True)
    vehicle = TenantScopedRelatedField(required=False, allow_null=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from customers.models import Customer
        from employees.models import Employee
        from vehicles.models import Vehicle

        self.fields["customer"].queryset = Customer.objects.all()
        self.fields["employee"].queryset = Employee.objects.all()
        self.fields["vehicle"].queryset = Vehicle.objects.all()

    class Meta:
        model = Reservation
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class ReservationItemSerializer(serializers.ModelSerializer):
    reservation = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reservation"].queryset = Reservation.objects.all()

    class Meta:
        model = ReservationItem
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")
