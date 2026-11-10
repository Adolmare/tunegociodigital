"""
URL configuration for config project.
"""
from django.contrib import admin
from django.db import connection
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from barbershop.frontend import BarberPortalView
from loans.frontend import LoanPortalView


def health_check(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return HttpResponse(status=204)


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="loans-frontend", permanent=False), name="root-redirect"),
    path("health/", health_check, name="health-check"),
    path("loans/", LoanPortalView.as_view(), name="loans-frontend"),
    path("barberia/", BarberPortalView.as_view(), name="barbershop-frontend"),
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/", include("tenants.urls")),
    path("api/v1/", include("customers.urls")),
    path("api/v1/", include("employees.urls")),
    path("api/v1/", include("vehicles.urls")),
    path("api/v1/", include("catalog.urls")),
    path("api/v1/", include("reservations.urls")),
    path("api/v1/", include("deliveries.urls")),
    path("api/v1/", include("loans.urls")),
    path("api/v1/", include("barbershop.urls")),
    path("api/v1/", include("accounting.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
