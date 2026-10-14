from rest_framework import viewsets

from tenants.api import TenantViewSet

from .models import DeliveryOrder, DeliveryOrderItem
from .serializers import DeliveryOrderSerializer, DeliveryOrderItemSerializer


class DeliveryOrderViewSet(TenantViewSet):
    required_tool = "deliveries"
    min_role = "employee"
    serializer_class = DeliveryOrderSerializer

    def get_queryset(self):
        return DeliveryOrder.objects.all()


class DeliveryOrderItemViewSet(TenantViewSet):
    required_tool = "deliveries"
    min_role = "employee"
    serializer_class = DeliveryOrderItemSerializer

    def get_queryset(self):
        return DeliveryOrderItem.objects.all()
