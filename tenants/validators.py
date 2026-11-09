from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError


def validate_timezone_name(value):
    """Acepta solo nombres IANA válidos, por ejemplo ``America/Bogota``."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError, OSError):
        raise ValidationError(
            "Zona horaria no válida: %(value)s. Usa un nombre IANA como America/Bogota.",
            params={"value": value},
            code="invalid_timezone",
        )
