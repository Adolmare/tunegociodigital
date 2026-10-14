import pytest
from django.urls import reverse
from rest_framework import status

from .models import Employee


@pytest.mark.django_db
def test_employee_api_is_tenant_scoped(two_tenants, client_for, rls_context):
    client_a = client_for(two_tenants["user_a"], two_tenants["tenant_a"])
    client_b = client_for(two_tenants["user_b"], two_tenants["tenant_b"])

    rls_context(two_tenants["user_a"], two_tenants["tenant_a"])
    employee = Employee.unscoped.create(
        tenant=two_tenants["tenant_a"],
        full_name="Empleado A",
    )

    response = client_a.get(reverse("employee-detail", args=[employee.pk]))
    assert response.status_code == status.HTTP_200_OK

    response = client_b.get(reverse("employee-detail", args=[employee.pk]))
    assert response.status_code == status.HTTP_404_NOT_FOUND

    response = client_a.delete(reverse("employee-detail", args=[employee.pk]))
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert client_a.get(reverse("employee-list")).data == []
