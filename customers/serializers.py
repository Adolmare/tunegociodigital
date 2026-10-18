from rest_framework import serializers
from rest_framework_gis.fields import GeometryField

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    location = GeometryField(required=False, allow_null=True)

    def validate_neighborhood(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Selecciona o escribe un barrio.")
        return value

    class Meta:
        model = Customer
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at", "deleted_at")
        extra_kwargs = {
            "neighborhood": {"required": True, "allow_blank": False},
        }
