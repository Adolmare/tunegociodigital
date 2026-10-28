from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from rest_framework import serializers

from tenants.models import Membership

from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    username = serializers.CharField(
        max_length=150,
        validators=[UnicodeUsernameValidator()],
    )

    class Meta:
        model = User
        fields = ("id", "username", "email", "full_name", "password")
        read_only_fields = ("id",)

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "full_name", "created_at")
        read_only_fields = ("id", "username", "email", "created_at")


class MyMembershipSerializer(serializers.ModelSerializer):
    tenant_id = serializers.UUIDField(source="tenant.id", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    tenant_slug = serializers.CharField(source="tenant.slug", read_only=True)
    tenant_join_code = serializers.SerializerMethodField()
    tenant_currency = serializers.CharField(source="tenant.currency", read_only=True)

    def get_tenant_join_code(self, obj):
        if obj.role in {Membership.Role.OWNER, Membership.Role.ADMIN}:
            return obj.tenant.join_code
        return None

    class Meta:
        model = Membership
        fields = (
            "tenant_id",
            "tenant_name",
            "tenant_slug",
            "tenant_join_code",
            "tenant_currency",
            "role",
        )
