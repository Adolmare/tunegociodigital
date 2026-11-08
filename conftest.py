import pytest
from django.core.management import call_command
from django.db import connection
from rest_framework.test import APIClient

from accounts.models import User
from core.context import set_tenant
from tenants.models import Membership, Tenant


# ---------------------------------------------------------------------------
# Parche para entorno de desarrollo local sin superusuario
# ---------------------------------------------------------------------------
# El backend django.contrib.gis.db.backends.postgis llama a
#   CREATE EXTENSION IF NOT EXISTS postgis
# en prepare_database() antes de aplicar las migraciones. En producción y CI
# el usuario de migraciones tiene SUPERUSER; en local usamos tn_owner que no
# lo es, pero la extensión ya está instalada via scripts/setup_test_db.py.
# Este parche ignora el error cuando la extensión ya existe, permitiendo que
# los tests corran sin SUPERUSER en desarrollo.
def _patched_prepare_database(self):
    """
    Versión de prepare_database que no falla si postgis ya está instalado.
    Usa self.cursor() (la API pública de DatabaseWrapper) en lugar de
    self.connection.cursor() que puede ser None durante la creación de la DB.
    """
    # super().prepare_database() no hace nada en la clase base de psycopg
    with self.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'postgis'"
        )
        if cursor.fetchone():
            return  # ya existe, no intentar crear
        # No existe: intentar crearla (requiere superusuario)
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def pytest_configure(config):
    """Hook ejecutado antes de que pytest-django cree las DBs de test."""
    try:
        from django.contrib.gis.db.backends.postgis.base import DatabaseWrapper

        DatabaseWrapper.prepare_database = _patched_prepare_database
    except ImportError:
        pass  # PostGIS no disponible, nada que parchear


@pytest.fixture
def two_tenants(db):
    user_a = User.objects.create(email="owner-a@example.test")
    user_b = User.objects.create(email="owner-b@example.test")
    # UTC explícito: las pruebas calculan fechas con timezone.localdate() (UTC) y
    # el valor por defecto de producción (America/Bogota) las haría depender de la hora.
    tenant_a = Tenant.objects.create(name="Empresa A", slug="empresa-a", timezone="UTC")
    tenant_b = Tenant.objects.create(name="Empresa B", slug="empresa-b", timezone="UTC")
    _set_rls_context(user_a.pk, tenant_a.pk)
    Membership.objects.create(user=user_a, tenant=tenant_a, role=Membership.Role.OWNER)
    _set_rls_context(user_b.pk, tenant_b.pk)
    Membership.objects.create(user=user_b, tenant=tenant_b, role=Membership.Role.OWNER)
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
    }


def _set_rls_context(user_id, tenant_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.user_id', %s, true)", [str(user_id)])
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])


@pytest.fixture
def client_for():
    def make_client(user, tenant=None):
        client = APIClient()
        client.force_authenticate(user=user)
        if tenant is not None:
            client.credentials(HTTP_X_TENANT_ID=str(tenant.pk))
        return client

    return make_client


@pytest.fixture
def seeded_tools(db):
    call_command("seed_catalog")


@pytest.fixture
def rls_context():
    def apply(user, tenant):
        # Configura RLS a nivel de PostgreSQL (para políticas de fila)
        _set_rls_context(user.pk, tenant.pk)
        # Y también el ContextVar de Python (para TenantManager en el ORM)
        set_tenant(tenant)

    return apply
