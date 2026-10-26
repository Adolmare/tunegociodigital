from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from employees.models import Employee
from tenants.api import HasRole, TenantContextMixin, set_database_context
from tenants.models import Membership, Tenant, TenantJoinRequest


class TenantJoinRequestCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        code = str(request.data.get("join_code", "")).strip().upper()
        if not code:
            raise ValidationError({"join_code": "Introduce el código del negocio."})

        with transaction.atomic():
            tenant = Tenant.objects.filter(
                join_code=code,
                status__in=[Tenant.Status.TRIAL, Tenant.Status.ACTIVE],
            ).first()
            if tenant is None:
                raise NotFound("El código del negocio no existe o no está disponible.")

            set_database_context(request.user.pk, tenant.pk)
            existing_membership = Membership.objects.filter(
                user=request.user, tenant=tenant, is_active=True
            ).first()
            if existing_membership is not None:
                raise ValidationError({"join_code": "Ya perteneces a este negocio."})

            existing_request = TenantJoinRequest.objects.filter(
                user=request.user, tenant=tenant, status=TenantJoinRequest.Status.PENDING
            ).first()
            if existing_request is not None:
                raise ValidationError({"request": "Ya tienes una solicitud pendiente para este negocio."})

            join_request = TenantJoinRequest.objects.create(
                user=request.user, tenant=tenant
            )
            return Response(
                {
                    "id": str(join_request.pk),
                    "tenant_id": str(tenant.pk),
                    "tenant_name": tenant.name,
                    "status": join_request.status,
                    "created_at": join_request.created_at,
                },
                status=status.HTTP_201_CREATED,
            )


class TenantJoinRequestManageAPIView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasRole]
    min_role = "owner"

    def get(self, request):
        pending = TenantJoinRequest.objects.filter(
            tenant=request.tenant, status=TenantJoinRequest.Status.PENDING
        ).select_related("user").order_by("created_at")
        return Response([
            {
                "id": str(item.pk),
                "user_id": str(item.user_id),
                "username": item.user.username,
                "full_name": item.user.full_name,
                "email": item.user.email,
                "status": item.status,
                "created_at": item.created_at,
            }
            for item in pending
        ])

    def post(self, request):
        request_id = request.data.get("request_id")
        decision = request.data.get("decision")
        if decision not in {"accept", "reject"}:
            raise ValidationError({"decision": "Usa accept o reject."})
        if not request_id:
            raise ValidationError({"request_id": "Indica la solicitud que vas a revisar."})

        with transaction.atomic():
            try:
                join_request = TenantJoinRequest.objects.select_for_update().select_related(
                    "user", "tenant"
                ).get(
                    pk=request_id,
                    tenant=request.tenant,
                    status=TenantJoinRequest.Status.PENDING,
                )
            except (TenantJoinRequest.DoesNotExist, ValueError):
                raise NotFound("La solicitud no existe o ya fue revisada.")

            if decision == "accept":
                membership = Membership.objects.filter(
                    user=join_request.user, tenant=request.tenant
                ).first()
                if membership is not None and membership.role != Membership.Role.EMPLOYEE:
                    raise ValidationError({
                        "request_id": "El usuario ya tiene otro rol en este negocio; revisa su membresía manualmente."
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
            else:
                join_request.status = TenantJoinRequest.Status.REJECTED

            join_request.decided_by = request.user
            join_request.decided_at = timezone.now()
            join_request.save(update_fields=["status", "decided_by", "decided_at"])
            return Response({
                "id": str(join_request.pk),
                "status": join_request.status,
                "user_id": str(join_request.user_id),
                "tenant_id": str(request.tenant.pk),
            })
