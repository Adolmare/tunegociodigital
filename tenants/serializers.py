from rest_framework import serializers

from .models import BusinessType, Membership, Tenant


class TenantSerializer(serializers.ModelSerializer):
    join_code = serializers.SerializerMethodField()

    def get_join_code(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        role = Membership.objects.filter(
            tenant=obj, user=request.user, is_active=True
        ).values_list("role", flat=True).first()
        if role in {Membership.Role.OWNER, Membership.Role.ADMIN}:
            return obj.join_code
        return None

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
