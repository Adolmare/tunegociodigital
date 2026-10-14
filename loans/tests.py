import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status

from accounts.models import User
from customers.models import Customer
from employees.models import Employee
from loans.models import CollectionRoute, Loan
from tenants.models import Membership, Tool
from tenants.services import enable_tool


@pytest.mark.django_db
def test_loan_delete_requires_owner(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    manager = User.objects.create(email="manager@example.test")
    rls_context(owner, tenant)
    Membership.objects.create(user=manager, tenant=tenant, role=Membership.Role.MANAGER)

    rls_context(owner, tenant)
    customer = Customer.unscoped.create(tenant=tenant, full_name="Cliente A")
    loan = Loan.unscoped.create(
        tenant=tenant,
        customer=customer,
        principal=Decimal("1000.00"),
        interest_rate=Decimal("0.00"),
        installments=1,
        start_date="2025-01-01",
        total_payable=Decimal("1000.00"),
        balance=Decimal("1000.00"),
        status="active",
    )

    manager_client = client_for(manager, tenant)
    response = manager_client.delete(reverse("loan-detail", args=[loan.pk]))
    assert response.status_code == status.HTTP_403_FORBIDDEN

    owner_client = client_for(owner, tenant)
    response = owner_client.delete(reverse("loan-detail", args=[loan.pk]))
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db
def test_employee_can_list_and_create_loans_and_payments(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner = two_tenants["user_a"]
    tenant = two_tenants["tenant_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    user = User.objects.create(email="collector-a@example.test")
    Membership.objects.create(user=user, tenant=tenant, role=Membership.Role.EMPLOYEE)
    rls_context(user, tenant)
    employee = Employee.unscoped.create(
        tenant=tenant,
        user=user,
        full_name="Cobrador A",
    )
    customer = Customer.unscoped.create(tenant=tenant, full_name="Cliente A")

    client = client_for(user, tenant)
    response = client.post(
        reverse("loan-list"),
        {
            "customer": str(customer.pk),
            "collector": str(employee.pk),
            "principal": "1000.00",
            "interest_rate": "0.00",
            "installments": 1,
            "frequency": "monthly",
            "start_date": "2025-01-01",
            "total_payable": "1000.00",
            "balance": "1000.00",
            "status": "active",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    loan_id = response.data["id"]
    assert client.get(reverse("loan-list")).status_code == status.HTTP_200_OK

    response = client.post(
        reverse("loan-payment-list"),
        {
            "loan": loan_id,
            "collector": str(employee.pk),
            "amount": "100.00",
            "method": "cash",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    payment_id = response.data["id"]
    assert client.get(reverse("loan-payment-list")).status_code == status.HTTP_200_OK
    assert client.patch(
        reverse("loan-payment-detail", args=[payment_id]),
        {"amount": "1.00"},
        format="json",
    ).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_employee_only_sees_own_collection_routes(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner = two_tenants["user_a"]
    tenant_a = two_tenants["tenant_a"]
    rls_context(owner, tenant_a)
    enable_tool(tenant_a, Tool.objects.get(code="loans"))
    user_a = User.objects.create(email="collector-a@example.test")
    user_b = User.objects.create(email="collector-b@example.test")
    Membership.objects.create(user=user_a, tenant=tenant_a, role=Membership.Role.EMPLOYEE)
    Membership.objects.create(user=user_b, tenant=tenant_a, role=Membership.Role.EMPLOYEE)
    rls_context(user_a, tenant_a)
    employee_a = Employee.unscoped.create(
        tenant=tenant_a,
        user=user_a,
        full_name="Cobrador A",
    )
    rls_context(user_a, tenant_a)
    employee_b = Employee.unscoped.create(
        tenant=tenant_a,
        user=user_b,
        full_name="Cobrador B",
    )
    route_a = CollectionRoute.unscoped.create(
        tenant=tenant_a,
        collector=employee_a,
        name="Ruta A",
        date="2025-01-01",
    )
    CollectionRoute.unscoped.create(
        tenant=tenant_a,
        collector=employee_b,
        name="Ruta B",
        date="2025-01-01",
    )

    response = client_for(user_a, tenant_a).get(reverse("collection-route-list"))
    assert response.status_code == status.HTTP_200_OK
    assert [row["id"] for row in response.data] == [str(route_a.pk)]
