"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.db import connection
from django.http import HttpResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from loans.frontend import LoanPortalView


def health_check(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return HttpResponse(status=204)


urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("loans/", LoanPortalView.as_view(), name="loans-frontend"),
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
    path("api/v1/", include("accounting.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
