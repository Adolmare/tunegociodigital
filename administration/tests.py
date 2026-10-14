from types import SimpleNamespace

import pytest
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import RequestFactory

from accounts.models import User
from core.admin import TenantOwnedAdmin
from core.context import clear_tenant
from core.models import TenantContextMissing
from customers.models import Customer
from tenants.models import Tenant


BUSINESS_APP_LABELS = (
    "accounts",
    "tenants",
    "administration",
    "billing",
    "customers",
    "employees",
    "vehicles",
    "catalog",
    "reservations",
    "deliveries",
    "loans",
    "accounting",
)


@pytest.mark.django_db
def test_all_business_models_are_registered_in_admin():
    models = (
        model
        for app_label in BUSINESS_APP_LABELS
        for model in apps.get_app_config(app_label).get_models()
    )

    assert all(model in admin.site._registry for model in models)


def test_each_registered_business_model_has_a_working_add_form():
    request = RequestFactory().get("/admin/")
    request.user = SimpleNamespace(is_superuser=True)
    for app_label in BUSINESS_APP_LABELS:
        for model in apps.get_app_config(app_label).get_models():
            try:
                form = admin.site._registry[model].get_form(request)
            except TenantContextMissing as error:
                pytest.fail(f"{model._meta.label}: {error}")
            assert form


def test_tenant_owned_admin_uses_unscoped_queryset_without_context():
    clear_tenant()
    model_admin = admin.site._registry[Customer]
    request = RequestFactory().get("/admin/customers/customer/")
    request.user = AnonymousUser()

    assert isinstance(model_admin, TenantOwnedAdmin)
    assert model_admin.get_queryset(request).model is Customer


@pytest.mark.django_db
def test_tenant_owned_admin_form_requires_a_tenant(two_tenants):
    clear_tenant()
    model_admin = admin.site._registry[Customer]
    request = RequestFactory().get("/admin/customers/customer/add/")
    request.user = two_tenants["user_a"]
    form_class = model_admin.get_form(request)

    assert "tenant" in form_class.base_fields
    assert list(form_class.base_fields["tenant"].queryset) == list(Tenant.objects.all())


@pytest.mark.django_db
def test_superuser_can_manage_customers_across_tenants(two_tenants, client):
    for tenant, name in (
        (two_tenants["tenant_a"], "Cliente Empresa A"),
        (two_tenants["tenant_b"], "Cliente Empresa B"),
    ):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)",
                [str(tenant.pk)],
            )
        Customer.unscoped.create(tenant=tenant, full_name=name)

    superuser = User.objects.create_superuser(
        email="platform-admin@example.test",
        password="Test-password-834!",
    )
    client.force_login(superuser)

    response = client.get("/admin/customers/customer/")

    assert response.status_code == 200
    assert "Cliente Empresa A" in response.content.decode()
    assert "Cliente Empresa B" in response.content.decode()

    response = client.post(
        "/admin/customers/customer/add/",
        {
            "tenant": str(two_tenants["tenant_a"].pk),
            "full_name": "Cliente desde admin",
            "phone": "",
            "email": "",
            "document_id": "",
            "address": "",
            "notes": "",
        },
    )

    assert response.status_code == 302
    customer = Customer.unscoped.get(full_name="Cliente desde admin")
    assert customer.tenant_id == two_tenants["tenant_a"].pk
