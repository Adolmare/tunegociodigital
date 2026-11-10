from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AppointmentViewSet, BarberViewSet, DaySummaryView, ServiceViewSet

router = DefaultRouter()
router.register(r"barbershop/services", ServiceViewSet, basename="barbershop-service")
router.register(r"barbershop/barbers", BarberViewSet, basename="barbershop-barber")
router.register(r"barbershop/appointments", AppointmentViewSet, basename="barbershop-appointment")

urlpatterns = [
    path("barbershop/summary/", DaySummaryView.as_view(), name="barbershop-summary"),
    path("", include(router.urls)),
]
