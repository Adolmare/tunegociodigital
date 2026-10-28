from django.urls import path

from .join_requests import TenantJoinRequestCreateAPIView, TenantJoinRequestManageAPIView
from .views import TenantListCreateAPIView

urlpatterns = [
    path("tenants/", TenantListCreateAPIView.as_view(), name="tenant-list-create"),
    path("tenant-join-requests/", TenantJoinRequestCreateAPIView.as_view(), name="tenant-join-request-create"),
    path("tenant-join-requests/manage/", TenantJoinRequestManageAPIView.as_view(), name="tenant-join-request-manage"),
]
