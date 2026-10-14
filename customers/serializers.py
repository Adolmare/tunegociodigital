from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at", "deleted_at")
