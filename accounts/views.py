from django.db import connection
from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from tenants.api import set_database_context
from tenants.models import EmployeeJoinRequest, Membership, Tenant

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


class JoinBusinessAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        business_id = request.data.get("business_id")
        if not business_id:
            raise ValidationError({"business_id": "Ingresa el ID del negocio."})
        set_database_context(request.user.pk)
        try:
            tenant = Tenant.objects.get(pk=business_id, status__in=["trial", "active"])
        except (Tenant.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"business_id": "No encontramos un negocio activo con ese ID."})
        set_database_context(request.user.pk, tenant.pk)
        if Membership.objects.filter(user=request.user, tenant=tenant, is_active=True).exists():
            raise ValidationError({"business_id": "Ya formas parte de este negocio."})
        join_request, created = EmployeeJoinRequest.objects.get_or_create(
            user=request.user,
            tenant=tenant,
            status=EmployeeJoinRequest.Status.PENDING,
        )
        return Response(
            {
                "id": join_request.pk,
                "tenant_name": tenant.name,
                "status": join_request.status,
                "created": created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
