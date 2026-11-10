"""Catalogo de herramientas y tipos de negocio de la plataforma (compartido por seed y registro)."""

TOOL_SPECS = {
    "catalog": {"name": "Catálogo", "is_core": False, "depends_on": []},
    "reservations": {"name": "Reservas", "is_core": False, "depends_on": ["catalog"]},
    "barbershop": {
        "name": "Barbería",
        "is_core": False,
        "depends_on": ["catalog", "reservations"],
    },
    "deliveries": {"name": "Entregas", "is_core": False, "depends_on": ["catalog"]},
    "loans": {"name": "Préstamos", "is_core": False, "depends_on": []},
    "accounting": {"name": "Contabilidad", "is_core": True, "depends_on": []},
}

BUSINESS_TYPE_SPECS = {
    "barberia": ["barbershop", "reservations", "catalog", "accounting"],
    "restaurante": ["catalog", "deliveries", "accounting"],
    "lavadero": ["reservations", "catalog", "accounting"],
    "taller": ["reservations", "catalog", "accounting"],
    "prestamista": ["loans", "accounting"],
}
