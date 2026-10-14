from rest_framework import viewsets

from .api import TenantViewSet as BaseTenantViewSet
from .models import Membership, Tenant, TenantApiKey
from .serializers import MembershipSerializer, TenantApiKeySerializer, TenantSerializer


class TenantViewSet(BaseTenantViewSet):
    queryset = Tenant.objects.all()
    serializer_class = TenantSerializer
    required_tool = None
    min_role = "owner"


class MembershipViewSet(BaseTenantViewSet):
    queryset = Membership.objects.all()
    serializer_class = MembershipSerializer
    required_tool = None
    min_role = "admin"


class TenantApiKeyViewSet(BaseTenantViewSet):
    queryset = TenantApiKey.objects.all()
    serializer_class = TenantApiKeySerializer
    required_tool = "deliveries"
    min_role = "owner"
