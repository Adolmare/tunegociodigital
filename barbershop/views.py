from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Item
from tenants.api import ActionMinRoleMixin, HasRole, HasTool, TenantContextMixin, TenantViewSet
from reservations.models import Reservation

from .models import BarberProfile, ServiceSale
from .serializers import (
    OPEN_STATUSES,
    AppointmentCreateSerializer,
    BarberSerializer,
    CompleteAppointmentSerializer,
    ServiceSerializer,
    money,
    serialize_appointment,
)

TOOL = "barbershop"


class ServiceViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = TOOL
    serializer_class = ServiceSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "manager",
        "partial_update": "manager",
    }

    def get_queryset(self):
        return Item.objects.filter(kind="service").order_by("name")


class BarberViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = TOOL
    serializer_class = BarberSerializer
    lookup_field = "employee_id"
    http_method_names = ["get", "post", "patch", "head", "options"]
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "manager",
        "partial_update": "manager",
    }

    def get_queryset(self):
        return BarberProfile.objects.select_related("employee").filter(
            employee__deleted_at__isnull=True
        ).order_by("employee__full_name")


class AppointmentViewSet(
    TenantContextMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasTool, HasRole]
    required_tool = TOOL
    min_role = "employee"

    def get_queryset(self):
        queryset = (
            Reservation.objects.select_related("customer", "employee", "sale")
            .prefetch_related("items__item")
            .order_by("starts_at")
        )
        params = self.request.query_params
        selected = params.get("date")
        if selected:
            try:
                day = date.fromisoformat(selected)
            except ValueError:
                raise ValidationError({"date": "Usa el formato YYYY-MM-DD."})
            tz = timezone.get_current_timezone()
            start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
            queryset = queryset.filter(starts_at__gte=start, starts_at__lt=start + timedelta(days=1))
        if params.get("barber"):
            queryset = queryset.filter(employee_id=params["barber"])
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        return queryset

    def list(self, request, *args, **kwargs):
        return Response([serialize_appointment(row) for row in self.get_queryset()])

    def retrieve(self, request, *args, **kwargs):
        return Response(serialize_appointment(self.get_object()))

    def create(self, request, *args, **kwargs):
        serializer = AppointmentCreateSerializer(
            data=request.data, context={"tenant": request.tenant}
        )
        serializer.is_valid(raise_exception=True)
        reservation = serializer.save()
        reservation = self.get_queryset().get(pk=reservation.pk)
        return Response(serialize_appointment(reservation), status=status.HTTP_201_CREATED)

    def _set_closed_status(self, new_status):
        with transaction.atomic():
            reservation = Reservation.objects.select_for_update().get(pk=self.get_object().pk)
            if reservation.status not in OPEN_STATUSES:
                raise ValidationError({"status": "Esta cita ya fue cerrada."})
            reservation.status = new_status
            reservation.save(update_fields=["status", "updated_at"])
        return Response(serialize_appointment(self.get_queryset().get(pk=reservation.pk)))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._set_closed_status("cancelled")

    @action(detail=True, methods=["post"], url_path="no-show")
    def no_show(self, request, pk=None):
        return self._set_closed_status("no_show")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        payload = CompleteAppointmentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            reservation = Reservation.objects.select_for_update().select_related("customer").get(
                pk=self.get_object().pk
            )
            if reservation.status not in OPEN_STATUSES:
                raise ValidationError({"status": "Esta cita ya fue cerrada."})
            if reservation.employee_id is None:
                raise ValidationError({"barber": "La cita no tiene barbero asignado."})
            profile = BarberProfile.objects.filter(employee_id=reservation.employee_id).first()
            percent = profile.commission_percent if profile else Decimal("0")
            subtotal = sum(
                (row.unit_price * row.quantity for row in reservation.items.all()), Decimal("0")
            )
            tip = money(payload.validated_data["tip"])
            ServiceSale.objects.create(
                tenant=request.tenant,
                reservation=reservation,
                barber_id=reservation.employee_id,
                customer_name=reservation.customer.full_name,
                subtotal=money(subtotal),
                tip=tip,
                total=money(subtotal) + tip,
                payment_method=payload.validated_data["payment_method"],
                commission_percent=percent,
                commission_amount=money(subtotal * percent / Decimal("100")),
            )
            reservation.status = "completed"
            reservation.save(update_fields=["status", "updated_at"])
        return Response(serialize_appointment(self.get_queryset().get(pk=reservation.pk)))


class DaySummaryView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasTool, HasRole]
    required_tool = TOOL
    min_role = "employee"

    def get(self, request):
        period = request.query_params.get("period", "day")
        if period not in {"day", "week", "month"}:
            raise ValidationError({"period": "Usa day, week o month."})
        try:
            selected = date.fromisoformat(
                request.query_params.get("date", timezone.localdate().isoformat())
            )
        except ValueError:
            raise ValidationError({"date": "Usa el formato YYYY-MM-DD."})
        if period == "week":
            start = selected - timedelta(days=selected.weekday())
            end = start + timedelta(days=6)
        elif period == "month":
            start = selected.replace(day=1)
            nxt = date(start.year + (start.month == 12), (start.month % 12) + 1, 1)
            end = nxt - timedelta(days=1)
        else:
            start = end = selected

        sales = ServiceSale.objects.filter(paid_at__date__range=(start, end))
        per_barber = {
            row["barber_id"]: row
            for row in sales.values("barber_id").annotate(
                services=Count("id"),
                subtotal=Sum("subtotal"),
                tips=Sum("tip"),
                commission=Sum("commission_amount"),
            )
        }
        zero = Decimal("0")
        rows = []
        for profile in BarberProfile.objects.select_related("employee").filter(
            employee__deleted_at__isnull=True
        ):
            data = per_barber.get(profile.employee_id, {})
            subtotal = data.get("subtotal") or zero
            commission = data.get("commission") or zero
            tips = data.get("tips") or zero
            if not data and not profile.employee.is_active:
                continue
            rows.append(
                {
                    "barber_id": str(profile.employee_id),
                    "barber_name": profile.employee.full_name,
                    "commission_percent": f"{profile.commission_percent:.2f}",
                    "services": data.get("services", 0),
                    "subtotal": f"{subtotal:.2f}",
                    "tips": f"{tips:.2f}",
                    "commission": f"{commission:.2f}",
                    "barber_pay": f"{commission + tips:.2f}",
                    "owner_net": f"{subtotal - commission:.2f}",
                }
            )
        methods = {
            row["payment_method"]: f"{row['total']:.2f}"
            for row in sales.values("payment_method").annotate(total=Sum("total"))
        }
        totals = sales.aggregate(
            services=Count("id"),
            subtotal=Sum("subtotal"),
            tips=Sum("tip"),
            commission=Sum("commission_amount"),
            total=Sum("total"),
        )
        subtotal = totals["subtotal"] or zero
        commission = totals["commission"] or zero
        tips = totals["tips"] or zero
        tz = timezone.get_current_timezone()
        window_start = datetime.combine(start, datetime.min.time(), tzinfo=tz)
        window_end = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        by_status = {
            row["status"]: row["n"]
            for row in Reservation.objects.filter(
                starts_at__gte=window_start, starts_at__lt=window_end
            ).values("status").annotate(n=Count("id"))
        }
        return Response(
            {
                "period": period,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "totals": {
                    "services": totals["services"] or 0,
                    "subtotal": f"{subtotal:.2f}",
                    "tips": f"{tips:.2f}",
                    "commission": f"{commission:.2f}",
                    "barber_pay": f"{commission + tips:.2f}",
                    "owner_net": f"{subtotal - commission:.2f}",
                    "collected": f"{(totals['total'] or zero):.2f}",
                },
                "by_method": methods,
                "appointments": {
                    "pending": by_status.get("pending", 0) + by_status.get("confirmed", 0)
                    + by_status.get("in_progress", 0),
                    "completed": by_status.get("completed", 0),
                    "cancelled": by_status.get("cancelled", 0),
                    "no_show": by_status.get("no_show", 0),
                },
                "rows": rows,
            }
        )
