from rest_framework import serializers
from rest_framework_gis.fields import GeometryField

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    location = GeometryField(required=False, allow_null=True)

    class Meta:
        model = Customer
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at", "deleted_at")
