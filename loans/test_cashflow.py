from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import User
from core.context import clear_tenant, set_tenant
from customers.models import Customer
from employees.models import Employee
from loans.models import CollectorDailyCash, CollectorExpense
from loans.services import create_loan
from tenants.models import Membership, Tool
from tenants.services import enable_tool


@pytest.mark.django_db
def test_cash_summary_applies_daily_formula_and_employee_scope(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))

    collector_user = User.objects.create(email="cashflow-collector@example.test")
    Membership.objects.create(
        user=collector_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )
    collector = Employee.unscoped.create(
        tenant=tenant, user=collector_user, full_name="Cobrador Uno"
    )
    customer = Customer.unscoped.create(
        tenant=tenant, full_name="Cliente Uno", document_id="CASH-001", neighborhood="Centro"
    )

    set_tenant(tenant)
    loan = create_loan(
        tenant=tenant,
        customer=customer,
        collector=collector,
        principal="500.00",
        interest_rate="20.00",
        is_open_ended=True,
        frequency="daily",
        start_date=timezone.localdate(),
        paperwork_fee="25.00",
    )
    clear_tenant()

    owner_client = client_for(owner, tenant)
    opening_response = owner_client.post(
        reverse("collector-daily-cash-list"),
        {
            "collector": str(collector.pk),
            "date": timezone.localdate().isoformat(),
            "opening_amount": "1000.00",
            "notes": "Base de caja",
        },
        format="json",
    )
    assert opening_response.status_code == status.HTTP_201_CREATED

    employee_client = client_for(collector_user, tenant)
    expense_response = employee_client.post(
        reverse("collector-expense-list"),
        {
            "spent_on": timezone.localdate().isoformat(),
            "category": "transport",
            "description": "Transporte de ruta",
            "amount": "20.00",
        },
        format="json",
    )
    assert expense_response.status_code == status.HTTP_201_CREATED

    payment_response = employee_client.post(
        reverse("loan-payment-list"),
        {"loan": str(loan.pk), "amount": "100.00", "method": "cash"},
        format="json",
    )
    assert payment_response.status_code == status.HTTP_201_CREATED

    summary = employee_client.get(
        reverse("collector-cash-summary"),
        {"period": "day", "date": timezone.localdate().isoformat()},
    )
    assert summary.status_code == status.HTTP_200_OK
    assert len(summary.data["rows"]) == 1
    row = summary.data["rows"][0]
    assert row["collector_name"] == "Cobrador Uno"
    assert Decimal(row["opening_cash"]) == Decimal("1000.00")
    assert Decimal(row["collected"]) == Decimal("100.00")
    assert Decimal(row["expenses"]) == Decimal("20.00")
    assert Decimal(row["principal_lent"]) == Decimal("500.00")
    assert Decimal(row["paperwork"]) == Decimal("25.00")
    assert Decimal(row["expected_cash"]) == Decimal("605.00")


@pytest.mark.django_db
def test_customer_loan_summary_groups_multiple_loans_without_duplicate_customer_rows(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    customer = Customer.unscoped.create(
        tenant=tenant, full_name="María Pérez", document_id="GROUP-001", neighborhood="Centro"
    )
    set_tenant(tenant)
    for principal in ("100.00", "200.00"):
        create_loan(
            tenant=tenant,
            customer=customer,
            principal=principal,
            interest_rate="10.00",
            installments=2,
            frequency="weekly",
            start_date=date(2026, 10, 1),
        )
    clear_tenant()

    response = client_for(owner, tenant).get(
        reverse("customer-loan-summary"), {"search": "María"}
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["customer_count"] == 1
    assert len(response.data["rows"]) == 1
    row = response.data["rows"][0]
    assert row["customer_name"] == "María Pérez"
    assert row["loan_count"] == 2
    assert Decimal(row["principal"]) == Decimal("300.00")
    assert len(row["loans"]) == 2
    assert all(len(item["installments"]) == 2 for item in row["loans"])


@pytest.mark.django_db
def test_cash_summary_counts_principal_lent_by_disbursement_date_not_start_date(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))

    collector_user = User.objects.create(email="disbursement-collector@example.test")
    Membership.objects.create(
        user=collector_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )
    collector = Employee.unscoped.create(
        tenant=tenant, user=collector_user, full_name="Cobrador Desembolso"
    )
    customer = Customer.unscoped.create(
        tenant=tenant, full_name="Cliente Fecha", document_id="DISB-001", neighborhood="Centro"
    )

    today = timezone.localdate()
    future_start = date(2026, 12, 15)
    set_tenant(tenant)
    try:
        create_loan(
            tenant=tenant,
            customer=customer,
            collector=collector,
            principal="400.00",
            interest_rate="20.00",
            is_open_ended=True,
            frequency="daily",
            start_date=future_start,
            paperwork_fee="15.00",
        )
        create_loan(
            tenant=tenant,
            customer=customer,
            collector=collector,
            principal="900.00",
            interest_rate="20.00",
            is_open_ended=True,
            frequency="daily",
            start_date=today,
            paperwork_fee="30.00",
            import_reference="excel:hist-1",
        )
    finally:
        clear_tenant()

    client = client_for(collector_user, tenant)
    today_summary = client.get(
        reverse("collector-cash-summary"),
        {"period": "day", "date": today.isoformat()},
    )
    assert today_summary.status_code == status.HTTP_200_OK
    today_row = today_summary.data["rows"][0]
    assert Decimal(today_row["principal_lent"]) == Decimal("400.00")
    assert Decimal(today_row["paperwork"]) == Decimal("15.00")

    future_summary = client.get(
        reverse("collector-cash-summary"),
        {"period": "day", "date": future_start.isoformat()},
    )
    assert future_summary.status_code == status.HTTP_200_OK
    future_row = future_summary.data["rows"][0]
    assert Decimal(future_row["principal_lent"]) == Decimal("0.00")
    assert Decimal(future_row["paperwork"]) == Decimal("0.00")


@pytest.mark.django_db
def test_customer_loan_summary_paginates_customers_and_keeps_global_totals(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))

    customers = [
        Customer.unscoped.create(tenant=tenant, full_name=name, document_id=f"PAG-{idx}")
        for idx, name in enumerate(("Ana Uno", "Beto Dos", "Carlos Tres"), start=1)
    ]
    set_tenant(tenant)
    try:
        for idx, customer in enumerate(customers, start=1):
            create_loan(
                tenant=tenant,
                customer=customer,
                principal=f"{idx * 100}.00",
                interest_rate="10.00",
                installments=2,
                frequency="weekly",
                start_date=date(2026, 10, 1),
            )
    finally:
        clear_tenant()

    owner_client = client_for(owner, tenant)
    page_one = owner_client.get(
        reverse("customer-loan-summary"), {"page": 1, "page_size": 2}
    )
    assert page_one.status_code == status.HTTP_200_OK
    assert page_one.data["customer_count"] == 3
    assert page_one.data["page"] == 1
    assert page_one.data["page_size"] == 2
    assert page_one.data["total_pages"] == 2
    assert page_one.data["has_next"] is True
    assert page_one.data["has_previous"] is False
    assert [row["customer_name"] for row in page_one.data["rows"]] == ["Ana Uno", "Beto Dos"]
    assert page_one.data["totals"]["loan_count"] == "3"
    assert Decimal(page_one.data["totals"]["principal"]) == Decimal("600.00")

    page_two = owner_client.get(
        reverse("customer-loan-summary"), {"page": 2, "page_size": 2}
    )
    assert page_two.status_code == status.HTTP_200_OK
    assert page_two.data["customer_count"] == 3
    assert page_two.data["page"] == 2
    assert page_two.data["has_next"] is False
    assert page_two.data["has_previous"] is True
    assert [row["customer_name"] for row in page_two.data["rows"]] == ["Carlos Tres"]
    assert Decimal(page_two.data["totals"]["principal"]) == Decimal("600.00")


@pytest.mark.django_db
def test_export_excel_generates_multi_sheet_workbook_for_day_week_and_month(
    two_tenants, client_for, rls_context, seeded_tools
):
    from io import BytesIO
    from openpyxl import load_workbook

    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))

    collector_user = User.objects.create(email="excel-collector@example.test")
    Membership.objects.create(
        user=collector_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )
    collector = Employee.unscoped.create(
        tenant=tenant, user=collector_user, full_name="Cobrador Excel"
    )
    customer = Customer.unscoped.create(
        tenant=tenant, full_name="Cliente Excel", document_id="XLS-001", neighborhood="Centro"
    )
    today = timezone.localdate()
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
            start_date=today,
            paperwork_fee="25.00",
        )
    finally:
        clear_tenant()

    employee_client = client_for(collector_user, tenant)
    assert (
        employee_client.get(reverse("loan-export-excel"), {"period": "day", "date": today.isoformat()}).status_code
        == status.HTTP_403_FORBIDDEN
    )
    employee_client.post(
        reverse("loan-payment-list"),
        {"loan": str(loan.pk), "amount": "50.00", "method": "cash"},
        format="json",
    )

    owner_client = client_for(owner, tenant)
    for period in ("day", "week", "month"):
        response = owner_client.get(
            reverse("loan-export-excel"),
            {"period": period, "date": today.isoformat(), "frequency": "all"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert (
            response["Content-Type"]
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        wb = load_workbook(BytesIO(response.content))
        assert wb.sheetnames == [
            "Libro de Cartera",
            "Cierre de Caja",
            "Gastos",
            "Abonos del Período",
        ]
        assert wb["Libro de Cartera"]["D2"].value == "Cliente Excel"
        assert wb["Cierre de Caja"]["A2"].value == "Cobrador Excel"
        assert wb["Abonos del Período"]["C2"].value == "Cliente Excel"
