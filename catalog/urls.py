from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, ItemViewSet

router = DefaultRouter()
router.register(r"categories", CategoryViewSet, basename="catalog-category")
router.register(r"items", ItemViewSet, basename="catalog-item")

urlpatterns = [
    path("", include(router.urls)),
]
