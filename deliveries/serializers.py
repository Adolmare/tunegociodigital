from rest_framework import serializers

from tenants.api import TenantScopedRelatedField

from .models import DeliveryOrder, DeliveryOrderItem


class DeliveryOrderSerializer(serializers.ModelSerializer):
    customer = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from customers.models import Customer

        self.fields["customer"].queryset = Customer.objects.all()

    class Meta:
        model = DeliveryOrder
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class DeliveryOrderItemSerializer(serializers.ModelSerializer):
    order = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].queryset = DeliveryOrder.objects.all()

    class Meta:
        model = DeliveryOrderItem
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")
