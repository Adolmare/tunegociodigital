from django.core.management.base import BaseCommand

from tenants.models import BusinessType, Tool


class Command(BaseCommand):
    help = "Seeds the default catalog of tools and business types for the platform."

    def handle(self, *args, **options):
        tool_specs = {
            "catalog": {"name": "Catálogo", "is_core": False, "depends_on": []},
            "reservations": {"name": "Reservas", "is_core": False, "depends_on": ["catalog"]},
            "deliveries": {"name": "Entregas", "is_core": False, "depends_on": ["catalog"]},
            "loans": {"name": "Préstamos", "is_core": False, "depends_on": []},
            "accounting": {"name": "Contabilidad", "is_core": True, "depends_on": []},
        }

        tools = {}
        for code, payload in tool_specs.items():
            tool, _ = Tool.objects.update_or_create(
                code=code,
                defaults={"name": payload["name"], "is_core": payload["is_core"]},
            )
            tools[code] = tool
            for dep_code in payload["depends_on"]:
                tool.depends_on.add(tools[dep_code])

        business_type_specs = {
            "barberia": ["reservations", "catalog", "accounting"],
            "restaurante": ["catalog", "deliveries", "accounting"],
            "lavadero": ["reservations", "catalog", "accounting"],
            "taller": ["reservations", "catalog", "accounting"],
            "prestamista": ["loans", "accounting"],
        }

        for code, tools_to_enable in business_type_specs.items():
            business_type, _ = BusinessType.objects.update_or_create(
                code=code,
                defaults={"name": code.title()},
            )
            selected = [tools[tool_code] for tool_code in tools_to_enable]
            business_type.tools.set(selected)

        self.stdout.write(self.style.SUCCESS("Catálogo de herramientas preparado."))
