from django.db import connection, transaction

from core.context import clear_tenant


class AdminRLSMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_admin_path = (
            request.path.startswith("/admin/")
            or request.path.startswith("/panel/")
            or request.path.startswith("/api/v1/admin/")
            or request.path.startswith("/api/v1/admin-panel/")
        )
        is_admin_user = getattr(request.user, "is_superuser", False) or getattr(
            request.user, "is_staff", False
        )
        if not is_admin_path or not is_admin_user:
            return self.get_response(request)

        clear_tenant()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.admin_access', 'on', true)")
                return self.get_response(request)
        finally:
            clear_tenant()
