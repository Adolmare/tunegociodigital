import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.events import emit
from customers.models import Customer

from .models import Loan, LoanInstallment, LoanPayment, PaymentAllocation

CENT = Decimal("0.01")
COLLECTION_AMOUNTS_PER_100K = {
    "daily": Decimal("4000.00"),
    "weekly": Decimal("20000.00"),
    "biweekly": Decimal("40000.00"),
}


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _collection_amount(principal, frequency):
    rate = COLLECTION_AMOUNTS_PER_100K.get(frequency)
    if rate is None:
        raise ValidationError(
            {"frequency": "Las cuotas automáticas están disponibles para diario, semanal o quincenal."}
        )
    return _money(Decimal(principal) * rate / Decimal("100000"))


def _due_date(start_date, frequency, installment_number):
    if frequency == "daily":
        return start_date + timedelta(days=installment_number)
    if frequency == "weekly":
        return start_date + timedelta(days=7 * installment_number)
    if frequency == "biweekly":
        return start_date + timedelta(days=14 * installment_number)

    month_index = start_date.month - 1 + installment_number
    year = start_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def ledger_period_dates(period, selected_date):
    if period == "year":
        return date(selected_date.year, 1, 1), date(selected_date.year, 12, 31)
    if period == "month":
        first_day = date(selected_date.year, selected_date.month, 1)
        last_day = date(
            selected_date.year,
            selected_date.month,
            calendar.monthrange(selected_date.year, selected_date.month)[1],
        )
        return first_day, last_day
    if period == "week":
        first_day = selected_date - timedelta(days=selected_date.weekday())
        return first_day, first_day + timedelta(days=6)
    if period == "fortnight":
        if selected_date.day <= 15:
            return date(selected_date.year, selected_date.month, 1), date(
                selected_date.year, selected_date.month, 15
            )
        return date(selected_date.year, selected_date.month, 16), date(
            selected_date.year,
            selected_date.month,
            calendar.monthrange(selected_date.year, selected_date.month)[1],
        )
    return selected_date, selected_date


@transaction.atomic
def create_loan(
    *,
    tenant,
    customer=None,
    customer_details=None,
    principal,
    interest_rate,
    installments=None,
    frequency,
    start_date,
    collector=None,
    is_open_ended=False,
    paperwork_fee=0,
    opening_paid=0,
    import_reference="",
):
    if customer is None and customer_details is None:
        raise ValidationError({"customer": "Selecciona o registra un cliente."})
    if customer is not None and customer_details is not None:
        raise ValidationError({"customer": "Envía un cliente existente o uno nuevo, no ambos."})
    if customer_details is not None:
        customer = Customer.objects.create(tenant=tenant, **customer_details)

    principal = _money(principal)
    interest_rate = Decimal(interest_rate)
    paperwork_fee = _money(paperwork_fee)
    if principal <= 0:
        raise ValidationError({"principal": "El capital debe ser mayor que cero."})
    if interest_rate < 0:
        raise ValidationError({"interest_rate": "La tasa no puede ser negativa."})
    if not is_open_ended and (installments is None or installments < 1):
        raise ValidationError({"installments": "Debe existir al menos una cuota."})
    if customer.tenant_id != tenant.pk:
        raise ValidationError({"customer": "El cliente debe pertenecer a la empresa activa."})
    if collector is not None and collector.tenant_id != tenant.pk:
        raise ValidationError({"collector": "El cobrador debe pertenecer a la empresa activa."})

    # The rate is a percentage of the full principal, not a periodic rate.
    interest = _money(principal * interest_rate / Decimal("100"))
    total_payable = _money(principal + interest)
    opening_paid = _money(opening_paid)
    if opening_paid < 0 or opening_paid > total_payable:
        raise ValidationError(
            {"opening_paid": "El abono inicial debe estar entre cero y el total a pagar."}
        )
    if is_open_ended:
        collection_amount = _collection_amount(principal, frequency)
        collection_cents = int(collection_amount * 100)
        if collection_cents < 1:
            raise ValidationError(
                {"principal": "El capital es demasiado bajo para calcular una cuota positiva."}
            )
        total_cents = int(total_payable * 100)
        installments = (total_cents + collection_cents - 1) // collection_cents
    else:
        collection_amount = Decimal("0.00")
        total_cents = int(total_payable * 100)
        if installments > total_cents:
            raise ValidationError(
                {"installments": "El número de cuotas no puede exceder los centavos a cobrar."}
            )

    loan = Loan.objects.create(
        tenant=tenant,
        customer=customer,
        collector=collector,
        principal=principal,
        interest_rate=interest_rate,
        installments=installments,
        is_open_ended=is_open_ended,
        frequency=frequency,
        start_date=start_date,
        collection_amount=collection_amount,
        paperwork_fee=paperwork_fee,
        total_payable=total_payable,
        opening_paid=opening_paid,
        balance=_money(total_payable - opening_paid),
        status="paid" if opening_paid == total_payable else "active",
        import_reference=import_reference,
    )

    if is_open_ended:
        remaining_paid = opening_paid
        for index in range(1, installments + 1):
            amount_due = min(collection_amount, total_payable - collection_amount * (index - 1))
            amount_paid = min(remaining_paid, amount_due)
            LoanInstallment.objects.create(
                tenant=tenant,
                loan=loan,
                number=index,
                due_date=_due_date(start_date, frequency, index),
                amount_due=amount_due,
                amount_paid=amount_paid,
                status=(
                    "paid"
                    if amount_paid == amount_due
                    else "partial"
                    if amount_paid > 0
                    else "pending"
                ),
            )
            remaining_paid = _money(remaining_paid - amount_paid)
    else:
        base_cents, remainder = divmod(total_cents, installments)
        for index in range(1, installments + 1):
            amount_cents = base_cents + (1 if index <= remainder else 0)
            LoanInstallment.objects.create(
                tenant=tenant,
                loan=loan,
                number=index,
                due_date=_due_date(start_date, frequency, index),
                amount_due=Decimal(amount_cents) / 100,
            )
    return loan


def overdue_installments(*, tenant, as_of=None, collector=None):
    as_of = as_of or timezone.localdate()
    queryset = LoanInstallment.objects.select_related(
        "loan",
        "loan__customer",
        "loan__collector",
    ).filter(
        tenant=tenant,
        due_date__lte=as_of,
        amount_paid__lt=F("amount_due"),
        loan__status__in=["active", "delinquent"],
    )
    if collector is not None:
        queryset = queryset.filter(loan__collector=collector)
    return queryset.order_by("due_date", "loan__customer__full_name", "number")


def _refresh_loan_totals(loan):
    totals = LoanInstallment.objects.filter(loan=loan).aggregate(
        amount_due=Sum("amount_due"),
        amount_paid=Sum("amount_paid"),
    )
    loan.balance = _money(
        (totals["amount_due"] or Decimal("0"))
        - (totals["amount_paid"] or Decimal("0"))
    )
    if loan.balance == 0:
        loan.status = "paid"
    elif LoanInstallment.objects.filter(
        loan=loan,
        due_date__lt=timezone.localdate(),
        amount_paid__lt=F("amount_due"),
    ).exists():
        loan.status = "delinquent"
    else:
        loan.status = "active"
    loan.save(update_fields=["balance", "status", "updated_at"])


@transaction.atomic
def register_payment(*, loan, collector, amount, method="cash", user=None):
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError({"amount": "El abono debe ser mayor que cero."})

    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if loan.status == "cancelled":
        raise ValidationError({"loan": "No se pueden registrar abonos a un préstamo cancelado."})
    if collector.tenant_id != loan.tenant_id:
        raise ValidationError({"collector": "El cobrador debe pertenecer a la empresa activa."})
    if amount > loan.balance:
        raise ValidationError({"amount": "El abono no puede superar el saldo pendiente."})

    installments = list(
        LoanInstallment.objects.select_for_update()
        .filter(loan=loan)
        .order_by("due_date", "number")
    )
    remaining = amount
    allocations = []
    for installment in installments:
        due = installment.amount_due - installment.amount_paid
        if due <= 0:
            continue
        applied = min(remaining, due)
        installment.amount_paid = _money(installment.amount_paid + applied)
        installment.status = (
            "paid" if installment.amount_paid == installment.amount_due else "partial"
        )
        update_fields = ["amount_paid", "status", "updated_at"]
        if loan.is_open_ended and installment.amount_paid < installment.amount_due:
            installment.due_date = _due_date(
                timezone.localdate(),
                loan.frequency,
                1,
            )
            update_fields.append("due_date")
        installment.save(update_fields=update_fields)
        allocations.append((installment, applied))
        remaining = _money(remaining - applied)
        if remaining == 0:
            break
    if remaining != 0:
        raise ValidationError({"amount": "El abono excede las cuotas pendientes."})

    payment = LoanPayment.objects.create(
        tenant_id=loan.tenant_id,
        loan=loan,
        collector=collector,
        amount=amount,
        method=method,
        created_by=user,
    )
    for installment, applied in allocations:
        PaymentAllocation.objects.create(
            tenant_id=loan.tenant_id,
            payment=payment,
            installment=installment,
            amount=applied,
        )

    _refresh_loan_totals(loan)
    emit(
        "loan.payment_received",
        tenant_id=str(loan.tenant_id),
        user_id=str(user.pk) if user is not None else None,
        loan_id=str(loan.pk),
        payment_id=str(payment.pk),
        amount=str(amount),
        balance=str(loan.balance),
    )
    return payment


@transaction.atomic
def reverse_payment(*, payment, user):
    loan = Loan.objects.select_for_update().get(pk=payment.loan_id)
    payment = LoanPayment.objects.select_for_update().get(pk=payment.pk, loan=loan)
    if payment.direction != "payment":
        raise ValidationError({"payment": "Solo se pueden reversar abonos originales."})
    if payment.reversals.exists():
        raise ValidationError({"payment": "Este abono ya fue reversado."})

    allocations = list(
        PaymentAllocation.objects.select_for_update()
        .filter(payment=payment)
    )
    reversal = LoanPayment.objects.create(
        tenant_id=loan.tenant_id,
        loan=loan,
        collector=payment.collector,
        amount=payment.amount,
        method=payment.method,
        direction="reversal",
        reversal_of=payment,
        created_by=user,
    )
    for allocation in allocations:
        installment = LoanInstallment.objects.select_for_update().get(
            pk=allocation.installment_id
        )
        installment.amount_paid = _money(installment.amount_paid - allocation.amount)
        installment.status = (
            "paid"
            if installment.amount_paid == installment.amount_due
            else "partial"
            if installment.amount_paid > 0
            else "pending"
        )
        update_fields = ["amount_paid", "status", "updated_at"]
        if loan.is_open_ended:
            installment.due_date = timezone.localdate()
            update_fields.append("due_date")
        installment.save(update_fields=update_fields)
        PaymentAllocation.objects.create(
            tenant_id=loan.tenant_id,
            payment=reversal,
            installment=installment,
            amount=allocation.amount,
        )

    _refresh_loan_totals(loan)
    emit(
        "loan.payment_reversed",
        tenant_id=str(loan.tenant_id),
        user_id=str(user.pk),
        loan_id=str(loan.pk),
        payment_id=str(payment.pk),
        reversal_id=str(reversal.pk),
        amount=str(reversal.amount),
        balance=str(loan.balance),
    )
    return reversal
