from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db import models

from core.context import clear_tenant, set_tenant
from core.models import TenantOwnedModel
from tenants.models import Tenant


class TenantOwnedAdminForm(forms.ModelForm):
    tenant = forms.ModelChoiceField(queryset=Tenant.objects.all(), label="Empresa")

    class Meta:
        fields = "__all__"

    def validate_constraints(self):
        tenant = self.cleaned_data.get("tenant")
        if tenant is None:
            return
        set_tenant(tenant)
        try:
            super().validate_constraints()
        finally:
            clear_tenant()

    def clean(self):
        cleaned_data = super().clean()
        tenant = cleaned_data.get("tenant")
        if tenant is None:
            self.add_error("tenant", "Selecciona una empresa.")
            return cleaned_data

        for field in self._meta.model._meta.concrete_fields:
            if not isinstance(field, models.ForeignKey) or field.name == "tenant":
                continue
            related_model = field.remote_field.model
            if not issubclass(related_model, TenantOwnedModel):
                continue
            related_object = cleaned_data.get(field.name)
            if related_object and related_object.tenant_id != tenant.pk:
                self.add_error(
                    field.name,
                    "El registro debe pertenecer a la misma empresa.",
                )
        return cleaned_data


class SuperuserOnlyAdminMixin:
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class PlatformAdmin(SuperuserOnlyAdminMixin, admin.ModelAdmin):
    def get_list_display(self, request):
        fields = [
            field.name
            for field in self.model._meta.fields
            if isinstance(
                field,
                (
                    models.CharField,
                    models.BooleanField,
                    models.DateField,
                    models.DateTimeField,
                    models.DecimalField,
                    models.IntegerField,
                ),
            )
        ]
        if issubclass(self.model, TenantOwnedModel):
            return ("__str__", "tenant", *fields[:3])
        return ("__str__", *fields[:4])

    def get_list_filter(self, request):
        fields = [
            field.name
            for field in self.model._meta.fields
            if isinstance(field, models.BooleanField) or field.choices
        ]
        if issubclass(self.model, TenantOwnedModel):
            fields.insert(0, "tenant")
        return tuple(fields)

    def get_search_fields(self, request):
        return tuple(
            field.name
            for field in self.model._meta.fields
            if isinstance(field, (models.CharField, models.EmailField, models.SlugField))
        )[:5]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        related_model = db_field.remote_field.model
        if issubclass(related_model, TenantOwnedModel):
            kwargs.pop("using", None)
            kwargs["queryset"] = related_model.unscoped.all()
            kwargs.setdefault("required", not db_field.blank)
            kwargs.setdefault("label", db_field.verbose_name)
            kwargs.setdefault("help_text", db_field.help_text)
            kwargs.setdefault("to_field_name", db_field.remote_field.field_name)
            return forms.ModelChoiceField(**kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        related_model = db_field.remote_field.model
        if issubclass(related_model, TenantOwnedModel):
            kwargs.pop("using", None)
            kwargs["queryset"] = related_model.unscoped.all()
            kwargs.setdefault("required", not db_field.blank)
            kwargs.setdefault("label", db_field.verbose_name)
            kwargs.setdefault("help_text", db_field.help_text)
            kwargs.setdefault("to_field_name", db_field.remote_field.field_name)
            return forms.ModelMultipleChoiceField(**kwargs)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


class TenantOwnedAdmin(PlatformAdmin):
    form = TenantOwnedAdminForm

    def get_queryset(self, request):
        return self.model.unscoped.all()

    def get_form(self, request, obj=None, **kwargs):
        if kwargs.get("fields") is None:
            kwargs["fields"] = [
                field.name
                for field in self.model._meta.fields
                if field.editable and field.name != "tenant"
            ]
        else:
            kwargs["fields"] = [
                field_name
                for field_name in kwargs["fields"]
                if field_name != "tenant"
            ]
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["tenant"].initial = obj.tenant_id if obj else None
        form.base_fields["tenant"].disabled = obj is not None
        return form

    def save_model(self, request, obj, form, change):
        obj.tenant = form.cleaned_data["tenant"]
        super().save_model(request, obj, form, change)


class PlatformUserAdmin(SuperuserOnlyAdminMixin, UserAdmin):
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Información personal", {"fields": ("full_name",)}),
        (
            "Permisos",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Fechas importantes", {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "is_staff", "is_superuser"),
            },
        ),
    )
    list_display = ("email", "full_name", "is_staff", "is_superuser", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("email", "full_name")
    ordering = ("email",)
