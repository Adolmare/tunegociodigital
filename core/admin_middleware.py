from django.db import connection, transaction

from core.context import clear_tenant


class AdminRLSMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/admin/") or not request.user.is_superuser:
            return self.get_response(request)

        clear_tenant()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.admin_access', 'on', true)")
                return self.get_response(request)
        finally:
            clear_tenant()
