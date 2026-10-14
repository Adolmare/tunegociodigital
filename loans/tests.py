import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from customers.models import Customer
from loans.models import Loan
from tenants.models import Membership


@pytest.mark.django_db
def test_loan_delete_requires_owner(two_tenants, client_for):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    manager = User.objects.create(email="manager@example.test")
    Membership.objects.create(user=manager, tenant=tenant, role=Membership.Role.MANAGER)

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
