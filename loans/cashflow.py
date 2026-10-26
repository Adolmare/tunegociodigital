from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Sum, When
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from employees.models import Employee
from tenants.api import HasRole, HasTool, TenantContextMixin, TenantViewSet
from rest_framework.permissions import IsAuthenticated

from .models import CollectorDailyCash, CollectorExpense, Loan, LoanPayment


ZERO = Decimal("0.00")


class CollectorDailyCashSerializer(serializers.ModelSerializer):
    collector_name = serializers.CharField(source="collector.full_name", read_only=True)
    collector = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.none())

    class Meta:
        model = CollectorDailyCash
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collector"].queryset = Employee.objects.filter(
            is_active=True, deleted_at__isnull=True
        )

    def validate(self, attrs):
        request = self.context.get("request")
        collector = attrs.get("collector", getattr(self.instance, "collector", None))
        if request is not None and collector is not None:
            if collector.tenant_id != request.tenant.pk:
                raise serializers.ValidationError({"collector": "El cobrador no pertenece al negocio activo."})
            if request.membership.role == "employee" and collector.user_id != request.user.pk:
                raise serializers.ValidationError({"collector": "Solo puedes registrar tu propia caja."})
        return attrs


class CollectorExpenseSerializer(serializers.ModelSerializer):
    collector_name = serializers.CharField(source="collector.full_name", read_only=True)
    collector = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.none())

    class Meta:
        model = CollectorExpense
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collector"].queryset = Employee.objects.filter(
            is_active=True, deleted_at__isnull=True
        )

    def validate(self, attrs):
        request = self.context.get("request")
        collector = attrs.get("collector", getattr(self.instance, "collector", None))
        if request is not None and collector is not None:
            if collector.tenant_id != request.tenant.pk:
                raise serializers.ValidationError({"collector": "El cobrador no pertenece al negocio activo."})
            if request.membership.role == "employee" and collector.user_id != request.user.pk:
                raise serializers.ValidationError({"collector": "Solo puedes registrar tus propios gastos."})
        return attrs


class CollectorDailyCashViewSet(TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    serializer_class = CollectorDailyCashSerializer

    def get_queryset(self):
        queryset = CollectorDailyCash.objects.select_related("collector")
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        collector_id = self.request.query_params.get("collector")
        selected_date = self.request.query_params.get("date")
        if collector_id:
            queryset = queryset.filter(collector_id=collector_id)
        if selected_date:
            queryset = queryset.filter(date=selected_date)
        return queryset

    def perform_create(self, serializer):
        if self.request.membership.role == "employee":
            collector = Employee.objects.filter(
                user=self.request.user, is_active=True, deleted_at__isnull=True
            ).first()
            if collector is None:
                raise ValidationError({"collector": "No tienes un perfil de cobrador activo."})
            serializer.save(collector=collector, tenant=self.request.tenant)
        else:
            serializer.save(tenant=self.request.tenant)


class CollectorExpenseViewSet(TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    serializer_class = CollectorExpenseSerializer

    def get_queryset(self):
        queryset = CollectorExpense.objects.select_related("collector")
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        collector_id = self.request.query_params.get("collector")
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        if collector_id:
            queryset = queryset.filter(collector_id=collector_id)
        if start:
            queryset = queryset.filter(spent_on__gte=start)
        if end:
            queryset = queryset.filter(spent_on__lte=end)
        return queryset

    def perform_create(self, serializer):
        if self.request.membership.role == "employee":
            collector = Employee.objects.filter(
                user=self.request.user, is_active=True, deleted_at__isnull=True
            ).first()
            if collector is None:
                raise ValidationError({"collector": "No tienes un perfil de cobrador activo."})
            serializer.save(collector=collector, tenant=self.request.tenant)
        else:
            serializer.save(tenant=self.request.tenant)


class CollectorCashSummaryView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasTool, HasRole]
    required_tool = "loans"
    min_role = "employee"

    def get(self, request):
        period = request.query_params.get("period", "day")
        if period not in {"day", "week", "month"}:
            raise ValidationError({"period": "Usa day, week o month."})
        try:
            selected = date.fromisoformat(request.query_params.get("date", timezone.localdate().isoformat()))
        except ValueError:
            raise ValidationError({"date": "Usa el formato YYYY-MM-DD."})

        if period == "week":
            start = selected - timedelta(days=selected.weekday())
            end = start + timedelta(days=6)
        elif period == "month":
            start = selected.replace(day=1)
            if start.month == 12:
                end = date(start.year + 1, 1, 1) - timedelta(days=1)
            else:
                end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        else:
            start = end = selected

        employees = Employee.objects.filter(is_active=True, deleted_at__isnull=True)
        if request.membership.role == "employee":
            employees = employees.filter(user=request.user)
        employee_rows = list(employees.order_by("full_name"))
        ids = [employee.pk for employee in employee_rows]

        openings = {
            row["collector_id"]: row["total"] or ZERO
            for row in CollectorDailyCash.objects.filter(
                collector_id__in=ids, date__range=(start, end)
            ).values("collector_id").annotate(total=Sum("opening_amount"))
        }
        expenses = {
            row["collector_id"]: row["total"] or ZERO
            for row in CollectorExpense.objects.filter(
                collector_id__in=ids, spent_on__range=(start, end)
            ).values("collector_id").annotate(total=Sum("amount"))
        }
        loans = {
            row["collector_id"]: row
            for row in Loan.objects.filter(
                collector_id__in=ids, start_date__range=(start, end)
            ).values("collector_id").annotate(
                principal=Sum("principal"),
                paperwork=Sum("paperwork_fee"),
            )
        }
        payments = {
            row["collector_id"]: row["total"] or ZERO
            for row in LoanPayment.objects.filter(
                collector_id__in=ids, paid_at__date__range=(start, end)
            ).annotate(
                signed_amount=Case(
                    When(direction="reversal", then=-F("amount")),
                    default=F("amount"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ).values("collector_id").annotate(total=Sum("signed_amount"))
        }

        rows = []
        for employee in employee_rows:
            opening = openings.get(employee.pk, ZERO)
            collected = payments.get(employee.pk, ZERO)
            expense_total = expenses.get(employee.pk, ZERO)
            loan_data = loans.get(employee.pk, {})
            principal = loan_data.get("principal") or ZERO
            paperwork = loan_data.get("paperwork") or ZERO
            expected = opening + collected - expense_total - principal + paperwork
            rows.append({
                "collector_id": str(employee.pk),
                "collector_name": employee.full_name,
                "opening_cash": str(opening),
                "collected": str(collected),
                "expenses": str(expense_total),
                "principal_lent": str(principal),
                "paperwork": str(paperwork),
                "expected_cash": str(expected),
            })

        totals = {
            key: sum((Decimal(row[key]) for row in rows), ZERO)
            for key in ("opening_cash", "collected", "expenses", "principal_lent", "paperwork", "expected_cash")
        }
        return Response({
            "period": period,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "formula": "dinero_inicial + recogido - gastos - capital_prestado + papeleria",
            "rows": rows,
            "totals": {key: str(value) for key, value in totals.items()},
        }, status=status.HTTP_200_OK)
