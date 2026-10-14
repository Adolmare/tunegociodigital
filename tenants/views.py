from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .api import _set_database_context
from .models import Membership, Tenant
from .serializers import TenantCreateSerializer, TenantSerializer
from .services import create_tenant


class TenantListCreateAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TenantCreateSerializer

    def get(self, request, *args, **kwargs):
        _set_database_context(request.user.pk)
        tenants = Tenant.objects.filter(
            memberships__user=request.user,
            memberships__is_active=True,
        ).distinct()
        return Response(TenantSerializer(tenants, many=True).data)

    def post(self, request, *args, **kwargs):
        _set_database_context(request.user.pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = create_tenant(
            user=request.user,
            name=serializer.validated_data["name"],
            slug=serializer.validated_data["slug"],
            business_type=serializer.validated_data.get("business_type"),
        )
        membership = Membership.objects.get(user=request.user, tenant=tenant)
        return Response(
            {
                "tenant": TenantSerializer(tenant).data,
                "role": membership.role,
            },
            status=status.HTTP_201_CREATED,
        )
