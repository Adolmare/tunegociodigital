from .base import *
DATABASES = {"default": env.db("MIGRATOR_DATABASE_URL")}
DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"
DATABASES["default"]["ATOMIC_REQUESTS"] = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]