from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from catalog.models import Category, Item
from customers.models import Customer
from employees.models import Employee
from reservations.models import Reservation, ReservationItem

from .models import BarberProfile, ServiceSale

CENTS = Decimal("0.01")
DEFAULT_DURATION_MINUTES = 30
OPEN_STATUSES = ("pending", "confirmed", "in_progress")
BLOCKING_STATUSES = ("pending", "confirmed", "in_progress", "completed")


def money(value):
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


class ServiceSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))
    duration_minutes = serializers.IntegerField(min_value=5, max_value=480)

    class Meta:
        model = Item
        fields = ("id", "name", "price", "duration_minutes", "is_active")
        read_only_fields = ("id",)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Escribe el nombre del servicio.")
        duplicates = Item.objects.filter(kind="service", name__iexact=value)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("Ya existe un servicio con ese nombre.")
        return value

    def create(self, validated_data):
        tenant = validated_data.pop("tenant")
        category, _ = Category.objects.get_or_create(
            name="Servicios", defaults={"tenant": tenant}
        )
        return Item.objects.create(
            tenant=tenant, category=category, kind="service", **validated_data
        )


class BarberSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="employee_id", read_only=True)
    full_name = serializers.CharField(source="employee.full_name", max_length=160)
    phone = serializers.CharField(
        source="employee.phone", max_length=40, required=False, allow_blank=True
    )
    is_active = serializers.BooleanField(source="employee.is_active", required=False)
    commission_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100")
    )

    class Meta:
        model = BarberProfile
        fields = ("id", "full_name", "phone", "is_active", "commission_percent")

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Escribe el nombre del barbero.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        tenant = validated_data.pop("tenant")
        employee_data = validated_data.pop("employee", {})
        employee = Employee.objects.create(
            tenant=tenant,
            full_name=employee_data["full_name"],
            phone=employee_data.get("phone", ""),
            position="Barbero",
            is_active=employee_data.get("is_active", True),
        )
        return BarberProfile.objects.create(tenant=tenant, employee=employee, **validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        employee_data = validated_data.pop("employee", {})
        employee = instance.employee
        for field, value in employee_data.items():
            setattr(employee, field, value)
        if employee_data:
            employee.save()
        if "commission_percent" in validated_data:
            instance.commission_percent = validated_data["commission_percent"]
            instance.save(update_fields=["commission_percent", "updated_at"])
        return instance


class AppointmentCreateSerializer(serializers.Serializer):
    customer = serializers.UUIDField(required=False, allow_null=True)
    customer_name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    customer_phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    barber = serializers.UUIDField()
    starts_at = serializers.DateTimeField(required=False)
    services = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=15
    )
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        customer_id = attrs.get("customer")
        if customer_id:
            customer = Customer.objects.filter(pk=customer_id, deleted_at__isnull=True).first()
            if customer is None:
                raise serializers.ValidationError({"customer": "El cliente no existe."})
            attrs["_customer"] = customer
        elif not str(attrs.get("customer_name") or "").strip():
            raise serializers.ValidationError(
                {"customer_name": "Selecciona un cliente o escribe su nombre."}
            )

        barber = Employee.objects.filter(
            pk=attrs["barber"],
            is_active=True,
            deleted_at__isnull=True,
            barber_profile__isnull=False,
        ).first()
        if barber is None:
            raise serializers.ValidationError({"barber": "Selecciona un barbero activo."})
        attrs["_barber"] = barber

        wanted = list(dict.fromkeys(attrs["services"]))
        items = list(Item.objects.filter(pk__in=wanted, kind="service", is_active=True))
        if len(items) != len(wanted):
            raise serializers.ValidationError({"services": "Algun servicio no esta disponible."})
        attrs["_items"] = items

        minutes = sum(item.duration_minutes for item in items) or DEFAULT_DURATION_MINUTES
        starts_at = attrs.get("starts_at") or timezone.now()
        ends_at = starts_at + timedelta(minutes=minutes)
        clash = Reservation.objects.filter(
            employee=barber,
            status__in=BLOCKING_STATUSES,
            starts_at__lt=ends_at,
            ends_at__gt=starts_at,
        ).first()
        if clash is not None:
            local_start = timezone.localtime(clash.starts_at).strftime("%H:%M")
            local_end = timezone.localtime(clash.ends_at).strftime("%H:%M")
            raise serializers.ValidationError(
                {"barber": f"Ese barbero ya tiene una cita de {local_start} a {local_end}."}
            )
        attrs["_starts_at"] = starts_at
        attrs["_ends_at"] = ends_at
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        tenant = self.context["tenant"]
        customer = validated_data.get("_customer")
        if customer is None:
            customer = Customer.objects.create(
                tenant=tenant,
                full_name=validated_data["customer_name"].strip(),
                phone=str(validated_data.get("customer_phone") or "").strip(),
            )
        reservation = Reservation.objects.create(
            tenant=tenant,
            customer=customer,
            employee=validated_data["_barber"],
            starts_at=validated_data["_starts_at"],
            ends_at=validated_data["_ends_at"],
            status="confirmed",
            notes=str(validated_data.get("notes") or "").strip(),
        )
        for item in validated_data["_items"]:
            ReservationItem.objects.create(
                tenant=tenant,
                reservation=reservation,
                item=item,
                quantity=1,
                unit_price=item.price,
            )
        return reservation


class CompleteAppointmentSerializer(serializers.Serializer):
    payment_method = serializers.ChoiceField(
        choices=[code for code, _ in ServiceSale.PAYMENT_METHODS], default="cash"
    )
    tip = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0"), required=False, default=Decimal("0")
    )


def serialize_sale(sale):
    return {
        "id": str(sale.pk),
        "subtotal": f"{sale.subtotal:.2f}",
        "tip": f"{sale.tip:.2f}",
        "total": f"{sale.total:.2f}",
        "payment_method": sale.payment_method,
        "commission_percent": f"{sale.commission_percent:.2f}",
        "commission_amount": f"{sale.commission_amount:.2f}",
        "paid_at": timezone.localtime(sale.paid_at).isoformat(),
    }


def serialize_appointment(reservation):
    items = list(reservation.items.all())
    total = sum((row.unit_price * row.quantity for row in items), Decimal("0"))
    sale = getattr(reservation, "sale", None)
    return {
        "id": str(reservation.pk),
        "status": reservation.status,
        "starts_at": timezone.localtime(reservation.starts_at).isoformat(),
        "ends_at": timezone.localtime(reservation.ends_at).isoformat(),
        "notes": reservation.notes,
        "customer": {
            "id": str(reservation.customer_id),
            "name": reservation.customer.full_name,
            "phone": reservation.customer.phone,
        },
        "barber": (
            {"id": str(reservation.employee_id), "name": reservation.employee.full_name}
            if reservation.employee_id
            else None
        ),
        "services": [
            {
                "id": str(row.item_id),
                "name": row.item.name,
                "price": f"{row.unit_price:.2f}",
                "quantity": row.quantity,
            }
            for row in items
        ],
        "total": f"{total:.2f}",
        "sale": serialize_sale(sale) if sale is not None else None,
    }
