from rest_framework import serializers

from .models import BusinessType, Tenant


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "slug",
            "join_code",
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
