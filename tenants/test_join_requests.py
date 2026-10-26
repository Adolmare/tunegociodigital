import pytest
from django.urls import reverse
from rest_framework import status

from accounts.models import User
from employees.models import Employee
from tenants.models import Membership, TenantJoinRequest


@pytest.mark.django_db
def test_employee_join_request_requires_owner_acceptance(
    two_tenants, client_for, rls_context
):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    applicant = User.objects.create(email="applicant@example.test")

    response = client_for(applicant).post(
        reverse("tenant-join-request-create"),
        {"join_code": tenant.join_code},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["status"] == TenantJoinRequest.Status.PENDING
    assert not Membership.objects.filter(user=applicant, tenant=tenant).exists()

    owner_client = client_for(owner, tenant)
    pending = owner_client.get(reverse("tenant-join-request-manage"))
    assert pending.status_code == status.HTTP_200_OK
    assert len(pending.data) == 1

    decision = owner_client.post(
        reverse("tenant-join-request-manage"),
        {"request_id": response.data["id"], "decision": "accept"},
        format="json",
    )
    assert decision.status_code == status.HTTP_200_OK
    assert decision.data["status"] == TenantJoinRequest.Status.ACCEPTED
    assert Membership.objects.filter(
        user=applicant, tenant=tenant, role=Membership.Role.EMPLOYEE, is_active=True
    ).exists()
    assert Employee.unscoped.filter(tenant=tenant, user=applicant, is_active=True).exists()


@pytest.mark.django_db
def test_join_request_rejects_unknown_code(two_tenants, client_for):
    applicant = User.objects.create(email="unknown-code@example.test")
    response = client_for(applicant).post(
        reverse("tenant-join-request-create"),
        {"join_code": "NOTACODE00"},
        format="json",
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
