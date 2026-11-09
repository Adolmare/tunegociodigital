import secrets

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from tenants.api import set_database_context
from tenants.models import BusinessType, Membership, Tenant, TenantJoinRequest, Tool
from tenants.services import create_tenant

from .models import User


def _build_unique_tenant_slug(name: str) -> str:
    base = slugify(name or "negocio")[:38] or "negocio"
    candidate = base
    while Tenant.objects.filter(slug=candidate).exists():
        suffix = secrets.token_hex(3)
        candidate = f"{base}-{suffix}"
    return candidate


class LoginSerializer(TokenObtainPairSerializer):
    default_error_messages = {
        "no_active_account": "Usuario o contraseña incorrectos. Verifica tus datos e inténtalo de nuevo."
    }

    def validate(self, attrs):
        raw_username = str(attrs.get(self.username_field, "")).strip()
        if raw_username and "@" not in raw_username:
            matched_user = User.objects.filter(username__iexact=raw_username).first()
            if matched_user is not None:
                attrs[self.username_field] = matched_user.username
            else:
                attrs[self.username_field] = raw_username
        data = super().validate(attrs)
        data["username"] = self.user.username
        data["full_name"] = self.user.full_name
        data["email"] = self.user.email
        return data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        validators=[validate_password],
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )
    username = serializers.CharField(
        max_length=150,
        validators=[UnicodeUsernameValidator()],
    )
    register_role = serializers.ChoiceField(
        choices=[("collector", "Cobrador"), ("owner", "Dueño")],
        required=False,
        write_only=True,
    )
    join_code = serializers.CharField(
        max_length=16,
        required=False,
        allow_blank=True,
        write_only=True,
    )
    business_name = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
        write_only=True,
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "full_name",
            "password",
            "password_confirm",
            "register_role",
            "join_code",
            "business_name",
        )
        read_only_fields = ("id",)
        extra_kwargs = {
            "email": {"validators": []},
        }

    def validate_username(self, value):
        clean = str(value or "").strip()
        if not clean:
            raise serializers.ValidationError("Ingresa un nombre de usuario válido.")
        if User.objects.filter(username__iexact=clean).exists():
            raise serializers.ValidationError(
                "Este nombre de usuario ya está en uso. Elige otro."
            )
        return clean

    def validate_email(self, value):
        clean = str(value or "").strip().lower()
        if not clean:
            raise serializers.ValidationError("Ingresa un correo electrónico válido.")
        if User.objects.filter(email__iexact=clean).exists():
            raise serializers.ValidationError(
                "Ya existe una cuenta registrada con este correo electrónico."
            )
        return clean

    def validate(self, attrs):
        password = attrs.get("password", "")
        if "password_confirm" in self.initial_data:
            confirm = attrs.get("password_confirm", "")
            if confirm != password:
                raise serializers.ValidationError(
                    {"password_confirm": "Las contraseñas no coinciden."}
                )

        candidate_user = User(
            username=attrs.get("username", ""),
            email=attrs.get("email", ""),
            full_name=attrs.get("full_name", ""),
        )
        try:
            validate_password(password, user=candidate_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})

        role = attrs.get("register_role")
        if role == "collector":
            code = str(attrs.get("join_code") or "").strip().upper()
            if not code:
                raise serializers.ValidationError(
                    {"join_code": "Ingresa el código del negocio entregado por el propietario."}
                )
            tenant = Tenant.objects.filter(
                join_code=code,
                status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE],
            ).first()
            if tenant is None:
                raise serializers.ValidationError(
                    {
                        "join_code": "El código del negocio no existe o no está activo. Verifica el código con el propietario."
                    }
                )
            attrs["_target_tenant"] = tenant
            attrs["join_code"] = code
        elif role == "owner":
            biz_name = str(attrs.get("business_name") or "").strip()
            if not biz_name:
                raise serializers.ValidationError(
                    {"business_name": "Ingresa el nombre de tu negocio de préstamos."}
                )
            attrs["business_name"] = biz_name

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("password_confirm", None)
        role = validated_data.pop("register_role", None)
        validated_data.pop("join_code", None)
        business_name = validated_data.pop("business_name", None)
        target_tenant = validated_data.pop("_target_tenant", None)

        user = User.objects.create_user(**validated_data)

        if role == "owner" and business_name:
            set_database_context(user.pk)
            loans_tool, _ = Tool.objects.get_or_create(
                code="loans",
                defaults={"name": "Préstamos", "is_core": False},
            )
            accounting_tool, _ = Tool.objects.get_or_create(
                code="accounting",
                defaults={"name": "Contabilidad", "is_core": True},
            )
            bt, _ = BusinessType.objects.get_or_create(
                code="prestamista",
                defaults={"name": "Prestamista"},
            )
            bt.tools.add(loans_tool, accounting_tool)
            slug = _build_unique_tenant_slug(business_name)
            tenant = create_tenant(
                user=user,
                name=business_name,
                slug=slug,
                business_type=bt,
            )
            user._created_tenant = tenant
        elif role == "collector" and target_tenant is not None:
            set_database_context(user.pk, target_tenant.pk)
            join_request = TenantJoinRequest.objects.create(
                user=user,
                tenant=target_tenant,
            )
            user._created_join_request = join_request

        refresh = RefreshToken.for_user(user)
        user._tokens = {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }
        return user

    def to_representation(self, instance):
        data = super().to_representation(instance)
        tokens = getattr(instance, "_tokens", None)
        if tokens:
            data["access"] = tokens["access"]
            data["refresh"] = tokens["refresh"]
        created_tenant = getattr(instance, "_created_tenant", None)
        if created_tenant is not None:
            data["tenant"] = {
                "tenant_id": str(created_tenant.pk),
                "tenant_name": created_tenant.name,
                "tenant_slug": created_tenant.slug,
                "tenant_join_code": created_tenant.join_code,
                "tenant_currency": created_tenant.currency,
                "role": Membership.Role.OWNER,
            }
        created_join_request = getattr(instance, "_created_join_request", None)
        if created_join_request is not None:
            data["join_request"] = {
                "id": str(created_join_request.pk),
                "tenant_id": str(created_join_request.tenant_id),
                "tenant_name": created_join_request.tenant.name,
                "status": created_join_request.status,
            }
        return data


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
