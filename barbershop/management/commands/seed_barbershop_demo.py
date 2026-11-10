from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from barbershop.models import BarberProfile, ServiceSale
from catalog.models import Category, Item
from customers.models import Customer
from employees.models import Employee
from reservations.models import Reservation, ReservationItem
from tenants.api import set_database_context
from tenants.models import BusinessType, Membership, Tenant
from tenants.services import create_tenant, ensure_business_type


class Command(BaseCommand):
    help = "Seeds demo data for the barbershop module and links it to adolmare123."

    def handle(self, *args, **options):
        # 1. User
        user, _ = User.objects.get_or_create(
            username="adolmare123",
            defaults={
                "email": "adolmare123@gmail.com",
                "full_name": "Adolfo",
            },
        )
        if not user.has_usable_password():
            user.set_password("Adolfo123!")
            user.save()

        # 2. Link Inova loans tenant if present
        inova = Tenant.objects.filter(slug="inova").first()
        if inova:
            with transaction.atomic():
                set_database_context(user_id=user.pk, tenant_id=inova.pk)
                Membership.objects.get_or_create(
                    user=user,
                    tenant=inova,
                    defaults={"role": Membership.Role.OWNER, "is_active": True},
                )

        # 3. Barbershop business type
        bt = ensure_business_type("barberia")

        # 4. Barbershop tenant
        shop = Tenant.objects.filter(slug="barberia-tunegocio-style").first()
        if not shop:
            shop = create_tenant(
                user=user,
                name="Barbería TuNegocio Style",
                slug="barberia-tunegocio-style",
                business_type=bt,
            )
        else:
            with transaction.atomic():
                set_database_context(user_id=user.pk, tenant_id=shop.pk)
                Membership.objects.get_or_create(
                    user=user,
                    tenant=shop,
                    defaults={"role": Membership.Role.OWNER, "is_active": True},
                )

        with transaction.atomic():
            # Activate context for shop
            set_database_context(user_id=user.pk, tenant_id=shop.pk)

            # 5. Barbers
            barber_data = [
                ("Carlos 'El Paisa' Gómez", "3001234567", Decimal("50.00")),
                ("Mateo Rodríguez", "3109876543", Decimal("45.00")),
                ("Andrés Castro", "3205551234", Decimal("50.00")),
            ]
            barbers = []
            for name, phone, comm in barber_data:
                emp, _ = Employee.unscoped.get_or_create(
                    tenant=shop,
                    full_name=name,
                    defaults={"phone": phone, "position": "Barbero", "is_active": True},
                )
                profile, _ = BarberProfile.unscoped.get_or_create(
                    tenant=shop,
                    employee=emp,
                    defaults={"commission_percent": comm},
                )
                barbers.append((emp, profile))

            # 6. Category & Services (Catalog Items)
            category, _ = Category.unscoped.get_or_create(
                tenant=shop,
                name="Servicios de Barbería",
            )
            services_data = [
                ("Corte Clásico", Decimal("20000"), 30),
                ("Corte + Barba Premium", Decimal("35000"), 45),
                ("Perfilado de Barba & Toalla Caliente", Decimal("18000"), 20),
                ("Diseño & Cejas", Decimal("12000"), 15),
                ("Tinte / Camuflaje de Canas", Decimal("40000"), 40),
            ]
            services = []
            for name, price, duration in services_data:
                item, _ = Item.unscoped.get_or_create(
                    tenant=shop,
                    category=category,
                    name=name,
                    defaults={
                        "kind": "service",
                        "price": price,
                        "duration_minutes": duration,
                        "is_active": True,
                    },
                )
                services.append(item)

            # 7. Customers
            customer_data = [
                ("Juan Fernando Pérez", "3014445566", "juan@example.com"),
                ("Santiago Ospina", "3123334455", "santiago@example.com"),
                ("Camilo Torres", "3158889900", "camilo@example.com"),
                ("Felipe Morales", "3176667788", "felipe@example.com"),
            ]
            customers = []
            for name, phone, email in customer_data:
                cust, _ = Customer.unscoped.get_or_create(
                    tenant=shop,
                    full_name=name,
                    defaults={"phone": phone, "email": email},
                )
                customers.append(cust)

            # 8. Appointments for Today
            now = timezone.now()
            today = now.date()

            # Cita 1: Completada con venta
            start_1 = timezone.make_aware(timezone.datetime(today.year, today.month, today.day, 9, 0))
            res_1, _ = Reservation.unscoped.get_or_create(
                tenant=shop,
                customer=customers[0],
                employee=barbers[0][0],
                starts_at=start_1,
                defaults={
                    "ends_at": start_1 + timedelta(minutes=30),
                    "status": "completed",
                    "notes": "Cliente puntual, prefiere degradado bajo.",
                },
            )
            ReservationItem.unscoped.get_or_create(
                tenant=shop,
                reservation=res_1,
                item=services[0],
                defaults={"quantity": 1, "unit_price": services[0].price},
            )
            ServiceSale.unscoped.get_or_create(
                tenant=shop,
                reservation=res_1,
                defaults={
                    "barber": barbers[0][0],
                    "customer_name": customers[0].full_name,
                    "subtotal": Decimal("20000"),
                    "tip": Decimal("3000"),
                    "total": Decimal("23000"),
                    "payment_method": "cash",
                    "commission_percent": barbers[0][1].commission_percent,
                    "commission_amount": Decimal("10000"),
                },
            )

            # Cita 2: Completada con venta Nequi
            start_2 = timezone.make_aware(timezone.datetime(today.year, today.month, today.day, 10, 0))
            res_2, _ = Reservation.unscoped.get_or_create(
                tenant=shop,
                customer=customers[1],
                employee=barbers[1][0],
                starts_at=start_2,
                defaults={
                    "ends_at": start_2 + timedelta(minutes=45),
                    "status": "completed",
                    "notes": "Corte y barba con toalla caliente.",
                },
            )
            ReservationItem.unscoped.get_or_create(
                tenant=shop,
                reservation=res_2,
                item=services[1],
                defaults={"quantity": 1, "unit_price": services[1].price},
            )
            ServiceSale.unscoped.get_or_create(
                tenant=shop,
                reservation=res_2,
                defaults={
                    "barber": barbers[1][0],
                    "customer_name": customers[1].full_name,
                    "subtotal": Decimal("35000"),
                    "tip": Decimal("5000"),
                    "total": Decimal("40000"),
                    "payment_method": "transfer",
                    "commission_percent": barbers[1][1].commission_percent,
                    "commission_amount": Decimal("15750"),
                },
            )

            # Cita 3: En progreso / pendiente
            start_3 = timezone.make_aware(timezone.datetime(today.year, today.month, today.day, 11, 30))
            res_3, _ = Reservation.unscoped.get_or_create(
                tenant=shop,
                customer=customers[2],
                employee=barbers[0][0],
                starts_at=start_3,
                defaults={
                    "ends_at": start_3 + timedelta(minutes=30),
                    "status": "confirmed",
                    "notes": "Llegó al local.",
                },
            )
            ReservationItem.unscoped.get_or_create(
                tenant=shop,
                reservation=res_3,
                item=services[0],
                defaults={"quantity": 1, "unit_price": services[0].price},
            )

            # Cita 4: Programada para la tarde
            start_4 = timezone.make_aware(timezone.datetime(today.year, today.month, today.day, 14, 0))
            res_4, _ = Reservation.unscoped.get_or_create(
                tenant=shop,
                customer=customers[3],
                employee=barbers[2][0],
                starts_at=start_4,
                defaults={
                    "ends_at": start_4 + timedelta(minutes=45),
                    "status": "confirmed",
                    "notes": "Corte y diseño.",
                },
            )
            ReservationItem.unscoped.get_or_create(
                tenant=shop,
                reservation=res_4,
                item=services[1],
                defaults={"quantity": 1, "unit_price": services[1].price},
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Barbería demo '{shop.name}' ({shop.slug}) creada con éxito para usuario '{user.username}'.\n"
                f"- Barberos: {len(barbers)}\n"
                f"- Servicios: {len(services)}\n"
                f"- Clientes: {len(customers)}\n"
                f"- Citas creadas: 4 (2 completadas con cobro, 2 en agenda)"
            )
        )
