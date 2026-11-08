from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from accounts.models import User
from employees.models import Employee
from loans.tests import (
    _enable_loans,
    _make_employee_and_customer,
    _post_loan,
    _post_payment,
)
from loans.views import _read_payment_events
from tenants.models import Membership


def _second_collector(owner, tenant, rls_context):
    rls_context(owner, tenant)
    user = User.objects.create(email="collector-two@example.test")
    Membership.objects.create(user=user, tenant=tenant, role=Membership.Role.EMPLOYEE)
    employee = Employee.unscoped.create(tenant=tenant, user=user, full_name="Cobrador 2")
    return user, employee


def _events_for(user, tenant, cursor, collector=None):
    return _read_payment_events(
        str(user.pk),
        str(tenant.pk),
        cursor,
        collector_id=str(collector.pk) if collector is not None else None,
    )


@pytest.mark.django_db
def test_employee_only_reads_payment_events_of_their_own_collections(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, user_one, collector_one, customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    user_two, collector_two = _second_collector(owner, tenant, rls_context)
    cursor = timezone.now() - timedelta(minutes=5)

    owner_client = client_for(owner, tenant)
    loan_one = _post_loan(owner_client, customer, collector_one).data["id"]
    loan_two = _post_loan(owner_client, customer, collector_two).data["id"]
    payment_one = _post_payment(client_for(user_one, tenant), loan_one, "100.00").data["id"]
    payment_two = _post_payment(client_for(user_two, tenant), loan_two, "50.00").data["id"]

    own = _events_for(user_one, tenant, cursor, collector_one)
    assert [e["payload"]["payment_id"] for e in own] == [payment_one]
    assert own[0]["payload"]["collector_id"] == str(collector_one.pk)

    other = _events_for(user_two, tenant, cursor, collector_two)
    assert [e["payload"]["payment_id"] for e in other] == [payment_two]

    # Los roles de gestión (sin filtro de cobrador) siguen viendo todo el negocio.
    everything = _events_for(owner, tenant, cursor)
    assert {e["payload"]["payment_id"] for e in everything} == {payment_one, payment_two}


@pytest.mark.django_db
def test_reversal_event_is_visible_only_to_the_original_collector(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, user_one, collector_one, customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    user_two, collector_two = _second_collector(owner, tenant, rls_context)
    cursor = timezone.now() - timedelta(minutes=5)

    owner_client = client_for(owner, tenant)
    loan_id = _post_loan(owner_client, customer, collector_one).data["id"]
    payment_id = _post_payment(client_for(user_one, tenant), loan_id, "100.00").data["id"]
    reversal = owner_client.post(
        reverse("loan-payment-reverse", args=[payment_id]), {}, format="json"
    )
    assert reversal.status_code == status.HTTP_201_CREATED

    own_events = _events_for(user_one, tenant, cursor, collector_one)
    assert [e["event_name"] for e in own_events] == [
        "loan.payment_received",
        "loan.payment_reversed",
    ]
    assert _events_for(user_two, tenant, cursor, collector_two) == []


@pytest.mark.django_db
def test_employee_without_collector_profile_cannot_open_event_stream(
    two_tenants, client_for, rls_context, seeded_tools
):
    owner, tenant, _user, _collector, _customer = _make_employee_and_customer(
        two_tenants, rls_context
    )
    _enable_loans(owner, tenant, rls_context)
    rls_context(owner, tenant)
    no_profile = User.objects.create(email="no-profile@example.test")
    Membership.objects.create(user=no_profile, tenant=tenant, role=Membership.Role.EMPLOYEE)

    response = client_for(no_profile, tenant).get(reverse("loan-payment-events-stream"))
    assert response.status_code == status.HTTP_403_FORBIDDEN
