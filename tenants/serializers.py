from rest_framework import serializers

from .models import BusinessType, EmployeeJoinRequest, Tenant


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "business_type",
            "status",
            "timezone",
            "currency",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class TenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    slug = serializers.SlugField(max_length=50)
    business_type = serializers.SlugRelatedField(
        slug_field="code",
        queryset=BusinessType.objects.all(),
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        unexpected_tenant_fields = {"tenant", "tenant_id"}.intersection(self.initial_data)
        if unexpected_tenant_fields:
            raise serializers.ValidationError(
                "El tenant se determina al crear la empresa y no se acepta en la solicitud."
            )
        if Tenant.objects.filter(slug=attrs["slug"]).exists():
            raise serializers.ValidationError({"slug": "Este slug ya está en uso."})
        return attrs


class EmployeeJoinRequestSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = EmployeeJoinRequest
        fields = ("id", "username", "full_name", "email", "status", "created_at")
        read_only_fields = fields
