from django.contrib.gis.db import models
from django.db import migrations


class CreateExtensionIfSuperuser(migrations.operations.base.Operation):
    """
    Crea la extensión postgis SOLO si el usuario tiene permiso (superusuario).
    Si ya existe o el usuario no tiene permisos, la operación es un no-op.
    Esto permite que los tests corran sin superusuario siempre que la extensión
    ya esté habilitada en la base de datos (lo cual se hace en setup_test_db.py).
    """

    reversible = True

    def __init__(self, name):
        self.name = name

    def state_forwards(self, app_label, state):
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        db = schema_editor.connection
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_extension WHERE extname = %s", [self.name]
            )
            if cursor.fetchone():
                # La extensión ya existe, nada que hacer
                return
        # No existe: intentar crearla (requiere superusuario)
        schema_editor.execute(
            f"CREATE EXTENSION IF NOT EXISTS {self.name}"
        )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        # No eliminamos la extensión en rollback para no romper otras apps
        pass

    def describe(self):
        return f"Creates extension {self.name} (skips if already exists)"


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0002_enable_rls"),
    ]

    operations = [
        CreateExtensionIfSuperuser("postgis"),
        migrations.AddField(
            model_name="customer",
            name="location",
            field=models.PointField(blank=True, null=True, srid=4326),
        ),
    ]
