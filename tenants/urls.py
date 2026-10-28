from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import EmployeeJoinRequestViewSet, TenantListCreateAPIView

router = DefaultRouter()
router.register(
    r"employee-requests",
    EmployeeJoinRequestViewSet,
    basename="employee-join-request",
)

urlpatterns = [
    path("tenants/", TenantListCreateAPIView.as_view(), name="tenant-list-create"),
    *router.urls,
]
