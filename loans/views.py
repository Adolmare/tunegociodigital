from datetime import datetime
import json
import time
import uuid

from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import EventInbox
from tenants.api import (
    ActionMinRoleMixin,
    HasRole,
    HasTool,
    TenantContextMixin,
    TenantViewSet,
    set_database_context,
)

from employees.models import Employee

from .models import CollectionRoute, Loan, LoanInstallment, LoanPayment, RouteStop
from .serializers import (
    CollectionRouteSerializer,
    LoanInstallmentSerializer,
    LoanPaymentSerializer,
    LoanSerializer,
    RouteStopSerializer,
)
from .services import (
    create_loan,
    overdue_installments,
    register_payment,
    reverse_payment,
)


class LoanViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "collection_today": "employee",
        "destroy": "owner",
        "update": "manager",
        "partial_update": "manager",
    }
    serializer_class = LoanSerializer

    def get_queryset(self):
        queryset = Loan.objects.all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        return queryset

    def perform_create(self, serializer):
        data = serializer.validated_data.copy()
        if self.request.membership.role == "employee":
            collector = Employee.objects.filter(
                user=self.request.user,
                is_active=True,
                deleted_at__isnull=True,
            ).first()
            if collector is None:
                raise ValidationError(
                    {"collector": "El usuario no tiene un perfil de cobrador activo."}
                )
            data["collector"] = collector
        serializer.instance = create_loan(
            tenant=self.request.tenant,
            **data,
        )

    @action(detail=False, methods=["get"], url_path="collection-today")
    def collection_today(self, request):
        collector = None
        if request.membership.role == "employee":
            collector = Employee.objects.filter(
                user=request.user,
                is_active=True,
                deleted_at__isnull=True,
            ).first()
            if collector is None:
                return Response([])
        installments = overdue_installments(
            tenant=request.tenant,
            collector=collector,
        )
        page = self.paginate_queryset(installments)
        if page is not None:
            data = LoanInstallmentSerializer(page, many=True).data
            return self.get_paginated_response(data)
        return Response(LoanInstallmentSerializer(installments, many=True).data)


class LoanPaymentViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "reverse": "owner",
        "update": "employee",
        "partial_update": "employee",
        "destroy": "employee",
    }
    http_method_names = ["get", "post", "head", "options"]
    serializer_class = LoanPaymentSerializer

    def get_queryset(self):
        queryset = LoanPayment.objects.all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        return queryset

    def perform_create(self, serializer):
        data = serializer.validated_data.copy()
        loan = data.pop("loan")
        collector = data.pop("collector", None)
        if self.request.membership.role == "employee":
            collector = Employee.objects.filter(
                user=self.request.user,
                is_active=True,
                deleted_at__isnull=True,
            ).first()
            if collector is None:
                raise ValidationError(
                    {"collector": "El usuario no tiene un perfil de cobrador activo."}
                )
        elif collector is None:
            raise ValidationError({"collector": "Debes indicar el cobrador que recibió el abono."})
        serializer.instance = register_payment(
            loan=loan,
            collector=collector,
            user=self.request.user,
            **data,
        )

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        payment = self.get_object()
        reversal = reverse_payment(payment=payment, user=request.user)
        return Response(
            self.get_serializer(reversal).data,
            status=status.HTTP_201_CREATED,
        )


class LoanPaymentEventStreamView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasTool, HasRole]
    required_tool = "loans"
    min_role = "admin"
    http_method_names = ["get", "options"]

    def get(self, request):
        last_event_id = request.headers.get("Last-Event-ID")
        seen_event_ids = set()
        if last_event_id:
            timestamp, separator, event_id = last_event_id.partition("|")
            if not separator:
                raise ValidationError(
                    {"Last-Event-ID": "El identificador del último evento no es válido."}
                )
            try:
                cursor = datetime.fromisoformat(timestamp)
                event_id = uuid.UUID(event_id)
            except (TypeError, ValueError):
                raise ValidationError(
                    {"Last-Event-ID": "El identificador del último evento no es válido."}
                )
            if timezone.is_naive(cursor):
                raise ValidationError(
                    {"Last-Event-ID": "La fecha del último evento debe incluir zona horaria."}
                )
            seen_event_ids.add(event_id)
        else:
            cursor = timezone.now()

        tenant_id = str(request.tenant.pk)
        user_id = str(request.user.pk)

        def stream():
            nonlocal cursor
            yield "event: ready\ndata: {}\n\n"
            last_heartbeat = time.monotonic()
            while True:
                with transaction.atomic():
                    set_database_context(user_id, tenant_id)
                    events = list(
                        EventInbox.unscoped.filter(
                            tenant_id=tenant_id,
                            event_name="loan.payment_received",
                            occurred_at__gte=cursor,
                        )
                        .order_by("occurred_at", "id")
                        .values("id", "occurred_at", "payload")[:100]
                    )

                for event in events:
                    occurred_at = event["occurred_at"]
                    if occurred_at > cursor:
                        cursor = occurred_at
                        seen_event_ids.clear()
                    if event["id"] in seen_event_ids:
                        continue
                    seen_event_ids.add(event["id"])
                    data = {
                        "id": str(event["id"]),
                        "occurred_at": occurred_at.isoformat(),
                        "payload": event["payload"],
                    }
                    event_id = f"{occurred_at.isoformat()}|{event['id']}"
                    yield (
                        f"id: {event_id}\n"
                        "event: loan.payment_received\n"
                        f"data: {json.dumps(data, separators=(',', ':'))}\n\n"
                    )

                if not events and time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
                time.sleep(1)

        response = StreamingHttpResponse(stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class LoanInstallmentViewSet(TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    http_method_names = ["get", "head", "options"]
    serializer_class = LoanInstallmentSerializer

    def get_queryset(self):
        queryset = LoanInstallment.objects.select_related("loan").all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(loan__collector__user=self.request.user)
        return queryset


class CollectionRouteViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "destroy": "owner",
        "update": "manager",
        "partial_update": "manager",
    }
    serializer_class = CollectionRouteSerializer

    def get_queryset(self):
        queryset = CollectionRoute.objects.all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        return queryset


class RouteStopViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "partial_update": "employee",
        "destroy": "owner",
        "update": "manager",
    }
    serializer_class = RouteStopSerializer

    def get_queryset(self):
        queryset = RouteStop.objects.all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(route__collector__user=self.request.user)
        return queryset
