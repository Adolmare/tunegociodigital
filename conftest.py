import pytest
from django.db import connection
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Membership, Tenant


@pytest.fixture
def two_tenants(db):
    user_a = User.objects.create(email="owner-a@example.test")
    user_b = User.objects.create(email="owner-b@example.test")
    tenant_a = Tenant.objects.create(name="Empresa A", slug="empresa-a")
    tenant_b = Tenant.objects.create(name="Empresa B", slug="empresa-b")
    _set_rls_context(user_a.pk, tenant_a.pk)
    Membership.objects.create(user=user_a, tenant=tenant_a, role=Membership.Role.OWNER)
    _set_rls_context(user_b.pk, tenant_b.pk)
    Membership.objects.create(user=user_b, tenant=tenant_b, role=Membership.Role.OWNER)
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
    }


def _set_rls_context(user_id, tenant_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", [str(user_id)])
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])


@pytest.fixture
def client_for():
    def make_client(user, tenant=None):
        client = APIClient()
        client.force_authenticate(user=user)
        if tenant is not None:
            client.credentials(HTTP_X_TENANT_ID=str(tenant.pk))
        return client

    return make_client
