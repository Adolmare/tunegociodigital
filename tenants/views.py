from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from .api import TenantContextMixin, set_database_context
from .models import EmployeeJoinRequest, Membership, Tenant
from .serializers import EmployeeJoinRequestSerializer, TenantCreateSerializer, TenantSerializer
from .services import create_tenant
from employees.models import Employee


class IsTenantOwner(BasePermission):
    def has_permission(self, request, view):
        return getattr(getattr(request, "membership", None), "role", None) == "owner"


class EmployeeJoinRequestViewSet(TenantContextMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsTenantOwner]
    serializer_class = EmployeeJoinRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return EmployeeJoinRequest.objects.filter(
            tenant=self.request.tenant,
            status=EmployeeJoinRequest.Status.PENDING,
        ).select_related("user").order_by("created_at")

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def approve(self, request, pk=None):
        join_request = self.get_object()
        join_request.status = EmployeeJoinRequest.Status.APPROVED
        join_request.reviewed_by = request.user
        join_request.reviewed_at = timezone.now()
        join_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        Membership.objects.update_or_create(
            user=join_request.user,
            tenant=request.tenant,
            defaults={"role": Membership.Role.EMPLOYEE, "is_active": True},
        )
        Employee.objects.get_or_create(
            tenant=request.tenant,
            user=join_request.user,
            defaults={"full_name": join_request.user.full_name or join_request.user.username},
        )
        return Response({"status": join_request.status})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        join_request = self.get_object()
        join_request.status = EmployeeJoinRequest.Status.REJECTED
        join_request.reviewed_by = request.user
        join_request.reviewed_at = timezone.now()
        join_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        return Response({"status": join_request.status})


class TenantListCreateAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TenantCreateSerializer

    def get(self, request, *args, **kwargs):
        set_database_context(request.user.pk)
        tenants = Tenant.objects.filter(
            memberships__user=request.user,
            memberships__is_active=True,
        ).distinct()
        return Response(TenantSerializer(tenants, many=True).data)

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
                "tenant": TenantSerializer(tenant).data,
                "role": membership.role,
            },
            status=status.HTTP_201_CREATED,
        )
