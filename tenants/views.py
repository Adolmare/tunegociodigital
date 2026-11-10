from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from employees.models import Employee
from .api import HasRole, TenantContextMixin, set_database_context
from .models import BusinessType, Membership, Tenant, TenantJoinRequest, Tool
from .serializers import (
    EmployeeJoinRequestSerializer,
    TenantCreateSerializer,
    TenantSerializer,
)
from .services import create_tenant


class TenantListCreateAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TenantCreateSerializer

    def get(self, request, *args, **kwargs):
        set_database_context(request.user.pk)
        tenants = Tenant.objects.filter(
            memberships__user=request.user,
            memberships__is_active=True,
        ).distinct()
        return Response(TenantSerializer(tenants, many=True, context={"request": request}).data)

    def post(self, request, *args, **kwargs):
        set_database_context(request.user.pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = create_tenant(
            user=request.user,
            name=serializer.validated_data["name"],
            slug=serializer.validated_data["slug"],
            business_type=serializer.validated_data.get("business_type"),
        )
        membership = Membership.objects.get(user=request.user, tenant=tenant)
        return Response(
            {
                "tenant": TenantSerializer(tenant, context={"request": request}).data,
                "role": membership.role,
            },
            status=status.HTTP_201_CREATED,
        )


class EmployeeJoinRequestViewSet(TenantContextMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, HasRole]
    min_role = "owner"
    serializer_class = EmployeeJoinRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return (
            TenantJoinRequest.objects.filter(
                tenant=self.request.tenant,
                status=TenantJoinRequest.Status.PENDING,
            )
            .select_related("user")
            .order_by("created_at")
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def approve(self, request, pk=None):
        join_request = self.get_object()
        membership = Membership.objects.filter(
            user=join_request.user, tenant=request.tenant
        ).first()
        if membership is not None and membership.role != Membership.Role.EMPLOYEE:
            raise ValidationError({
                "request_id": "El usuario ya tiene otro rol en este negocio."
            })
        if membership is None:
            Membership.objects.create(
                user=join_request.user,
                tenant=request.tenant,
                role=Membership.Role.EMPLOYEE,
                is_active=True,
            )
        elif not membership.is_active:
            membership.is_active = True
            membership.save(update_fields=["is_active"])

        employee, created = Employee.unscoped.get_or_create(
            tenant=request.tenant,
            user=join_request.user,
            defaults={
                "full_name": join_request.user.full_name or join_request.user.username,
                "position": "Cobrador",
                "is_active": True,
            },
        )
        if not created and (not employee.is_active or employee.deleted_at is not None):
            employee.is_active = True
            employee.deleted_at = None
            employee.save(update_fields=["is_active", "deleted_at", "updated_at"])

        join_request.status = TenantJoinRequest.Status.ACCEPTED
        join_request.decided_by = request.user
        join_request.decided_at = timezone.now()
        join_request.save(update_fields=["status", "decided_by", "decided_at"])
        return Response({"status": join_request.status})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        join_request = self.get_object()
        join_request.status = TenantJoinRequest.Status.REJECTED
        join_request.decided_by = request.user
        join_request.decided_at = timezone.now()
        join_request.save(update_fields=["status", "decided_by", "decided_at"])
        return Response({"status": join_request.status})
