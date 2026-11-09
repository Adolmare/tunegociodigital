from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import User
from core.context import clear_tenant, set_tenant
from customers.models import Customer
from employees.models import Employee
from loans.services import create_loan
from tenants.models import Membership
from loans.tests import _enable_loans, _make_employee_and_customer


def _rows(response):
    data = response.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


def _overdue_loan(tenant, customer, collector=None):
    set_tenant(tenant)
    try:
        return create_loan(
            tenant=tenant,
            customer=customer,
            collector=collector,
            principal="1000.00",
            interest_rate="20.00",
            installments=3,
            frequency="monthly",
            start_date=timezone.localdate() - timedelta(days=45),
        )
    finally:
        clear_tenant()


def _other_collector(owner, tenant, rls_context):
    rls_context(owner, tenant)
    user = User.objects.create(email="visibility-two@example.test")
    Membership.objects.create(user=user, tenant=tenant, role=Membership.Role.EMPLOYEE)
    return Employee.unscoped.create(tenant=tenant, user=user, full_name="Cobrador 2")


@pytest.mark.django_db
def test_employee_without_assignments_does_not_see_unassigned_loans(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, employee_user, _employee, customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    unassigned = _overdue_loan(tenant, customer)
    client = client_for(employee_user, tenant)

    assert _rows(client.get(reverse("loan-list"))) == []
    assert client.get(reverse("loan-detail", args=[unassigned.pk])).status_code == (
        status.HTTP_404_NOT_FOUND
    )
    assert _rows(client.get(reverse("loan-collection-today"))) == []

    # El dueño sí ve el préstamo sin cobrador asignado.
    owner_rows = _rows(client_for(owner, tenant).get(reverse("loan-list")))
    assert [row["id"] for row in owner_rows] == [str(unassigned.pk)]


@pytest.mark.django_db
def test_employee_only_sees_loans_assigned_to_them(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, employee_user, employee, customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    other = _other_collector(owner, tenant, rls_context)
    own_loan = _overdue_loan(tenant, customer, employee)
    other_loan = _overdue_loan(tenant, customer, other)
    unassigned_loan = _overdue_loan(tenant, customer)
    client = client_for(employee_user, tenant)

    visible = {row["id"] for row in _rows(client.get(reverse("loan-list")))}
    assert visible == {str(own_loan.pk)}
    for hidden in (other_loan, unassigned_loan):
        response = client.get(reverse("loan-detail", args=[hidden.pk]))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    queue_loans = {
        str(row["loan"]) for row in _rows(client.get(reverse("loan-collection-today")))
    }
    assert queue_loans == {str(own_loan.pk)}
