from tenants.api import TenantViewSet

from .models import Vehicle
from .serializers import VehicleSerializer


class VehicleViewSet(TenantViewSet):
    serializer_class = VehicleSerializer
    min_role = "employee"

    def get_queryset(self):
        return Vehicle.objects.all()
