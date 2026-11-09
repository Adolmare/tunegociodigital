from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Case, Count, DecimalField, F, Sum, When
from django.db.models.functions import Lower
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from customers.models import Customer
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
            if request.membership.role == "employee":
                raise serializers.ValidationError({"collector": "El registro de dinero inicial solo puede realizarlo el dueño."})
            if collector is None:
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
    description = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
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
        category = attrs.get("category", getattr(self.instance, "category", "other"))
        description = (attrs.get("description", getattr(self.instance, "description", "")) or "").strip()
        notes = (attrs.get("notes", getattr(self.instance, "notes", "")) or "").strip()
        if category == "other" and not description and not notes:
            raise serializers.ValidationError(
                {"description": "Cuando el tipo de gasto es 'Otro', la descripción u observaciones son obligatorias."}
            )
        attrs["description"] = description
        attrs["notes"] = notes
        return attrs


class CollectorDailyCashViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "manager",
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

    def create(self, request, *args, **kwargs):
        collector_id = request.data.get("collector")
        selected_date = request.data.get("date")
        if collector_id and selected_date and request.membership.role != "employee":
            existing = CollectorDailyCash.objects.filter(
                collector_id=collector_id,
                date=selected_date,
            ).first()
            if existing is not None:
                serializer = self.get_serializer(existing, data=request.data)
                serializer.is_valid(raise_exception=True)
                self.perform_update(serializer)
                return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

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
                collector_id__in=ids,
                created_at__date__range=(start, end),
                import_reference="",
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
    """Una fila por cliente con paginación en BD; pagos se agregan aparte para evitar duplicación por joins."""

    permission_classes = [IsAuthenticated, HasTool, HasRole]
    required_tool = "loans"
    min_role = "employee"
    default_page_size = 25
    max_page_size = 100

    def get(self, request):
        loans_qs = Loan.objects.all()
        if request.membership.role == "employee":
            loans_qs = loans_qs.filter(collector__user=request.user)

        search = request.query_params.get("search", "").strip()
        if search:
            loans_qs = loans_qs.filter(customer__full_name__icontains=search)

        start = request.query_params.get("start")
        end = request.query_params.get("end")
        if start:
            try:
                date.fromisoformat(start)
            except ValueError:
                raise ValidationError({"start": "Usa el formato YYYY-MM-DD."})
            loans_qs = loans_qs.filter(start_date__gte=start)
        if end:
            try:
                date.fromisoformat(end)
            except ValueError:
                raise ValidationError({"end": "Usa el formato YYYY-MM-DD."})
            loans_qs = loans_qs.filter(start_date__lte=end)

        raw_page = request.query_params.get("page", "1")
        raw_page_size = request.query_params.get("page_size", str(self.default_page_size))
        try:
            page = int(raw_page)
        except (TypeError, ValueError):
            raise ValidationError({"page": "Usa un número de página entero positivo."})
        if page < 1:
            raise ValidationError({"page": "La página debe ser mayor o igual a 1."})

        try:
            page_size = int(raw_page_size)
        except (TypeError, ValueError):
            raise ValidationError({"page_size": "Usa un tamaño de página entero positivo."})
        if page_size < 1 or page_size > self.max_page_size:
            raise ValidationError(
                {"page_size": f"El tamaño de página debe estar entre 1 y {self.max_page_size}."}
            )

        customers_qs = Customer.objects.filter(
            pk__in=loans_qs.values("customer_id")
        ).order_by(Lower("full_name"), "full_name", "id")
        customer_count = customers_qs.count()
        total_pages = max(1, (customer_count + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        page_customers = list(customers_qs[offset : offset + page_size])
        page_customer_ids = [customer.pk for customer in page_customers]

        loan_agg = loans_qs.aggregate(
            loan_count=Count("id"),
            principal=Sum("principal"),
            paperwork=Sum("paperwork_fee"),
            total_payable=Sum("total_payable"),
            opening_paid=Sum("opening_paid"),
            balance=Sum("balance"),
        )
        payment_agg = (
            LoanPayment.objects.filter(loan__in=loans_qs)
            .annotate(
                signed_amount=Case(
                    When(direction="reversal", then=-F("amount")),
                    default=F("amount"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
            .aggregate(total=Sum("signed_amount"))
        )
        total_principal = loan_agg["principal"] or ZERO
        total_paperwork = loan_agg["paperwork"] or ZERO
        total_payable = loan_agg["total_payable"] or ZERO
        total_interest = total_payable - total_principal
        total_collected = (loan_agg["opening_paid"] or ZERO) + (payment_agg["total"] or ZERO)
        total_balance = loan_agg["balance"] or ZERO
        totals = {
            "loan_count": loan_agg["loan_count"] or 0,
            "principal": total_principal,
            "paperwork": total_paperwork,
            "interest": total_interest,
            "total_payable": total_payable,
            "collected": total_collected,
            "balance": total_balance,
        }

        loan_rows = (
            list(
                loans_qs.filter(customer_id__in=page_customer_ids)
                .select_related("customer", "collector")
                .prefetch_related("schedule")
                .order_by("created_at", "id")
            )
            if page_customer_ids
            else []
        )
        loan_ids = [loan.pk for loan in loan_rows]
        payments = (
            {
                row["loan_id"]: row["total"] or ZERO
                for row in LoanPayment.objects.filter(loan_id__in=loan_ids)
                .annotate(
                    signed_amount=Case(
                        When(direction="reversal", then=-F("amount")),
                        default=F("amount"),
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    )
                )
                .values("loan_id")
                .annotate(total=Sum("signed_amount"))
            }
            if loan_ids
            else {}
        )
        payment_details = {}
        if loan_ids:
            all_payments = list(
                LoanPayment.objects.filter(loan_id__in=loan_ids)
                .select_related("collector")
                .order_by("paid_at", "id")
            )
            reversed_ids = {
                pmt.reversal_of_id
                for pmt in all_payments
                if pmt.direction == "reversal" and pmt.reversal_of_id is not None
            }
            for payment in all_payments:
                payment_details.setdefault(payment.loan_id, []).append({
                    "id": str(payment.pk),
                    "paid_at": payment.paid_at.isoformat(),
                    "date": timezone.localtime(payment.paid_at).date().isoformat(),
                    "amount": str(-payment.amount if payment.direction == "reversal" else payment.amount),
                    "direction": payment.direction,
                    "is_reversed": payment.pk in reversed_ids,
                    "method": payment.method,
                    "collector_name": payment.collector.full_name,
                })

        grouped = {
            customer.pk: {
                "customer_id": str(customer.pk),
                "customer_name": customer.full_name,
                "customer_phone": customer.phone,
                "customer_document": customer.document_id,
                "customer_neighborhood": customer.neighborhood,
                "loan_count": 0,
                "principal": ZERO,
                "paperwork": ZERO,
                "interest": ZERO,
                "total_payable": ZERO,
                "collected": ZERO,
                "balance": ZERO,
                "loans": [],
            }
            for customer in page_customers
        }
        for loan in loan_rows:
            row = grouped[loan.customer_id]
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
                "collector_id": str(loan.collector_id) if loan.collector_id else "",
                "collector_name": loan.collector.full_name if loan.collector else "Sin asignar",
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

        rows = [
            {
                **row,
                **{
                    key: str(row[key])
                    for key in ("principal", "paperwork", "interest", "total_payable", "collected", "balance")
                },
            }
            for row in (grouped[customer.pk] for customer in page_customers)
        ]
        return Response({
            "search": search,
            "start_date": start or None,
            "end_date": end or None,
            "customer_count": customer_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1 and customer_count > 0,
            "rows": rows,
            "totals": {key: str(value) for key, value in totals.items()},
        }, status=status.HTTP_200_OK)
