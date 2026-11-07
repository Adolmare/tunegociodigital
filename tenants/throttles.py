from rest_framework.throttling import ScopedRateThrottle


class TenantJoinRequestThrottle(ScopedRateThrottle):
    """Limita intentos de códigos de negocio por usuario/IP."""

    scope = "tenant_join_request"
