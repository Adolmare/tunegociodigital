import pytest
from django.urls import reverse
from rest_framework import status

from customers.models import Customer


@pytest.mark.django_db
def test_customer_crud_is_scoped_to_active_tenant(two_tenants, client_for):
    client_a = client_for(two_tenants["user_a"], two_tenants["tenant_a"])
    client_b = client_for(two_tenants["user_b"], two_tenants["tenant_b"])

    created = client_a.post(
        reverse("customer-list"),
        {"full_name": "Cliente A", "neighborhood": "VENECIA"},
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED
    assert created.data["neighborhood"] == "VENECIA"
    customer_id = created.data["id"]
    assert client_a.get(reverse("customer-detail", args=[customer_id])).status_code == status.HTTP_200_OK
    assert client_b.get(reverse("customer-detail", args=[customer_id])).status_code == status.HTTP_404_NOT_FOUND

    deleted = client_a.delete(reverse("customer-detail", args=[customer_id]))
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert Customer.unscoped.filter(pk=customer_id, deleted_at__isnull=False).exists()
    assert client_a.get(reverse("customer-list")).data == []
