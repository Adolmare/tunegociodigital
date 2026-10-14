from rest_framework import serializers

from tenants.api import TenantScopedRelatedField

from .models import Category, Item


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")


class ItemSerializer(serializers.ModelSerializer):
    category = TenantScopedRelatedField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.all()

    class Meta:
        model = Item
        exclude = ("tenant",)
        read_only_fields = ("id", "created_at", "updated_at")
