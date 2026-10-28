from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Case, DecimalField, F, Sum, When
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from employees.models import Employee
from tenants.api import ActionMinRoleMixin, HasRole, HasTool, TenantContextMixin, TenantViewSet

from .models import CollectorDailyCash, CollectorExpense, Loan, LoanPayment


ZERO = Decimal("0.00")


class CollectorDailyCashSerializer(serializers.ModelSerializer):
    collector_name = serializers.CharField(source="collector.full_name", read_only=True)
    collector = serializers.PrimaryKeyRelatedField(queryset=Employee.unscoped.none(), required=False)
    opening_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))

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
        if request is not None:
            if collector is None and request.membership.role != "employee":
                raise serializers.ValidationError({"collector": "Selecciona el cobrador."})
            if collector is not None and collector.tenant_id != request.tenant.pk:
                raise serializers.ValidationError({"collector": "El cobrador no pertenece al negocio activo."})
            if request.membership.role == "employee" and collector is not None and collector.user_id != request.user.pk:
                raise serializers.ValidationError({"collector": "Solo puedes registrar tu propia caja."})
            selected_date = attrs.get("date", getattr(self.instance, "date", None))
            if collector is not None and selected_date is not None:
                duplicate_opening = CollectorDailyCash.objects.filter(
                    collector=collector, date=selected_date
                )
                if self.instance is not None:
                    duplicate_opening = duplicate_opening.exclude(pk=self.instance.pk)
                if duplicate_opening.exists():
                    raise serializers.ValidationError({"date": "Ya existe un dinero inicial registrado para este cobrador en esa fecha."})
        return attrs


class CollectorExpenseSerializer(serializers.ModelSerializer):
    collector_name = serializers.CharField(source="collector.full_name", read_only=True)
    collector = serializers.PrimaryKeyRelatedField(queryset=Employee.unscoped.none(), required=False)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))

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
        if request is not None:
            if collector is None and request.membership.role != "employee":
                raise serializers.ValidationError({"collector": "Selecciona el cobrador."})
            if collector is not None and collector.tenant_id != request.tenant.pk:
                raise serializers.ValidationError({"collector": "El cobrador no pertenece al negocio activo."})
            if request.membership.role == "employee" and collector is not None and collector.user_id != request.user.pk:
                raise serializers.ValidationError({"collector": "Solo puedes registrar tus propios gastos."})
        return attrs


class CollectorDailyCashViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "update": "manager",
        "partial_update": "manager",
    }
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
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
            save_kwargs = {"collector": collector, "tenant": self.request.tenant}
        else:
            save_kwargs = {"tenant": self.request.tenant}
        try:
            with transaction.atomic():
                serializer.save(**save_kwargs)
        except IntegrityError:
            raise ValidationError({"date": "Ya existe un dinero inicial para ese cobrador y fecha."})

    def perform_update(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise ValidationError({"date": "Ya existe un dinero inicial para ese cobrador y fecha."})


class CollectorExpenseViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "update": "manager",
        "partial_update": "manager",
    }
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
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

    def perform_update(self, serializer):
        with transaction.atomic():
            serializer.save()


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


class CustomerLoanSummaryView(TenantContextMixin, APIView):
    """Una fila por cliente; pagos se agregan aparte para evitar duplicación por joins."""

    permission_classes = [IsAuthenticated, HasTool, HasRole]
    required_tool = "loans"
    min_role = "employee"

    def get(self, request):
        loans = Loan.objects.select_related("customer").prefetch_related("schedule").order_by("customer__full_name", "created_at")
        if request.membership.role == "employee":
            loans = loans.filter(collector__user=request.user)

        search = request.query_params.get("search", "").strip()
        if search:
            loans = loans.filter(customer__full_name__icontains=search)

        start = request.query_params.get("start")
        end = request.query_params.get("end")
        if start:
            try:
                date.fromisoformat(start)
            except ValueError:
                raise ValidationError({"start": "Usa el formato YYYY-MM-DD."})
            loans = loans.filter(start_date__gte=start)
        if end:
            try:
                date.fromisoformat(end)
            except ValueError:
                raise ValidationError({"end": "Usa el formato YYYY-MM-DD."})
            loans = loans.filter(start_date__lte=end)

        loan_rows = list(loans)
        loan_ids = [loan.pk for loan in loan_rows]
        payments = {
            row["loan_id"]: row["total"] or ZERO
            for row in LoanPayment.objects.filter(loan_id__in=loan_ids).annotate(
                signed_amount=Case(
                    When(direction="reversal", then=-F("amount")),
                    default=F("amount"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ).values("loan_id").annotate(total=Sum("signed_amount"))
        }
        payment_details = {}
        for payment in LoanPayment.objects.filter(loan_id__in=loan_ids).select_related("collector").order_by("paid_at"):
            payment_details.setdefault(payment.loan_id, []).append({
                "id": str(payment.pk),
                "paid_at": payment.paid_at.isoformat(),
                "date": timezone.localtime(payment.paid_at).date().isoformat(),
                "amount": str(-payment.amount if payment.direction == "reversal" else payment.amount),
                "direction": payment.direction,
                "method": payment.method,
                "collector_name": payment.collector.full_name,
            })

        grouped = {}
        for loan in loan_rows:
            key = loan.customer_id
            if key not in grouped:
                grouped[key] = {
                    "customer_id": str(loan.customer_id),
                    "customer_name": loan.customer.full_name,
                    "loan_count": 0,
                    "principal": ZERO,
                    "paperwork": ZERO,
                    "interest": ZERO,
                    "total_payable": ZERO,
                    "collected": ZERO,
                    "balance": ZERO,
                    "loans": [],
                }
            row = grouped[key]
            interest = loan.total_payable - loan.principal
            collected = loan.opening_paid + payments.get(loan.pk, ZERO)
            row["loan_count"] += 1
            row["principal"] += loan.principal
            row["paperwork"] += loan.paperwork_fee
            row["interest"] += interest
            row["total_payable"] += loan.total_payable
            row["collected"] += collected
            row["balance"] += loan.balance
            row["loans"].append({
                "id": str(loan.pk),
                "date": loan.start_date.isoformat(),
                "principal": str(loan.principal),
                "paperwork": str(loan.paperwork_fee),
                "interest": str(interest),
                "total_payable": str(loan.total_payable),
                "collected": str(collected),
                "balance": str(loan.balance),
                "frequency": loan.frequency,
                "status": loan.status,
                "installments": [
                    {
                        "number": installment.number,
                        "due_date": installment.due_date.isoformat(),
                        "amount_due": str(installment.amount_due),
                        "amount_paid": str(installment.amount_paid),
                        "pending_amount": str(installment.amount_due - installment.amount_paid),
                        "status": installment.status,
                    }
                    for installment in loan.schedule.all()
                ],
                "payments": payment_details.get(loan.pk, []),
            })

        rows = []
        for row in sorted(grouped.values(), key=lambda item: item["customer_name"].casefold()):
            rows.append({
                **row,
                **{
                    key: str(row[key])
                    for key in ("principal", "paperwork", "interest", "total_payable", "collected", "balance")
                },
            })
        total_keys = ("loan_count", "principal", "paperwork", "interest", "total_payable", "collected", "balance")
        totals = {
            key: sum((Decimal(str(row[key])) for row in rows), ZERO) if key != "loan_count"
            else sum(row[key] for row in rows)
            for key in total_keys
        }
        return Response({
            "search": search,
            "start_date": start or None,
            "end_date": end or None,
            "customer_count": len(rows),
            "rows": rows,
            "totals": {key: str(value) for key, value in totals.items()},
        }, status=status.HTTP_200_OK)
