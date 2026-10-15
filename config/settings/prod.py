import os

from django.core.exceptions import ImproperlyConfigured

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"

from .base import *

DEBUG = False
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY debe configurarse como variable de entorno.")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if render_hostname:
    ALLOWED_HOSTS.append(render_hostname)
ALLOWED_HOSTS = list(dict.fromkeys(ALLOWED_HOSTS))
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Configura ALLOWED_HOSTS para producción.")

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if render_hostname:
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_hostname}")
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(CSRF_TRUSTED_ORIGINS))
if not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured("Configura CSRF_TRUSTED_ORIGINS para producción.")

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31_536_000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=False,
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"

r2_account_id = env.str("R2_ACCOUNT_ID", default="")
r2_access_key_id = env.str("R2_ACCESS_KEY_ID", default="")
r2_secret_access_key = env.str("R2_SECRET_ACCESS_KEY", default="")
r2_bucket_name = env.str("R2_BUCKET_NAME", default="")
r2_configuration = {
    "R2_ACCOUNT_ID": r2_account_id,
    "R2_ACCESS_KEY_ID": r2_access_key_id,
    "R2_SECRET_ACCESS_KEY": r2_secret_access_key,
    "R2_BUCKET_NAME": r2_bucket_name,
}
missing_r2_settings = [
    setting for setting, value in r2_configuration.items() if not value
]
if missing_r2_settings:
    raise ImproperlyConfigured(
        "Configura las variables requeridas para Cloudflare R2: "
        + ", ".join(missing_r2_settings)
    )

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "access_key": r2_access_key_id,
            "secret_key": r2_secret_access_key,
            "bucket_name": r2_bucket_name,
            "endpoint_url": f"https://{r2_account_id}.r2.cloudflarestorage.com",
            "region_name": "auto",
            "signature_version": "s3v4",
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
        },
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

email_host = env.str("EMAIL_HOST", default="")
email_use_tls = env.bool("EMAIL_USE_TLS", default=True)
email_use_ssl = env.bool("EMAIL_USE_SSL", default=False)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="")
if email_host and not DEFAULT_FROM_EMAIL:
    raise ImproperlyConfigured(
        "Configura DEFAULT_FROM_EMAIL cuando el correo SMTP esté habilitado."
    )
if email_use_tls and email_use_ssl:
    raise ImproperlyConfigured("EMAIL_USE_TLS y EMAIL_USE_SSL no pueden ser True a la vez.")

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": email_host,
            "port": env.int("EMAIL_PORT", default=587),
            "username": env.str("EMAIL_HOST_USER", default=""),
            "password": env.str("EMAIL_HOST_PASSWORD", default=""),
            "use_tls": email_use_tls,
            "use_ssl": email_use_ssl,
            "timeout": env.int("EMAIL_TIMEOUT", default=10),
        },
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "production": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "production",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env.str("LOG_LEVEL", default="INFO"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env.str("DJANGO_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}