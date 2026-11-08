import asyncio
from datetime import datetime
import json
import time
import uuid
from decimal import Decimal

from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Case, DecimalField, F, Q, Sum, When
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
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

from .excel_export import build_loans_excel_workbook
from .models import CollectionRoute, Loan, LoanInstallment, LoanPayment, RouteStop
from .serializers import (
    CollectionRouteSerializer,
    LoanLedgerQuerySerializer,
    LoanInstallmentSerializer,
    LoanPaymentSerializer,
    LoanSerializer,
    RouteStopSerializer,
)
from .services import (
    create_loan,
    overdue_installments,
    ledger_period_dates,
    register_payment,
    reverse_payment,
)


def _read_payment_events(user_id, tenant_id, cursor, collector_id=None):
    """Lee eventos de pagos del negocio.

    Si ``collector_id`` viene informado (empleados), solo devuelve los eventos
    cuyo cobrador coincide; los roles de gestión ven todos los del negocio.
    """
    with transaction.atomic():
        set_database_context(user_id, tenant_id)
        queryset = EventInbox.unscoped.filter(
            tenant_id=tenant_id,
            event_name__in=["loan.payment_received", "loan.payment_reversed"],
            occurred_at__gte=cursor,
        )
        if collector_id is not None:
            queryset = queryset.filter(payload__collector_id=str(collector_id))
        return list(
            queryset.order_by("occurred_at", "id").values(
                "id", "occurred_at", "event_name", "payload"
            )[:100]
        )


class LoanViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "collection_today": "employee",
        "ledger": "owner",
        "export_excel": "manager",
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

    def _compute_ledger(self, request):
        filters = LoanLedgerQuerySerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        period = filters.validated_data["period"]
        selected_date = filters.validated_data["date"]
        raw_frequency = request.query_params.get("frequency")
        frequency = filters.validated_data.get("frequency")
        period_to_frequency = {
            "day": "daily",
            "week": "weekly",
            "fortnight": "biweekly",
            "month": "monthly",
        }
        if (not raw_frequency or raw_frequency == "auto") and period in period_to_frequency:
            frequency = period_to_frequency[period]
        period_start, period_end = ledger_period_dates(period, selected_date)

        loans = list(Loan.objects.select_related("customer"))
        imported_items = {}
        for loan in loans:
            reference = loan.import_reference.rpartition(":")[2]
            if reference.isdigit():
                imported_items[loan.pk] = int(reference)
        loans.sort(
            key=lambda loan: (
                (0, imported_items[loan.pk], "")
                if loan.pk in imported_items
                else (1, loan.created_at, str(loan.pk))
            )
        )
        next_item = max(imported_items.values(), default=0)
        item_numbers = {}
        for loan in loans:
            if loan.pk in imported_items:
                item_numbers[loan.pk] = imported_items[loan.pk]
            else:
                next_item += 1
                item_numbers[loan.pk] = next_item
        loans = [loan for loan in loans if loan.start_date <= period_end]

        payments = (
            LoanPayment.objects.filter(
                loan_id__in=[loan.pk for loan in loans],
                paid_at__date__lte=period_end,
            )
            .annotate(
                signed_amount=Case(
                    When(direction="reversal", then=-F("amount")),
                    default=F("amount"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
            .values("loan_id")
            .annotate(
                before_period=Sum(
                    "signed_amount",
                    filter=Q(paid_at__date__lt=period_start),
                ),
                in_period=Sum(
                    "signed_amount",
                    filter=Q(
                        paid_at__date__gte=period_start,
                        paid_at__date__lte=period_end,
                    ),
                ),
            )
        )
        payment_totals = {
            row["loan_id"]: (
                row["before_period"] or Decimal("0.00"),
                row["in_period"] or Decimal("0.00"),
            )
            for row in payments
        }

        frequency_labels = {
            "daily": "DIARIO",
            "weekly": "SEMANAL",
            "biweekly": "QUINCENAL",
            "monthly": "MENSUAL",
        }
        weekdays = (
            "lunes",
            "martes",
            "miércoles",
            "jueves",
            "viernes",
            "sábado",
            "domingo",
        )
        rows = []
        totals = {
            key: Decimal("0.00")
            for key in (
                "principal",
                "paperwork_fee",
                "interest",
                "total_payable",
                "abono",
                "collected",
                "remaining",
            )
        }
        for loan in loans:
            if frequency != "all" and loan.frequency != frequency:
                continue
            historical_paid, period_paid = payment_totals.get(
                loan.pk,
                (Decimal("0.00"), Decimal("0.00")),
            )
            abono = loan.opening_paid + historical_paid
            collected = period_paid
            remaining = loan.total_payable - abono - collected
            interest = loan.total_payable - loan.principal
            rows.append(
                {
                    "item": item_numbers[loan.pk],
                    "date": loan.start_date.isoformat(),
                    "day": weekdays[loan.start_date.weekday()],
                    "customer": loan.customer.full_name,
                    "neighborhood": loan.customer.neighborhood,
                    "concept": frequency_labels.get(loan.frequency, loan.frequency.upper()),
                    "principal": loan.principal,
                    "paperwork_fee": loan.paperwork_fee,
                    "interest": interest,
                    "total_payable": loan.total_payable,
                    "abono": abono,
                    "collected": collected,
                    "remaining": remaining,
                }
            )
            totals["principal"] += loan.principal
            totals["paperwork_fee"] += loan.paperwork_fee
            totals["interest"] += interest
            totals["total_payable"] += loan.total_payable
            totals["abono"] += abono
            totals["collected"] += collected
            totals["remaining"] += remaining

        rows.sort(key=lambda row: row["item"])
        return {
            "period": period,
            "selected_date": selected_date,
            "period_start": period_start,
            "period_end": period_end,
            "frequency": frequency,
            "rows": rows,
            "totals": totals,
        }

    @action(detail=False, methods=["get"])
    def ledger(self, request):
        report = self._compute_ledger(request)
        data = [
            {
                **row,
                **{
                    key: str(value)
                    for key, value in row.items()
                    if isinstance(value, Decimal)
                },
            }
            for row in report["rows"]
        ]
        return Response(
            {
                "period": report["period"],
                "period_start": report["period_start"].isoformat(),
                "period_end": report["period_end"].isoformat(),
                "frequency": report["frequency"],
                "rows": data,
                "totals": {key: str(value) for key, value in report["totals"].items()},
            }
        )

    @action(detail=False, methods=["get"], url_path="export-excel")
    def export_excel(self, request):
        report = self._compute_ledger(request)
        xlsx_bytes = build_loans_excel_workbook(
            tenant=request.tenant,
            period=report["period"],
            period_start=report["period_start"],
            period_end=report["period_end"],
            ledger_rows=report["rows"],
            ledger_totals=report["totals"],
        )
        filename = f"cartera_{request.tenant.slug}_{report['period']}_{report['selected_date'].isoformat()}.xlsx"
        response = HttpResponse(
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


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
    min_role = "employee"
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

        # Los empleados solo reciben los eventos de sus propios cobros.
        collector_id = None
        if request.membership.role == "employee":
            collector = Employee.objects.filter(
                user=request.user, is_active=True, deleted_at__isnull=True
            ).first()
            if collector is None:
                raise PermissionDenied("No tienes un perfil de cobrador activo.")
            collector_id = str(collector.pk)

        async def stream():
            nonlocal cursor
            yield "event: ready\ndata: {}\n\n"
            last_heartbeat = time.monotonic()
            while True:
                events = await sync_to_async(
                    _read_payment_events,
                    thread_sensitive=True,
                )(user_id, tenant_id, cursor, collector_id)

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
                    event_type = event.get("event_name", "loan.payment_received")
                    yield (
                        f"id: {event_id}\n"
                        f"event: {event_type}\n"
                        f"data: {json.dumps(data, separators=(',', ':'))}\n\n"
                    )

                if not events and time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(1)

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


from .cashflow import CollectorDailyCashViewSet as CollectorDailyCloseViewSet
