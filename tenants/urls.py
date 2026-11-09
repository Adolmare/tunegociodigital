from django.urls import path
from rest_framework.routers import DefaultRouter

from .join_requests import TenantJoinRequestCreateAPIView, TenantJoinRequestManageAPIView
from .views import EmployeeJoinRequestViewSet, TenantListCreateAPIView

router = DefaultRouter()
router.register(
    r"employee-requests",
    EmployeeJoinRequestViewSet,
    basename="employee-join-request",
)

urlpatterns = [
    path("tenants/", TenantListCreateAPIView.as_view(), name="tenant-list-create"),
    path("tenant-join-requests/", TenantJoinRequestCreateAPIView.as_view(), name="tenant-join-request-create"),
    path("tenant-join-requests/manage/", TenantJoinRequestManageAPIView.as_view(), name="tenant-join-request-manage"),
    *router.urls,
]
