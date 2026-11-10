from django.urls import path

from .views import (
    CreateTenantForUserAPIView,
    ToggleModuleAPIView,
    UserModulesListAPIView,
)

urlpatterns = [
    path("users-modules/", UserModulesListAPIView.as_view(), name="admin-users-modules"),
    path("toggle-module/", ToggleModuleAPIView.as_view(), name="admin-toggle-module"),
    path("create-tenant/", CreateTenantForUserAPIView.as_view(), name="admin-create-tenant"),
]
