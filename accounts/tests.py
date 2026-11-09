import pytest
from django.urls import reverse
from rest_framework import status

from accounts.models import User


@pytest.mark.django_db
def test_register_creates_user(client):
    response = client.post(
        reverse("register"),
        {
            "username": "nueva-persona",
            "email": "new-user@example.test",
            "full_name": "Nueva persona",
            "password": "A-very-strong-test-password-739!",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    user = User.objects.get(email="new-user@example.test")
    assert user.username == "nueva-persona"
    assert user.check_password("A-very-strong-test-password-739!")
    assert "password" not in response.data


@pytest.mark.django_db
def test_login_authenticates_with_username_not_email(client):
    user = User.objects.create_user(
        username="persona",
        email="persona@example.test",
        password="A-very-strong-test-password-739!",
    )

    response = client.post(
        reverse("token_obtain_pair"),
        {"username": "persona", "password": "A-very-strong-test-password-739!"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    assert "refresh" in response.data

    email_response = client.post(
        reverse("token_obtain_pair"),
        {"username": user.email, "password": "A-very-strong-test-password-739!"},
        format="json",
    )
    assert email_response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_me_can_read_and_update_profile(two_tenants, client_for):
    client = client_for(two_tenants["user_a"])

    response = client.get(reverse("me"))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["username"] == two_tenants["user_a"].username
    assert response.data["email"] == two_tenants["user_a"].email

    response = client.patch(reverse("me"), {"full_name": "Nombre actualizado"}, format="json")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["full_name"] == "Nombre actualizado"


@pytest.mark.django_db
def test_me_tenants_returns_only_active_memberships(two_tenants, client_for):
    client = client_for(two_tenants["user_a"])

    response = client.get(reverse("me-tenants"))

    assert response.status_code == status.HTTP_200_OK
    assert [row["tenant_id"] for row in response.data] == [str(two_tenants["tenant_a"].pk)]
    assert response.data[0]["tenant_currency"] == "COP"


@pytest.mark.django_db
def test_register_owner_creates_user_and_business_atomically(client):
    from django.core.cache import cache
    from tenants.models import Membership, Tenant

    cache.clear()
    response = client.post(
        reverse("register"),
        {
            "username": "dueno-nuevo",
            "email": "dueno-nuevo@example.test",
            "full_name": "Dueño Nuevo",
            "password": "Strong-Owner-Password-2026!",
            "password_confirm": "Strong-Owner-Password-2026!",
            "register_role": "owner",
            "business_name": "Cartera del Caribe",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["tenant"]["tenant_name"] == "Cartera del Caribe"
    assert response.data["tenant"]["role"] == Membership.Role.OWNER
    user = User.objects.get(username="dueno-nuevo")
    assert Tenant.objects.filter(name="Cartera del Caribe", memberships__user=user).exists()


@pytest.mark.django_db
def test_register_collector_validates_join_code_before_creating_user(two_tenants, client):
    from django.core.cache import cache
    from tenants.models import TenantJoinRequest

    cache.clear()
    tenant = two_tenants["tenant_a"]

    # Código inválido: no debe dejar el usuario creado a medias
    bad_response = client.post(
        reverse("register"),
        {
            "username": "cobrador-atomico",
            "email": "cobrador-atomico@example.test",
            "full_name": "Cobrador Atómico",
            "password": "Strong-Collector-Password-2026!",
            "password_confirm": "Strong-Collector-Password-2026!",
            "register_role": "collector",
            "join_code": "INVALID999",
        },
        format="json",
    )
    assert bad_response.status_code == status.HTTP_400_BAD_REQUEST
    assert "join_code" in bad_response.data
    assert not User.objects.filter(username="cobrador-atomico").exists()

    # Ahora corrige el código con el mismo usuario y correo: debe crear usuario y solicitud
    good_response = client.post(
        reverse("register"),
        {
            "username": "cobrador-atomico",
            "email": "cobrador-atomico@example.test",
            "full_name": "Cobrador Atómico",
            "password": "Strong-Collector-Password-2026!",
            "password_confirm": "Strong-Collector-Password-2026!",
            "register_role": "collector",
            "join_code": tenant.join_code,
        },
        format="json",
    )
    assert good_response.status_code == status.HTTP_201_CREATED
    assert "access" in good_response.data
    assert good_response.data["join_request"]["tenant_id"] == str(tenant.pk)
    user = User.objects.get(username="cobrador-atomico")
    assert TenantJoinRequest.objects.filter(user=user, tenant=tenant).exists()
