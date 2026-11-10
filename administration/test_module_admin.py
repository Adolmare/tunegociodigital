import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tenants.models import Membership, Tenant, TenantTool, Tool
from tenants.services import create_tenant, ensure_business_type

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(
        username="admin_boss",
        email="admin@test.com",
        password="AdminPass123!",
        is_staff=True,
        is_superuser=True,
    )
    return user


@pytest.fixture
def normal_user(db):
    user = User.objects.create_user(
        username="borrower_bob",
        email="bob@test.com",
        password="BobPass123!",
        is_staff=False,
        is_superuser=False,
    )
    # create a loan business for bob
    bt = ensure_business_type("prestamista")
    tenant = create_tenant(
        user=user,
        name="Préstamos de Bob",
        slug="prestamos-bob",
        business_type=bt,
    )
    return user


@pytest.mark.django_db
def test_user_modules_list_requires_admin(api_client, normal_user, admin_user):
    url = reverse("admin-users-modules")

    # Unauthenticated
    resp = api_client.get(url)
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    # Normal user (not staff)
    api_client.force_authenticate(user=normal_user)
    resp = api_client.get(url)
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # Admin user
    api_client.force_authenticate(user=admin_user)
    resp = api_client.get(url)
    assert resp.status_code == status.HTTP_200_OK
    assert isinstance(resp.data, list)
    bob_data = next((u for u in resp.data if u["username"] == "borrower_bob"), None)
    assert bob_data is not None
    assert bob_data["modules"]["loans"] is True
    assert bob_data["modules"]["barbershop"] is False


@pytest.mark.django_db
def test_toggle_module_activation_and_deactivation(api_client, normal_user, admin_user):
    toggle_url = reverse("admin-toggle-module")

    # 1. Non-admin forbidden
    api_client.force_authenticate(user=normal_user)
    resp = api_client.post(
        toggle_url,
        {"user_id": str(normal_user.id), "module": "barbershop", "enabled": True},
        format="json",
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # 2. Admin enables barbershop for normal_user
    api_client.force_authenticate(user=admin_user)
    resp = api_client.post(
        toggle_url,
        {
            "user_id": str(normal_user.id),
            "module": "barbershop",
            "enabled": True,
            "business_name": "Barbería Estilo Bob",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["enabled"] is True

    # Verify normal_user now has an active barbershop tenant and tool
    barber_tenant = Tenant.objects.filter(
        memberships__user=normal_user, business_type__code="barberia"
    ).first()
    assert barber_tenant is not None
    assert "Barbería Estilo Bob" in barber_tenant.name
    assert TenantTool.objects.filter(
        tenant=barber_tenant, tool__code="barbershop", is_enabled=True
    ).exists()

    # 3. Admin deactivates barbershop for normal_user
    resp = api_client.post(
        toggle_url,
        {"user_id": str(normal_user.id), "module": "barbershop", "enabled": False},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["enabled"] is False

    # Verify barbershop tool is now disabled
    assert (
        TenantTool.objects.filter(
            tenant=barber_tenant, tool__code="barbershop", is_enabled=True
        ).exists()
        is False
    )


@pytest.mark.django_db
def test_create_tenant_for_user_api(api_client, normal_user, admin_user):
    create_url = reverse("admin-create-tenant")
    api_client.force_authenticate(user=admin_user)

    resp = api_client.post(
        create_url,
        {
            "user_id": str(normal_user.id),
            "business_type": "barberia",
            "name": "Barbería Especial",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.data["tenant_name"] == "Barbería Especial"
    assert resp.data["business_type"] == "barberia"

    # Verify Membership
    membership = Membership.objects.filter(
        user=normal_user, tenant__slug=resp.data["tenant_slug"]
    ).first()
    assert membership is not None
    assert membership.role == Membership.Role.OWNER
