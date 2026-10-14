from rest_framework import viewsets

from tenants.api import TenantViewSet

from .models import Category, Item
from .serializers import CategorySerializer, ItemSerializer


class CategoryViewSet(TenantViewSet):
    required_tool = "catalog"
    min_role = "employee"
    serializer_class = CategorySerializer

    def get_queryset(self):
        return Category.objects.all()


class ItemViewSet(TenantViewSet):
    required_tool = "catalog"
    min_role = "employee"
    serializer_class = ItemSerializer

    def get_queryset(self):
        return Item.objects.all()
