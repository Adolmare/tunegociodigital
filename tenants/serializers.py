from rest_framework import serializers

from .models import Membership, Tenant, TenantApiKey


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


class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ["id", "user", "tenant", "role", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class TenantApiKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantApiKey
        fields = ["id", "tenant", "name", "key_hash", "scopes", "revoked_at", "created_at"]
        read_only_fields = ["id", "key_hash", "created_at"]
