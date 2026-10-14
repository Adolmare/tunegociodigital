from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ReservationItemViewSet, ReservationViewSet

router = DefaultRouter()
router.register(r"reservations", ReservationViewSet, basename="reservation")
router.register(r"reservation-items", ReservationItemViewSet, basename="reservation-item")

urlpatterns = [
    path("", include(router.urls)),
]
