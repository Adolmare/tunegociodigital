import pytest
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.urls import reverse
from rest_framework import status

from tenants.models import BusinessType, Membership, Tenant


@pytest.mark.django_db
def test_tenant_list_only_returns_user_memberships(two_tenants, client_for):
    client = client_for(two_tenants["user_a"])

    response = client.get(reverse("tenant-list-create"))

    assert response.status_code == status.HTTP_200_OK
    assert [row["id"] for row in response.data] == [str(two_tenants["tenant_a"].pk)]


@pytest.mark.django_db
def test_tenant_creation_needs_no_tenant_header_and_creates_owner(two_tenants, client_for):
    business_type = BusinessType.objects.create(code="barberia", name="Barbería")
    client = client_for(two_tenants["user_a"])

    response = client.post(
        reverse("tenant-list-create"),
        {"name": "Nueva empresa", "slug": "nueva-empresa", "business_type": "barberia"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    tenant = Tenant.objects.get(slug="nueva-empresa")
    assert response.data["tenant"]["id"] == str(tenant.pk)
    assert response.data["role"] == Membership.Role.OWNER
    assert Membership.objects.filter(
        user=two_tenants["user_a"],
        tenant=tenant,
        role=Membership.Role.OWNER,
        is_active=True,
    ).exists()
    assert tenant.business_type == business_type


@pytest.mark.django_db
def test_tenant_creation_rejects_tenant_from_request(two_tenants, client_for):
    client = client_for(two_tenants["user_a"])

    response = client.post(
        reverse("tenant-list-create"),
        {
            "name": "Otra empresa",
            "slug": "otra-empresa",
            "tenant": str(two_tenants["tenant_b"].pk),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Tenant.objects.filter(slug="otra-empresa").exists()


@pytest.mark.django_db
def test_tenant_collection_does_not_allow_mutation(two_tenants, client_for):
    client = client_for(two_tenants["user_a"])

    response = client.patch(
        reverse("tenant-list-create"),
        {"name": "HACKEADO"},
        format="json",
    )

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    two_tenants["tenant_b"].refresh_from_db()
    assert two_tenants["tenant_b"].name == "Empresa B"


@pytest.mark.django_db
def test_malformed_tenant_header_returns_not_found(two_tenants, client_for):
    client = client_for(two_tenants["user_a"])
    client.credentials(HTTP_X_TENANT_ID="not-a-uuid")

    response = client.get(reverse("catalog-category-list"))

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_all_tenant_tables_force_row_level_security():
    tenant_tables = []
    for model in apps.get_models():
        try:
            model._meta.get_field("tenant")
        except FieldDoesNotExist:
            continue
        tenant_tables.append(model._meta.db_table)

    assert tenant_tables
    with connection.cursor() as cursor:
        for table_name in tenant_tables:
            cursor.execute(
                """
                SELECT relation.relrowsecurity, relation.relforcerowsecurity
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = current_schema()
                  AND relation.relname = %s
                """,
                [table_name],
            )
            rls_state = cursor.fetchone()
            assert rls_state == (True, True), f"RLS no está activa y forzada en {table_name}"
