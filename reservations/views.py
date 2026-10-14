from rest_framework import viewsets

from tenants.api import TenantViewSet

from .models import Reservation, ReservationItem
from .serializers import ReservationSerializer, ReservationItemSerializer


class ReservationViewSet(TenantViewSet):
    required_tool = "reservations"
    min_role = "employee"
    serializer_class = ReservationSerializer

    def get_queryset(self):
        return Reservation.objects.all()


class ReservationItemViewSet(TenantViewSet):
    required_tool = "reservations"
    min_role = "employee"
    serializer_class = ReservationItemSerializer

    def get_queryset(self):
        return ReservationItem.objects.all()
