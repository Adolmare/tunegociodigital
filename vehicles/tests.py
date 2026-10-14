import pytest
from django.db import connection
from django.urls import reverse
from rest_framework import status

from customers.models import Customer


@pytest.mark.django_db
def test_vehicle_api_rejects_customer_from_another_tenant(two_tenants, client_for):
    client_a = client_for(two_tenants["user_a"], two_tenants["tenant_a"])
    client_b = client_for(two_tenants["user_b"], two_tenants["tenant_b"])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true)",
            [str(two_tenants["tenant_a"].pk)],
        )
    customer_a = Customer.unscoped.create(
        tenant=two_tenants["tenant_a"],
        full_name="Cliente A",
    )

    response = client_b.post(
        reverse("vehicle-list"),
        {"customer": str(customer_a.pk), "plate": "ABC-123"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert client_a.get(reverse("vehicle-list")).status_code == status.HTTP_200_OK
