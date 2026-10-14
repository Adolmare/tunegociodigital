from tenants.api import ActionMinRoleMixin, TenantViewSet

from .models import CollectionRoute, Loan, LoanPayment, RouteStop
from .serializers import (
    CollectionRouteSerializer,
    LoanPaymentSerializer,
    LoanSerializer,
    RouteStopSerializer,
)


class LoanViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "destroy": "owner",
        "update": "manager",
        "partial_update": "manager",
    }
    serializer_class = LoanSerializer

    def get_queryset(self):
        return Loan.objects.all()


class LoanPaymentViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "create": "manager",
        "update": "owner",
        "partial_update": "owner",
        "destroy": "owner",
    }
    http_method_names = ["get", "post", "head", "options"]
    serializer_class = LoanPaymentSerializer

    def get_queryset(self):
        return LoanPayment.objects.all()


class CollectionRouteViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "destroy": "owner",
        "update": "manager",
        "partial_update": "manager",
    }
    serializer_class = CollectionRouteSerializer

    def get_queryset(self):
        return CollectionRoute.objects.all()


class RouteStopViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "destroy": "owner",
        "update": "manager",
        "partial_update": "manager",
    }
    serializer_class = RouteStopSerializer

    def get_queryset(self):
        return RouteStop.objects.all()
