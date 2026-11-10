from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from accounts.models import User
from tenants.models import Membership, Tenant, TenantTool, Tool
from tenants.services import enable_tool


TODAY = datetime.now(dt_timezone.utc).date()


def at(hour, minute=0, days=0):
    day = TODAY + timedelta(days=days)
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00Z"


@pytest.fixture
def barbershop(two_tenants, rls_context, seeded_tools):
    tenant = two_tenants["tenant_a"]
    owner = two_tenants["user_a"]
    rls_context(owner, tenant)
    enable_tool(tenant, Tool.objects.get(code="barbershop"))
    return {"tenant": tenant, "owner": owner}


def _create_service(client, name="Corte", price="20000", minutes=30):
    response = client.post(
        reverse("barbershop-service-list"),
        {"name": name, "price": price, "duration_minutes": minutes},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data


def _create_barber(client, name="Carlos", commission="50"):
    response = client.post(
        reverse("barbershop-barber-list"),
        {"full_name": name, "phone": "3000000000", "commission_percent": commission},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data


def _create_appointment(client, barber, services, starts_at=None, name="Pedro"):
    return client.post(
        reverse("barbershop-appointment-list"),
        {
            "customer_name": name,
            "customer_phone": "3111111111",
            "barber": barber["id"],
            "services": [service["id"] for service in services],
            "starts_at": starts_at or at(10),
        },
        format="json",
    )


@pytest.mark.django_db
def test_owner_builds_catalog_and_books_appointment(barbershop, client_for):
    client = client_for(barbershop["owner"], barbershop["tenant"])
    corte = _create_service(client, "Corte", "20000", 30)
    barba = _create_service(client, "Barba", "10000", 15)
    barber = _create_barber(client)

    duplicate = client.post(
        reverse("barbershop-service-list"),
        {"name": "corte", "price": "5000", "duration_minutes": 20},
        format="json",
    )
    assert duplicate.status_code == status.HTTP_400_BAD_REQUEST

    response = _create_appointment(client, barber, [corte, barba])
    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert response.data["total"] == "30000.00"
    assert response.data["customer"]["name"] == "Pedro"
    assert response.data["status"] == "confirmed"
    assert len(response.data["services"]) == 2
    # 30 + 15 minutos
    assert response.data["starts_at"][11:16] == "10:00"
    assert response.data["ends_at"][11:16] == "10:45"

    listing = client.get(reverse("barbershop-appointment-list") + "?date=" + TODAY.isoformat())
    assert listing.status_code == status.HTTP_200_OK
    assert len(listing.data) == 1
    other_day = client.get(reverse("barbershop-appointment-list") + "?date=" + (TODAY + timedelta(days=1)).isoformat())
    assert other_day.data == []


@pytest.mark.django_db
def test_overlapping_appointments_for_same_barber_are_rejected(barbershop, client_for):
    client = client_for(barbershop["owner"], barbershop["tenant"])
    corte = _create_service(client)
    barber = _create_barber(client)
    other_barber = _create_barber(client, "Luis")

    assert _create_appointment(client, barber, [corte], at(10)).status_code == 201
    clash = _create_appointment(client, barber, [corte], at(10, 15), "Ana")
    assert clash.status_code == status.HTTP_400_BAD_REQUEST
    assert "barber" in clash.data
    # otro barbero a la misma hora y el mismo barbero justo despues si se permiten
    assert _create_appointment(client, other_barber, [corte], at(10, 15), "Ana").status_code == 201
    assert _create_appointment(client, barber, [corte], at(10, 30), "Luis").status_code == 201


@pytest.mark.django_db
def test_complete_creates_sale_with_commission_and_summary(barbershop, client_for):
    client = client_for(barbershop["owner"], barbershop["tenant"])
    corte = _create_service(client, "Corte", "20000", 30)
    barba = _create_service(client, "Barba", "10000", 15)
    barber = _create_barber(client, "Carlos", "40")
    appointment = _create_appointment(client, barber, [corte, barba]).data

    url = reverse("barbershop-appointment-complete", args=[appointment["id"]])
    done = client.post(url, {"payment_method": "transfer", "tip": "5000"}, format="json")
    assert done.status_code == status.HTTP_200_OK, done.data
    assert done.data["status"] == "completed"
    assert done.data["sale"]["subtotal"] == "30000.00"
    assert done.data["sale"]["commission_amount"] == "12000.00"
    assert done.data["sale"]["total"] == "35000.00"

    again = client.post(url, {"payment_method": "cash"}, format="json")
    assert again.status_code == status.HTTP_400_BAD_REQUEST

    summary = client.get(reverse("barbershop-summary"))
    assert summary.status_code == status.HTTP_200_OK, summary.data
    totals = summary.data["totals"]
    assert totals["services"] == 1
    assert totals["subtotal"] == "30000.00"
    assert totals["commission"] == "12000.00"
    assert totals["tips"] == "5000.00"
    assert totals["barber_pay"] == "17000.00"
    assert totals["owner_net"] == "18000.00"
    assert totals["collected"] == "35000.00"
    assert summary.data["by_method"] == {"transfer": "35000.00"}
    assert summary.data["appointments"]["completed"] == 1
    row = summary.data["rows"][0]
    assert row["barber_name"] == "Carlos"
    assert Decimal(row["owner_net"]) == Decimal("18000.00")


@pytest.mark.django_db
def test_cancelled_appointment_cannot_be_charged_and_frees_the_slot(barbershop, client_for):
    client = client_for(barbershop["owner"], barbershop["tenant"])
    corte = _create_service(client)
    barber = _create_barber(client)
    appointment = _create_appointment(client, barber, [corte]).data

    cancelled = client.post(reverse("barbershop-appointment-cancel", args=[appointment["id"]]))
    assert cancelled.status_code == status.HTTP_200_OK
    assert cancelled.data["status"] == "cancelled"
    charge = client.post(
        reverse("barbershop-appointment-complete", args=[appointment["id"]]),
        {"payment_method": "cash"},
        format="json",
    )
    assert charge.status_code == status.HTTP_400_BAD_REQUEST
    assert _create_appointment(client, barber, [corte], name="Nuevo").status_code == 201


@pytest.mark.django_db
def test_receptionist_can_operate_but_not_configure(barbershop, client_for):
    owner_client = client_for(barbershop["owner"], barbershop["tenant"])
    corte = _create_service(owner_client)
    barber = _create_barber(owner_client)

    receptionist = User.objects.create(email="recepcion@example.test", username="recepcion")
    Membership.objects.create(
        user=receptionist, tenant=barbershop["tenant"], role=Membership.Role.EMPLOYEE
    )
    client = client_for(receptionist, barbershop["tenant"])

    assert client.get(reverse("barbershop-service-list")).status_code == 200
    forbidden_service = client.post(
        reverse("barbershop-service-list"),
        {"name": "Tinte", "price": "50000", "duration_minutes": 60},
        format="json",
    )
    assert forbidden_service.status_code == status.HTTP_403_FORBIDDEN
    forbidden_barber = client.post(
        reverse("barbershop-barber-list"),
        {"full_name": "Intruso", "commission_percent": "10"},
        format="json",
    )
    assert forbidden_barber.status_code == status.HTTP_403_FORBIDDEN
    assert _create_appointment(client, barber, [corte]).status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_barbershop_data_is_isolated_between_tenants(barbershop, two_tenants, client_for, rls_context):
    client = client_for(barbershop["owner"], barbershop["tenant"])
    corte = _create_service(client)
    barber = _create_barber(client)
    assert _create_appointment(client, barber, [corte]).status_code == 201

    other_tenant = two_tenants["tenant_b"]
    other_owner = two_tenants["user_b"]
    rls_context(other_owner, other_tenant)
    enable_tool(other_tenant, Tool.objects.get(code="barbershop"))
    other_client = client_for(other_owner, other_tenant)

    assert other_client.get(reverse("barbershop-service-list")).data == []
    assert other_client.get(reverse("barbershop-barber-list")).data == []
    assert other_client.get(reverse("barbershop-appointment-list")).data == []
    foreign = _create_appointment(other_client, barber, [corte])
    assert foreign.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_tool_is_required(two_tenants, client_for, rls_context, seeded_tools):
    tenant = two_tenants["tenant_a"]
    rls_context(two_tenants["user_a"], tenant)
    client = client_for(two_tenants["user_a"], tenant)
    assert client.get(reverse("barbershop-service-list")).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_owner_can_register_a_barbershop(client, rls_context, seeded_tools):
    response = client.post(
        "/api/v1/auth/register/",
        {
            "username": "dueno_barber",
            "email": "dueno@barberia.test",
            "full_name": "Dueño Barbería",
            "password": "ClaveSegura2026x",
            "password_confirm": "ClaveSegura2026x",
            "register_role": "owner",
            "business_type": "barberia",
            "business_name": "Barbería El Corte",
        },
        content_type="application/json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.content
    data = response.json()
    assert data["tenant"]["tenant_business_type"] == "barberia"

    tenant = Tenant.objects.get(pk=data["tenant"]["tenant_id"])
    user = User.objects.get(username="dueno_barber")
    rls_context(user, tenant)
    enabled = set(
        TenantTool.objects.filter(tenant=tenant, is_enabled=True).values_list("tool__code", flat=True)
    )
    assert {"barbershop", "reservations", "catalog", "accounting"} <= enabled
    assert "loans" not in enabled

