from django.utils import timezone
from tenants.api import TenantViewSet

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(TenantViewSet):
    serializer_class = CustomerSerializer
    min_role = "employee"

    def get_queryset(self):
        return Customer.objects.all()

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])
