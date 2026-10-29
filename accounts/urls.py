from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    JoinBusinessAPIView,
    LoginAPIView,
    MeAPIView,
    MyTenantsAPIView,
    RegisterAPIView,
)

urlpatterns = [
    path("register/", RegisterAPIView.as_view(), name="register"),
    path("login/", LoginAPIView.as_view(), name="token_obtain_pair"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeAPIView.as_view(), name="me"),
    path("me/tenants/", MyTenantsAPIView.as_view(), name="me-tenants"),
    path("join-business/", JoinBusinessAPIView.as_view(), name="join-business"),
]
