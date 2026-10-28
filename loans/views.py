import asyncio
from datetime import datetime
import json
import time
import uuid
from decimal import Decimal

from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Case, DecimalField, F, Q, Sum, When
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

from .models import (
    CollectionRoute,
    CollectorDailyClose,
    CollectorExpense,
    Loan,
    LoanInstallment,
    LoanPayment,
    RouteStop,
)
from .serializers import (
    CollectionRouteSerializer,
    CollectorDailyCloseSerializer,
    CollectorExpenseSerializer,
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


def _read_payment_events(user_id, tenant_id, cursor):
    with transaction.atomic():
        set_database_context(user_id, tenant_id)
        return list(
            EventInbox.unscoped.filter(
                tenant_id=tenant_id,
                event_name="loan.payment_received",
                occurred_at__gte=cursor,
            )
            .order_by("occurred_at", "id")
            .values("id", "occurred_at", "payload")[:100]
        )


class LoanViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "collection_today": "employee",
        "collector_summary": "employee",
        "ledger": "owner",
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

    @action(detail=False, methods=["get"], url_path="collector-summary")
    def collector_summary(self, request):
        period = request.query_params.get("period", "day")
        selected_date = request.query_params.get("date") or timezone.localdate().isoformat()
        filters = LoanLedgerQuerySerializer(data={
            "period": period,
            "date": selected_date,
        })
        filters.is_valid(raise_exception=True)
        period_start, period_end = ledger_period_dates(
            filters.validated_data["period"],
            filters.validated_data["date"],
        )
        employees = Employee.objects.filter(is_active=True, deleted_at__isnull=True)
        if request.membership.role == "employee":
            employees = employees.filter(user=request.user)
        results = []
        for employee in employees:
            payments = LoanPayment.objects.filter(
                collector=employee,
                paid_at__date__gte=period_start,
                paid_at__date__lte=period_end,
            ).aggregate(total=Sum(
                Case(
                    When(direction="reversal", then=-F("amount")),
                    default=F("amount"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ))["total"] or Decimal("0.00")
            expenses = CollectorExpense.objects.filter(
                collector=employee,
                date__gte=period_start,
                date__lte=period_end,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            loans_issued = Loan.objects.filter(
                collector=employee,
                start_date__gte=period_start,
                start_date__lte=period_end,
            ).aggregate(total=Sum("principal"))["total"] or Decimal("0.00")
            close_totals = CollectorDailyClose.objects.filter(
                collector=employee,
                date__gte=period_start,
                date__lte=period_end,
            ).aggregate(
                opening_cash=Sum("opening_cash"),
                paperwork=Sum("paperwork_amount"),
            )
            opening_cash = close_totals["opening_cash"] or Decimal("0.00")
            paperwork = close_totals["paperwork"] or Decimal("0.00")
            results.append({
                "collector_id": str(employee.pk),
                "collector": employee.full_name,
                "opening_cash": str(opening_cash),
                "collected": str(payments),
                "expenses": str(expenses),
                "loans_issued": str(loans_issued),
                "paperwork": str(paperwork),
                "cash_balance": str(opening_cash + payments - expenses - loans_issued + paperwork),
            })
        totals = {
            key: sum((Decimal(row[key]) for row in results), Decimal("0.00"))
            for key in ("opening_cash", "collected", "expenses", "loans_issued", "paperwork", "cash_balance")
        }
        return Response({
            "period": period,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "collectors": results,
            "totals": {key: str(value) for key, value in totals.items()},
        })

    @action(detail=False, methods=["get"])
    def ledger(self, request):
        filters = LoanLedgerQuerySerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        period = filters.validated_data["period"]
        selected_date = filters.validated_data["date"]
        frequency = filters.validated_data["frequency"]
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
        data = [
            {
                **row,
                **{
                    key: str(value)
                    for key, value in row.items()
                    if isinstance(value, Decimal)
                },
            }
            for row in rows
        ]
        return Response(
            {
                "period": period,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "frequency": frequency,
                "rows": data,
                "totals": {key: str(value) for key, value in totals.items()},
            }
        )


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

        async def stream():
            nonlocal cursor
            yield "event: ready\ndata: {}\n\n"
            last_heartbeat = time.monotonic()
            while True:
                events = await sync_to_async(
                    _read_payment_events,
                    thread_sensitive=True,
                )(user_id, tenant_id, cursor)

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


class CollectorDailyCloseViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "update": "employee",
        "partial_update": "employee",
    }
    serializer_class = CollectorDailyCloseSerializer

    def get_queryset(self):
        queryset = CollectorDailyClose.objects.select_related("collector")
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        return queryset

    def perform_create(self, serializer):
        collector = self._collector(serializer.validated_data.get("collector"))
        close, created = CollectorDailyClose.objects.get_or_create(
            tenant=self.request.tenant,
            collector=collector,
            date=serializer.validated_data["date"],
            defaults={
                "opening_cash": serializer.validated_data["opening_cash"],
                "paperwork_amount": serializer.validated_data["paperwork_amount"],
            },
        )
        if not created:
            close.opening_cash = serializer.validated_data["opening_cash"]
            close.paperwork_amount = serializer.validated_data["paperwork_amount"]
            close.save(update_fields=["opening_cash", "paperwork_amount", "updated_at"])
        serializer.instance = close

    def perform_update(self, serializer):
        instance = self.get_object()
        collector = self._collector(serializer.validated_data.get("collector", instance.collector))
        serializer.save(collector=collector)

    def _collector(self, requested):
        if self.request.membership.role == "employee":
            requested = Employee.objects.filter(
                user=self.request.user,
                is_active=True,
                deleted_at__isnull=True,
            ).first()
        if requested is None or requested.tenant_id != self.request.tenant.pk:
            raise ValidationError({"collector": "Selecciona un cobrador activo del negocio."})
        return requested


class CollectorExpenseViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "update": "employee",
        "partial_update": "employee",
        "destroy": "manager",
    }
    serializer_class = CollectorExpenseSerializer

    def get_queryset(self):
        queryset = CollectorExpense.objects.select_related("collector")
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        return queryset

    def perform_create(self, serializer):
        collector = self._collector(serializer.validated_data.get("collector"))
        serializer.save(tenant=self.request.tenant, collector=collector)

    def perform_update(self, serializer):
        instance = self.get_object()
        collector = self._collector(serializer.validated_data.get("collector", instance.collector))
        serializer.save(collector=collector)

    def _collector(self, requested):
        if self.request.membership.role == "employee":
            requested = Employee.objects.filter(
                user=self.request.user,
                is_active=True,
                deleted_at__isnull=True,
            ).first()
        if requested is None or requested.tenant_id != self.request.tenant.pk:
            raise ValidationError({"collector": "Selecciona un cobrador activo del negocio."})
        return requested
