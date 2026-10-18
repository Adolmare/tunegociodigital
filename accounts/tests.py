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
