from django.contrib import admin

from core.admin import TenantOwnedAdmin
from .models import BarberProfile, ServiceSale


@admin.register(BarberProfile)
class BarberProfileAdmin(TenantOwnedAdmin):
    list_display = ("employee", "commission_percent", "tenant")
    search_fields = ("employee__full_name", "employee__phone")


@admin.register(ServiceSale)
class ServiceSaleAdmin(TenantOwnedAdmin):
    list_display = ("reservation", "barber", "total", "commission_amount", "paid_at", "tenant")
    list_filter = ("payment_method", "paid_at")
