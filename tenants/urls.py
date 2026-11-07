from django.urls import path
from rest_framework.routers import DefaultRouter

<<<<<<< HEAD
=======
from .join_requests import TenantJoinRequestCreateAPIView, TenantJoinRequestManageAPIView
>>>>>>> feat/loans-cashflow-collector-dashboard
from .views import EmployeeJoinRequestViewSet, TenantListCreateAPIView

router = DefaultRouter()
router.register(
    r"employee-requests",
    EmployeeJoinRequestViewSet,
    basename="employee-join-request",
)

urlpatterns = [
    path("tenants/", TenantListCreateAPIView.as_view(), name="tenant-list-create"),
<<<<<<< HEAD
=======
    path("tenant-join-requests/", TenantJoinRequestCreateAPIView.as_view(), name="tenant-join-request-create"),
    path("tenant-join-requests/manage/", TenantJoinRequestManageAPIView.as_view(), name="tenant-join-request-manage"),
>>>>>>> feat/loans-cashflow-collector-dashboard
    *router.urls,
]
