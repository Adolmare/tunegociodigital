from django.core.management.base import BaseCommand

from tenants.services import sync_catalog


class Command(BaseCommand):
    help = "Seeds the default catalog of tools and business types for the platform."

    def handle(self, *args, **options):
        sync_catalog()
        self.stdout.write(self.style.SUCCESS("Catálogo de herramientas preparado."))
