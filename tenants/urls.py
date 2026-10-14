from django.urls import path

from .views import TenantListCreateAPIView

urlpatterns = [
    path("tenants/", TenantListCreateAPIView.as_view(), name="tenant-list-create"),
]
