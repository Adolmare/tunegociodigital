from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.shortcuts import render
from django.views.generic import TemplateView
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import _build_unique_tenant_slug
from tenants.models import BusinessType, Membership, Tenant, TenantTool, Tool
from tenants.services import create_tenant, enable_tool, ensure_business_type

User = get_user_model()

MODULE_CONFIG = {
    "loans": {
        "business_type": "prestamista",
        "primary_tool": "loans",
        "tools": ["loans", "accounting"],
        "default_name": "Préstamos",
    },
    "barbershop": {
        "business_type": "barberia",
        "primary_tool": "barbershop",
        "tools": ["barbershop", "reservations", "catalog", "accounting"],
        "default_name": "Barbería",
    },
    "restaurante": {
        "business_type": "restaurante",
        "primary_tool": "catalog",
        "tools": ["catalog", "deliveries", "accounting"],
        "default_name": "Restaurante",
    },
    "lavadero": {
        "business_type": "lavadero",
        "primary_tool": "reservations",
        "tools": ["reservations", "catalog", "accounting"],
        "default_name": "Lavadero",
    },
}


def _ensure_admin_access():
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.admin_access', 'on', true)")


class IsPlatformAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )


class PlatformAdminPanelView(TemplateView):
    template_name = "administration/panel.html"


class UserModulesListAPIView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request, *args, **kwargs):
        _ensure_admin_access()
        users = (
            User.objects.all()
            .prefetch_related(
                "memberships",
                "memberships__tenant",
                "memberships__tenant__business_type",
                "memberships__tenant__tools",
                "memberships__tenant__tools__tool",
            )
            .order_by("-created_at")
        )

        data = []
        for u in users:
            tenants_list = []
            user_tools = set()
            for m in u.memberships.filter(is_active=True):
                t = m.tenant
                enabled_tools = list(
                    t.tools.filter(is_enabled=True).values_list("tool__code", flat=True)
                )
                user_tools.update(enabled_tools)
                tenants_list.append(
                    {
                        "id": str(t.id),
                        "name": t.name,
                        "slug": t.slug,
                        "role": m.role,
                        "business_type": t.business_type.code if t.business_type else "",
                        "enabled_tools": enabled_tools,
                    }
                )

            data.append(
                {
                    "id": str(u.id),
                    "username": u.username,
                    "email": u.email,
                    "full_name": u.full_name or u.username,
                    "is_staff": u.is_staff,
                    "is_superuser": u.is_superuser,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "tenants": tenants_list,
                    "modules": {
                        "loans": "loans" in user_tools,
                        "barbershop": "barbershop" in user_tools,
                        "restaurante": (
                            "restaurante" in [t["business_type"] for t in tenants_list]
                            and "catalog" in user_tools
                        ),
                        "lavadero": (
                            "lavadero" in [t["business_type"] for t in tenants_list]
                            and "reservations" in user_tools
                        ),
                    },
                }
            )

        return Response(data)


class ToggleModuleAPIView(APIView):
    permission_classes = [IsPlatformAdmin]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        _ensure_admin_access()
        user_id = request.data.get("user_id")
        module_code = request.data.get("module")
        enabled = bool(request.data.get("enabled"))
        tenant_id = request.data.get("tenant_id")
        business_name = request.data.get("business_name", "").strip()

        if not user_id or not module_code:
            raise ValidationError({"detail": "user_id y module son obligatorios."})

        if module_code not in MODULE_CONFIG:
            raise ValidationError({"detail": f"Módulo no reconocido: {module_code}."})

        cfg = MODULE_CONFIG[module_code]
        try:
            target_user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError):
            raise ValidationError({"detail": "Usuario no encontrado."})

        if enabled:
            # ACTIVATE MODULE
            if tenant_id:
                try:
                    tenant = Tenant.objects.get(pk=tenant_id)
                except (Tenant.DoesNotExist, ValueError):
                    raise ValidationError({"detail": "Negocio no encontrado."})

                # Enable tools on this specific tenant
                for t_code in cfg["tools"]:
                    try:
                        tool = Tool.objects.get(code=t_code)
                        enable_tool(tenant, tool)
                    except Tool.DoesNotExist:
                        pass
                Membership.objects.get_or_create(
                    user=target_user,
                    tenant=tenant,
                    defaults={"role": Membership.Role.OWNER, "is_active": True},
                )
            else:
                # Find if user already has a tenant of this business_type
                existing_m = (
                    Membership.objects.filter(
                        user=target_user,
                        tenant__business_type__code=cfg["business_type"],
                    )
                    .select_related("tenant")
                    .first()
                )

                if existing_m:
                    tenant = existing_m.tenant
                    if not existing_m.is_active:
                        existing_m.is_active = True
                        existing_m.save(update_fields=["is_active"])
                    for t_code in cfg["tools"]:
                        try:
                            tool = Tool.objects.get(code=t_code)
                            enable_tool(tenant, tool)
                        except Tool.DoesNotExist:
                            pass
                else:
                    # Create new tenant for this user with this module
                    bt = ensure_business_type(cfg["business_type"])
                    base_name = (
                        business_name
                        or f"{cfg['default_name']} {target_user.full_name or target_user.username}"
                    )
                    slug = _build_unique_tenant_slug(base_name)
                    tenant = create_tenant(
                        user=target_user,
                        name=base_name,
                        slug=slug,
                        business_type=bt,
                    )
        else:
            # DEACTIVATE MODULE
            if tenant_id:
                TenantTool.objects.filter(
                    tenant_id=tenant_id,
                    tool__code=cfg["primary_tool"],
                ).update(is_enabled=False)
            else:
                user_tenants = Tenant.objects.filter(
                    memberships__user=target_user,
                    business_type__code=cfg["business_type"],
                )
                TenantTool.objects.filter(
                    tenant__in=user_tenants,
                    tool__code=cfg["primary_tool"],
                ).update(is_enabled=False)

        return Response(
            {
                "status": "ok",
                "user_id": str(target_user.id),
                "module": module_code,
                "enabled": enabled,
            }
        )


class CreateTenantForUserAPIView(APIView):
    permission_classes = [IsPlatformAdmin]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        _ensure_admin_access()
        user_id = request.data.get("user_id")
        business_type_code = request.data.get("business_type")
        name = str(request.data.get("name") or "").strip()

        if not user_id or not business_type_code or not name:
            raise ValidationError({"detail": "user_id, business_type y name son obligatorios."})

        try:
            target_user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError):
            raise ValidationError({"detail": "Usuario no encontrado."})

        bt = ensure_business_type(business_type_code)
        slug = _build_unique_tenant_slug(name)
        tenant = create_tenant(
            user=target_user,
            name=name,
            slug=slug,
            business_type=bt,
        )

        return Response(
            {
                "status": "ok",
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "tenant_slug": tenant.slug,
                "business_type": bt.code,
                "user_id": str(target_user.id),
            },
            status=status.HTTP_201_CREATED,
        )
