from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CollectionRouteViewSet, LoanPaymentViewSet, LoanViewSet, RouteStopViewSet

router = DefaultRouter()
router.register(r"loans", LoanViewSet, basename="loan")
router.register(r"loan-payments", LoanPaymentViewSet, basename="loan-payment")
router.register(r"collection-routes", CollectionRouteViewSet, basename="collection-route")
router.register(r"route-stops", RouteStopViewSet, basename="route-stop")

urlpatterns = [
    path("", include(router.urls)),
]
