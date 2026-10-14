import uuid

from django.core.exceptions import ValidationError
from django.db import connection
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated

from core.context import clear_tenant, set_tenant
from core.context import get_tenant
from .models import Membership, TenantTool

RANK = {"employee": 1, "manager": 2, "admin": 3, "owner": 4}


def _set_database_context(user_id, tenant_id=None):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", [str(user_id)])
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)",
            [str(tenant_id) if tenant_id is not None else ""],
        )


class TenantContextMixin:
    def initial(self, request, *args, **kwargs):
        self.perform_authentication(request)
        tenant_id = request.headers.get("X-Tenant-ID")
        if not tenant_id:
            raise NotFound()
        try:
            tenant_id = uuid.UUID(tenant_id)
        except (AttributeError, TypeError, ValueError):
            raise NotFound()
        _set_database_context(request.user.pk, tenant_id)
        try:
            membership = Membership.objects.select_related("tenant").get(
                user=request.user,
                tenant_id=tenant_id,
                is_active=True,
                tenant__status__in=["trial", "active"],
            )
        except (Membership.DoesNotExist, ValidationError, ValueError):
            raise NotFound()

        request.tenant = membership.tenant
        request.membership = membership
        set_tenant(membership.tenant)
        super().initial(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            clear_tenant()


class HasTool(BasePermission):
    def has_permission(self, request, view):
        code = getattr(view, "required_tool", None)
        if code is None:
            return True
        return TenantTool.objects.filter(
            tenant=request.tenant,
            tool__code=code,
            is_enabled=True,
        ).exists()


class HasRole(BasePermission):
    def has_permission(self, request, view):
        membership = getattr(request, "membership", None)
        if membership is None:
            return False
        role_by_action = getattr(view, "role_by_action", {})
        required = role_by_action.get(
            getattr(view, "action", None),
            getattr(view, "min_role", "employee"),
        )
        return RANK.get(membership.role, 0) >= RANK.get(required, 0)


class TenantScopedRelatedField(serializers.PrimaryKeyRelatedField):
    def __init__(self, queryset=None, **kwargs):
        self.queryset = queryset
        super().__init__(**kwargs)

    def get_queryset(self):
        if self.queryset is not None:
            return self.queryset
        return super().get_queryset()


class TenantRelatedField(serializers.PrimaryKeyRelatedField):
    def __init__(self, model, **kwargs):
        self.related_model = model
        super().__init__(queryset=model.unscoped.none(), **kwargs)

    def get_queryset(self):
        if get_tenant() is None:
            return self.related_model.unscoped.none()
        return self.related_model.objects.all()


class TenantMemberUserField(serializers.PrimaryKeyRelatedField):
    def __init__(self, **kwargs):
        from accounts.models import User

        self.related_model = User
        super().__init__(queryset=User.objects.none(), **kwargs)

    def get_queryset(self):
        tenant = get_tenant()
        if tenant is None:
            return self.related_model.objects.none()
        return self.related_model.objects.filter(
            memberships__tenant=tenant,
            memberships__is_active=True,
        )


class ActionMinRoleMixin:
    role_by_action = {}

    def get_permissions(self):
        self.min_role = self.role_by_action.get(self.action, getattr(self, "min_role", "employee"))
        return super().get_permissions()


class TenantViewSet(TenantContextMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasTool, HasRole]
    required_tool = None
    min_role = "employee"

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)
