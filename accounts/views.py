from django.db import connection
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView

from tenants.models import Membership

from .serializers import MeSerializer, MyMembershipSerializer, RegisterSerializer


class RegisterAPIView(generics.CreateAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"


class LoginAPIView(TokenObtainPairView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class MeAPIView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MeSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user


class MyTenantsAPIView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MyMembershipSerializer

    def get(self, request, *args, **kwargs):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.user_id', %s, true)",
                [str(request.user.pk)],
            )
            cursor.execute("SELECT set_config('app.tenant_id', '', true)")
        memberships = (
            Membership.objects.select_related("tenant")
            .filter(user=request.user, is_active=True)
            .order_by("created_at")
        )
        return Response(self.get_serializer(memberships, many=True).data)
