from rest_framework import viewsets

from tenants.api import TenantViewSet

from .models import CollectionRoute, Loan, LoanPayment, RouteStop
from .serializers import (
    CollectionRouteSerializer,
    LoanPaymentSerializer,
    LoanSerializer,
    RouteStopSerializer,
)


class LoanViewSet(TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    serializer_class = LoanSerializer

    def get_queryset(self):
        return Loan.objects.all()


class LoanPaymentViewSet(TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    serializer_class = LoanPaymentSerializer

    def get_queryset(self):
        return LoanPayment.objects.all()


class CollectionRouteViewSet(TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    serializer_class = CollectionRouteSerializer

    def get_queryset(self):
        return CollectionRoute.objects.all()


class RouteStopViewSet(TenantViewSet):
    required_tool = "loans"
    min_role = "employee"
    serializer_class = RouteStopSerializer

    def get_queryset(self):
        return RouteStop.objects.all()
