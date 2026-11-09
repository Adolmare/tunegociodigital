from datetime import date
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from accounts.models import User
from accounts.serializers import MyMembershipSerializer
from employees.models import Employee
from loans.models import CollectorDailyCash
from tenants.models import Membership, Tool
from tenants.serializers import TenantSerializer
from tenants.services import enable_tool


@pytest.mark.django_db
def test_join_code_is_only_serialized_for_owner_and_admin(two_tenants, rls_context):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    employee_user = User.objects.create(email="join-code-employee@example.test")
    owner_membership = Membership.objects.get(user=owner, tenant=tenant)
    employee_membership = Membership.objects.create(
        user=employee_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )

    assert MyMembershipSerializer(owner_membership).data["tenant_join_code"] == tenant.join_code
    assert MyMembershipSerializer(employee_membership).data["tenant_join_code"] is None

    request = SimpleNamespace(user=employee_user)
    assert TenantSerializer(tenant, context={"request": request}).data["join_code"] is None


@pytest.mark.django_db
@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {"tenant_join_request": "5/hour"},
})
def test_join_code_attempts_are_throttled(two_tenants, client_for):
    applicant = User.objects.create(email="throttle-join-code@example.test")
    client = client_for(applicant)

    responses = [
        client.post(
            reverse("tenant-join-request-create"),
            {"join_code": "INVALID0000"},
            format="json",
        )
        for _ in range(6)
    ]
    assert all(response.status_code == status.HTTP_404_NOT_FOUND for response in responses[:5])
    assert responses[5].status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
def test_daily_cash_update_duplicate_returns_validation_error(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))

    collector_user = User.objects.create(email="cash-update-collector@example.test")
    Membership.objects.create(
        user=collector_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )
    collector = Employee.unscoped.create(
        tenant=tenant, user=collector_user, full_name="Cobrador Edición"
    )
    first = CollectorDailyCash.objects.create(
        tenant=tenant, collector=collector, date=date(2026, 10, 27), opening_amount="100.00"
    )
    second = CollectorDailyCash.objects.create(
        tenant=tenant, collector=collector, date=date(2026, 10, 28), opening_amount="200.00"
    )

    response = client_for(owner, tenant).patch(
        reverse("collector-daily-cash-detail", args=[str(second.pk)]),
        {"date": first.date.isoformat()},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    second.refresh_from_db()
    assert second.date == date(2026, 10, 28)


@pytest.mark.django_db
def test_employee_cannot_create_opening_cash_and_expenses_auto_assign_collector(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))

    collector_user = User.objects.create(email="cashflow-employee-role@example.test")
    Membership.objects.create(
        user=collector_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )
    collector = Employee.unscoped.create(
        tenant=tenant, user=collector_user, full_name="Cobrador Permisos"
    )

    employee_client = client_for(collector_user, tenant)
    # Employee cannot register opening cash (must be registered by owner)
    opening_response = employee_client.post(
        reverse("collector-daily-cash-list"),
        {
            "date": date(2026, 10, 29).isoformat(),
            "opening_amount": "500.00",
        },
        format="json",
    )
    assert opening_response.status_code == status.HTTP_403_FORBIDDEN

    # Employee registers expense without specifying collector dropdown -> auto assigned
    expense_response = employee_client.post(
        reverse("collector-expense-list"),
        {
            "spent_on": date(2026, 10, 29).isoformat(),
            "category": "transport",
            "description": "Gasolina moto",
            "amount": "15.00",
        },
        format="json",
    )
    assert expense_response.status_code == status.HTTP_201_CREATED
    assert expense_response.data["collector"] == collector.pk


@pytest.mark.django_db
def test_employee_only_sees_own_expenses_in_list(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))

    collector1_user = User.objects.create(email="collector1@example.test")
    collector2_user = User.objects.create(email="collector2@example.test")
    Membership.objects.create(
        user=collector1_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )
    Membership.objects.create(
        user=collector2_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )
    collector1 = Employee.unscoped.create(
        tenant=tenant, user=collector1_user, full_name="Cobrador Uno"
    )
    collector2 = Employee.unscoped.create(
        tenant=tenant, user=collector2_user, full_name="Cobrador Dos"
    )

    owner_client = client_for(owner, tenant)
    owner_client.post(
        reverse("collector-expense-list"),
        {
            "collector": str(collector1.pk),
            "spent_on": date(2026, 11, 9).isoformat(),
            "category": "transport",
            "description": "Gasto Cobrador Uno",
            "amount": "10000.00",
        },
        format="json",
    )
    owner_client.post(
        reverse("collector-expense-list"),
        {
            "collector": str(collector2.pk),
            "spent_on": date(2026, 11, 9).isoformat(),
            "category": "food",
            "description": "Gasto Cobrador Dos",
            "amount": "20000.00",
        },
        format="json",
    )

    c1_client = client_for(collector1_user, tenant)
    res = c1_client.get(reverse("collector-expense-list"))
    assert res.status_code == status.HTTP_200_OK
    rows = res.data["results"] if isinstance(res.data, dict) else res.data
    assert len(rows) == 1
    assert rows[0]["collector"] == collector1.pk
    assert rows[0]["description"] == "Gasto Cobrador Uno"

    # Even if collector1 tries to filter by collector2's ID, they only see their own
    res_filtered = c1_client.get(
        reverse("collector-expense-list") + f"?collector={collector2.pk}"
    )
    assert res_filtered.status_code == status.HTTP_200_OK
    rows_filtered = res_filtered.data["results"] if isinstance(res_filtered.data, dict) else res_filtered.data
    assert len(rows_filtered) == 1
    assert rows_filtered[0]["collector"] == collector1.pk
