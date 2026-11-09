"""Aislamiento entre negocios (RLS) y reversas en los resúmenes de caja.

Cubre las tablas nuevas del flujo de caja y de solicitudes de acceso:
- a nivel de base de datos (SQL directo, sin pasar por el ORM/managers),
- a nivel de API, con un dueño de otro negocio.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import DatabaseError, connection, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import User
from core.context import clear_tenant, set_tenant
from customers.models import Customer
from employees.models import Employee
from loans.models import CollectorDailyCash, CollectorExpense
from loans.services import create_loan
from tenants.models import Membership, TenantJoinRequest, Tool
from tenants.services import enable_tool

RLS_TABLES = [
    "loans_collectordailycash",
    "loans_collectorexpense",
    "tenants_tenantjoinrequest",
]


def _set_db_context(user, tenant):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", [str(user.pk)])
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)",
            [str(tenant.pk) if tenant is not None else ""],
        )


def _rows(response):
    data = response.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


@pytest.fixture
def tenant_a_data(two_tenants, rls_context, seeded_tools):
    """Filas del negocio A en las tres tablas protegidas."""
    tenant, owner = two_tenants["tenant_a"], two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    collector_user = User.objects.create(email="rls-collector-a@example.test")
    Membership.objects.create(user=collector_user, tenant=tenant, role=Membership.Role.EMPLOYEE)
    collector = Employee.unscoped.create(tenant=tenant, user=collector_user, full_name="Cobrador A")
    cash = CollectorDailyCash.unscoped.create(
        tenant=tenant, collector=collector, date=date(2026, 11, 6), opening_amount="100.00"
    )
    expense = CollectorExpense.unscoped.create(
        tenant=tenant,
        collector=collector,
        spent_on=date(2026, 11, 6),
        description="Transporte A",
        amount="10.00",
    )
    applicant = User.objects.create(email="rls-applicant-a@example.test")
    join_request = TenantJoinRequest.objects.create(tenant=tenant, user=applicant)
    return {
        "tenant": tenant,
        "owner": owner,
        "collector": collector,
        "cash": cash,
        "expense": expense,
        "join_request": join_request,
        "applicant": applicant,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("table", RLS_TABLES)
def test_database_hides_and_protects_rows_from_other_tenants(
    table, two_tenants, tenant_a_data
):
    tenant_a, owner_a = tenant_a_data["tenant"], tenant_a_data["owner"]
    tenant_b, owner_b = two_tenants["tenant_b"], two_tenants["user_b"]

    def count():
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {table}")
            return cursor.fetchone()[0]

    def affected(sql):
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.rowcount

    _set_db_context(owner_a, tenant_a)
    assert count() == 1

    _set_db_context(owner_b, tenant_b)
    assert count() == 0
    assert affected(f"UPDATE {table} SET tenant_id = tenant_id") == 0
    assert affected(f"DELETE FROM {table}") == 0

    _set_db_context(owner_b, None)  # sin negocio activo no se ve nada
    assert count() == 0

    _set_db_context(owner_a, tenant_a)
    assert count() == 1  # nadie borró ni modificó la fila de A


@pytest.mark.django_db
def test_database_rejects_inserting_rows_for_another_tenant(
    two_tenants, tenant_a_data, rls_context
):
    tenant_a = tenant_a_data["tenant"]
    tenant_b, owner_b = two_tenants["tenant_b"], two_tenants["user_b"]
    collector = tenant_a_data["collector"]
    rls_context(owner_b, tenant_b)

    attempts = {
        "loans_collectorexpense": lambda: CollectorExpense.unscoped.bulk_create([
            CollectorExpense(
                tenant=tenant_a, collector=collector, description="Intruso", amount="1.00"
            )
        ]),
        "loans_collectordailycash": lambda: CollectorDailyCash.unscoped.bulk_create([
            CollectorDailyCash(
                tenant=tenant_a, collector=collector, date=date(2026, 11, 7), opening_amount="1.00"
            )
        ]),
        "tenants_tenantjoinrequest": lambda: TenantJoinRequest.objects.create(
            tenant=tenant_a, user=owner_b
        ),
    }
    for table, attempt in attempts.items():
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                attempt()


@pytest.mark.django_db
def test_other_tenant_owner_cannot_read_or_touch_cashflow_rows_through_the_api(
    two_tenants, client_for, rls_context, tenant_a_data
):
    tenant_b, owner_b = two_tenants["tenant_b"], two_tenants["user_b"]
    rls_context(owner_b, tenant_b)
    enable_tool(tenant_b, Tool.objects.get(code="loans"))
    client = client_for(owner_b, tenant_b)

    assert _rows(client.get(reverse("collector-daily-cash-list"))) == []
    assert _rows(client.get(reverse("collector-expense-list"))) == []
    for name, row in (
        ("collector-daily-cash-detail", tenant_a_data["cash"]),
        ("collector-expense-detail", tenant_a_data["expense"]),
    ):
        url = reverse(name, args=[row.pk])
        assert client.get(url).status_code == status.HTTP_404_NOT_FOUND
        assert client.patch(url, {"notes": "x"}, format="json").status_code in {
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        }
        assert client.delete(url).status_code in {
            status.HTTP_404_NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        }

    foreign_collector = str(tenant_a_data["collector"].pk)
    expense = client.post(
        reverse("collector-expense-list"),
        {"collector": foreign_collector, "category": "other", "description": "x", "amount": "5.00"},
        format="json",
    )
    cash = client.post(
        reverse("collector-daily-cash-list"),
        {"collector": foreign_collector, "date": "2026-11-07", "opening_amount": "5.00"},
        format="json",
    )
    assert expense.status_code == status.HTTP_400_BAD_REQUEST
    assert cash.status_code == status.HTTP_400_BAD_REQUEST

    summary = client.get(reverse("collector-cash-summary"), {"date": "2026-11-06"})
    assert summary.status_code == status.HTTP_200_OK
    assert summary.data["rows"] == []


@pytest.mark.django_db
def test_other_tenant_owner_cannot_see_or_decide_join_requests(
    two_tenants, client_for, rls_context, tenant_a_data
):
    tenant_b, owner_b = two_tenants["tenant_b"], two_tenants["user_b"]
    rls_context(owner_b, tenant_b)
    client = client_for(owner_b, tenant_b)
    manage_url = reverse("tenant-join-request-manage")

    assert client.get(manage_url).data == []
    decision = client.post(
        manage_url,
        {"request_id": str(tenant_a_data["join_request"].pk), "decision": "accept"},
        format="json",
    )
    assert decision.status_code == status.HTTP_404_NOT_FOUND

    # La solicitud de A sigue pendiente y el solicitante no entró a B.
    rls_context(tenant_a_data["owner"], tenant_a_data["tenant"])
    tenant_a_data["join_request"].refresh_from_db()
    assert tenant_a_data["join_request"].status == TenantJoinRequest.Status.PENDING
    rls_context(owner_b, tenant_b)
    assert not Membership.objects.filter(user=tenant_a_data["applicant"], tenant=tenant_b).exists()


@pytest.mark.django_db
def test_payment_reversal_nets_out_of_cash_and_customer_summaries(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant, owner = two_tenants["tenant_a"], two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    collector_user = User.objects.create(email="reversal-collector@example.test")
    Membership.objects.create(user=collector_user, tenant=tenant, role=Membership.Role.EMPLOYEE)
    collector = Employee.unscoped.create(tenant=tenant, user=collector_user, full_name="Cobrador R")
    customer = Customer.unscoped.create(tenant=tenant, full_name="Cliente R")
    set_tenant(tenant)
    try:
        loan = create_loan(
            tenant=tenant,
            customer=customer,
            collector=collector,
            principal="500.00",
            interest_rate="20.00",
            is_open_ended=True,
            frequency="daily",
            start_date=timezone.localdate(),
        )
    finally:
        clear_tenant()

    today = timezone.localdate().isoformat()
    employee_client = client_for(collector_user, tenant)
    owner_client = client_for(owner, tenant)

    paid = employee_client.post(
        reverse("loan-payment-list"),
        {"loan": str(loan.pk), "amount": "100.00", "method": "cash"},
        format="json",
    )
    assert paid.status_code == status.HTTP_201_CREATED

    def cash_collected():
        response = employee_client.get(
            reverse("collector-cash-summary"), {"period": "day", "date": today}
        )
        return Decimal(response.data["rows"][0]["collected"])

    def customer_row():
        response = owner_client.get(reverse("customer-loan-summary"))
        return response.data["rows"][0]

    assert cash_collected() == Decimal("100.00")
    assert Decimal(customer_row()["collected"]) == Decimal("100.00")

    reversal = owner_client.post(
        reverse("loan-payment-reverse", args=[paid.data["id"]]), {}, format="json"
    )
    assert reversal.status_code == status.HTTP_201_CREATED

    assert cash_collected() == Decimal("0.00")
    row = customer_row()
    assert Decimal(row["collected"]) == Decimal("0.00")
    assert Decimal(row["balance"]) == Decimal(row["total_payable"])
    amounts = sorted(Decimal(item["amount"]) for item in row["loans"][0]["payments"])
    assert amounts == [Decimal("-100.00"), Decimal("100.00")]
