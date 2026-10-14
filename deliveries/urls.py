from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DeliveryOrderItemViewSet, DeliveryOrderViewSet

router = DefaultRouter()
router.register(r"delivery-orders", DeliveryOrderViewSet, basename="delivery-order")
router.register(r"delivery-order-items", DeliveryOrderItemViewSet, basename="delivery-order-item")

urlpatterns = [
    path("", include(router.urls)),
]
