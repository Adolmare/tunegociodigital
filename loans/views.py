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
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "destroy": "owner",
        "update": "manager",
        "partial_update": "manager",
    }
    serializer_class = LoanSerializer

    def get_queryset(self):
        queryset = Loan.objects.all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        return queryset


class LoanPaymentViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "create": "employee",
        "update": "owner",
        "partial_update": "owner",
        "destroy": "owner",
    }
    http_method_names = ["get", "post", "head", "options"]
    serializer_class = LoanPaymentSerializer

    def get_queryset(self):
        queryset = LoanPayment.objects.all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        return queryset


class CollectionRouteViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "destroy": "owner",
        "update": "manager",
        "partial_update": "manager",
    }
    serializer_class = CollectionRouteSerializer

    def get_queryset(self):
        queryset = CollectionRoute.objects.all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(collector__user=self.request.user)
        return queryset


class RouteStopViewSet(ActionMinRoleMixin, TenantViewSet):
    required_tool = "loans"
    min_role = "manager"
    role_by_action = {
        "list": "employee",
        "retrieve": "employee",
        "partial_update": "employee",
        "destroy": "owner",
        "update": "manager",
    }
    serializer_class = RouteStopSerializer

    def get_queryset(self):
        queryset = RouteStop.objects.all()
        if self.request.membership.role == "employee":
            queryset = queryset.filter(route__collector__user=self.request.user)
        return queryset
