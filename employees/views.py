from django.utils import timezone
from tenants.api import TenantViewSet

from .models import Employee
from .serializers import EmployeeSerializer


class EmployeeViewSet(TenantViewSet):
    serializer_class = EmployeeSerializer
    min_role = "employee"

    def get_queryset(self):
        return Employee.objects.filter(deleted_at__isnull=True)

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])
