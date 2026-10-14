import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from accounting.models import Account
from tenants.models import Membership
from tenants.services import create_tenant


@pytest.mark.django_db
def test_account_destroy_requires_owner():
    user = User.objects.create(email="owner@example.test")
    tenant = create_tenant(user, "Empresa", "empresa-conta")

    manager = User.objects.create(email="manager@example.test")
    Membership.objects.create(user=manager, tenant=tenant, role=Membership.Role.MANAGER)

    account = Account.unscoped.create(
        tenant=tenant,
        code="100",
        name="Caja",
    )

    owner_client = APIClient()
    owner_client.force_authenticate(user)
    owner_client.credentials(HTTP_X_TENANT_ID=str(tenant.pk))

    manager_client = APIClient()
    manager_client.force_authenticate(manager)
    manager_client.credentials(HTTP_X_TENANT_ID=str(tenant.pk))

    manager_response = manager_client.delete(reverse("accounting-account-detail", args=[account.pk]))
    assert manager_response.status_code == status.HTTP_403_FORBIDDEN

    owner_response = owner_client.delete(reverse("accounting-account-detail", args=[account.pk]))
    assert owner_response.status_code == status.HTTP_204_NO_CONTENT
