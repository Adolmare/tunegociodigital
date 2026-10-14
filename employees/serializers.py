from rest_framework import serializers

from tenants.api import TenantMemberUserField

from .models import Employee


class EmployeeSerializer(serializers.ModelSerializer):
    user = TenantMemberUserField(required=False, allow_null=True)

    class Meta:
        model = Employee
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at", "deleted_at")
