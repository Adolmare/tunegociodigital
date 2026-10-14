from rest_framework import serializers

from customers.models import Customer
from tenants.api import TenantRelatedField

from .models import Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    customer = TenantRelatedField(model=Customer)

    class Meta:
        model = Vehicle
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")
