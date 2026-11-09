from .base import *

DATABASES = {"default": env.db("MIGRATOR_DATABASE_URL")}
DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# Usar la base de datos de test pre-creada con PostGIS habilitado.
# Esto evita que pytest intente crearla (lo que requeriría permisos de superusuario
# para ejecutar CREATE EXTENSION postgis).
DATABASES["default"]["TEST"] = {"NAME": "test_tunegocio"}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
