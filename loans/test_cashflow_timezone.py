from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import User
from core.context import clear_tenant, set_tenant
from customers.models import Customer
from employees.models import Employee
from loans.models import LoanPayment
from loans.services import create_loan
from tenants.models import Membership, Tenant, Tool
from tenants.services import enable_tool

BOGOTA = ZoneInfo("America/Bogota")


def _bogota_collector_setup(two_tenants, rls_context):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    Tenant.objects.filter(pk=tenant.pk).update(timezone="America/Bogota")
    tenant.refresh_from_db()
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="loans"))
    collector_user = User.objects.create(email="tz-collector@example.test")
    Membership.objects.create(
        user=collector_user, tenant=tenant, role=Membership.Role.EMPLOYEE
    )
    collector = Employee.unscoped.create(
        tenant=tenant, user=collector_user, full_name="Cobrador TZ"
    )
    customer = Customer.unscoped.create(tenant=tenant, full_name="Cliente TZ")
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
            start_date=datetime(2026, 11, 1).date(),
        )
    finally:
        clear_tenant()
    return tenant, owner, collector_user, collector, loan


@pytest.mark.django_db
def test_cash_summary_groups_payments_by_the_tenant_calendar_day(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant, _owner, collector_user, _collector, loan = _bogota_collector_setup(
        two_tenants, rls_context
    )
    client = client_for(collector_user, tenant)
    payment = client.post(
        reverse("loan-payment-list"),
        {"loan": str(loan.pk), "amount": "100.00", "method": "cash"},
        format="json",
    )
    assert payment.status_code == status.HTTP_201_CREATED

    # 6 nov 2026, 11:30 p. m. en Bogotá = 7 nov 04:30 UTC.
    LoanPayment.unscoped.filter(pk=payment.data["id"]).update(
        paid_at=datetime(2026, 11, 6, 23, 30, tzinfo=BOGOTA)
    )

    def collected(day):
        response = client.get(
            reverse("collector-cash-summary"), {"period": "day", "date": day}
        )
        assert response.status_code == status.HTTP_200_OK
        return Decimal(response.data["rows"][0]["collected"])

    assert collected("2026-11-06") == Decimal("100.00")
    assert collected("2026-11-07") == Decimal("0")


@pytest.mark.django_db
def test_default_summary_date_follows_the_tenant_timezone(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant, _owner, collector_user, _collector, _loan = _bogota_collector_setup(
        two_tenants, rls_context
    )
    client = client_for(collector_user, tenant)

    # 7 nov 03:00 UTC sigue siendo 6 nov, 10:00 p. m., en Bogotá.
    fixed_now = datetime(2026, 11, 7, 3, 0, tzinfo=dt_timezone.utc)
    with mock.patch("django.utils.timezone.now", return_value=fixed_now):
        response = client.get(reverse("collector-cash-summary"), {"period": "day"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["start_date"] == "2026-11-06"


@pytest.mark.django_db
def test_timezone_does_not_leak_and_invalid_values_fall_back_to_utc(
    two_tenants, client_for, rls_context, seeded_tools
):
    tenant, _owner, collector_user, _collector, _loan = _bogota_collector_setup(
        two_tenants, rls_context
    )
    client = client_for(collector_user, tenant)
    summary_url = reverse("collector-cash-summary")

    assert client.get(summary_url).status_code == status.HTTP_200_OK
    assert timezone.get_current_timezone_name() == "UTC"

    Tenant.objects.filter(pk=tenant.pk).update(timezone="Mars/Base")
    assert client.get(summary_url).status_code == status.HTTP_200_OK
    assert timezone.get_current_timezone_name() == "UTC"


def test_tenant_timezone_field_rejects_unknown_zones_and_defaults_to_bogota():
    field = Tenant._meta.get_field("timezone")
    assert field.default == "America/Bogota"
    assert field.clean("America/Bogota", None) == "America/Bogota"
    with pytest.raises(ValidationError):
        field.clean("Mars/Base", None)
