from django.apps import apps
from django.contrib import admin

from accounts.models import User
from core.admin import PlatformAdmin, PlatformUserAdmin, TenantOwnedAdmin
from core.models import TenantOwnedModel


APPLICATIONS = (
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

for app_label in APPLICATIONS:
    for model in apps.get_app_config(app_label).get_models():
        if model is User:
            model_admin = PlatformUserAdmin
        elif issubclass(model, TenantOwnedModel):
            model_admin = TenantOwnedAdmin
        else:
            model_admin = PlatformAdmin
        admin.site.register(model, model_admin)
