import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import psycopg


def postgres_environment(database_url):
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("RESTORE_DATABASE_URL debe ser una URL PostgreSQL válida.")
    query = parse_qs(parsed.query)
    result = os.environ.copy()
    result.update(
        {
            "PGHOST": parsed.hostname,
            "PGPORT": str(parsed.port or 5432),
            "PGUSER": unquote(parsed.username or ""),
            "PGPASSWORD": unquote(parsed.password or ""),
            "PGDATABASE": unquote(parsed.path.lstrip("/")),
        }
    )
    if query.get("sslmode"):
        result["PGSSLMODE"] = query["sslmode"][0]
    if not result["PGUSER"] or not result["PGPASSWORD"] or not result["PGDATABASE"]:
        raise ValueError("La URL destino debe incluir usuario, clave y base de datos.")
    return result


def main():
    backup_file = Path(os.environ.get("BACKUP_FILE", ""))
    database_url = os.environ.get("RESTORE_DATABASE_URL")
    if not database_url or not backup_file.is_file():
        raise RuntimeError("Define RESTORE_DATABASE_URL y BACKUP_FILE existente.")
    env = postgres_environment(database_url)
    database_name = env["PGDATABASE"]
    if not database_name.startswith("restore_check_"):
        raise ValueError(
            "La restauración de prueba solo se permite en una base "
            "cuyo nombre empiece por restore_check_."
        )

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.django_migrations')"
            )
            if cursor.fetchone()[0] is not None:
                raise RuntimeError(
                    "La base destino no está vacía; usa una base temporal nueva."
                )

    subprocess.run(
        [
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "--dbname",
            database_name,
            str(backup_file),
        ],
        env=env,
        check=True,
    )

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT PostGIS_Version()")
            postgis_version = cursor.fetchone()[0]
            cursor.execute(
                "SELECT app, name FROM django_migrations "
                "WHERE app = 'customers' AND name = '0003_customer_location'"
            )
            if cursor.fetchone() is None:
                raise RuntimeError("Falta la migración de ubicación GPS restaurada.")
            cursor.execute("SELECT count(*) FROM customers_customer")
            customer_count = cursor.fetchone()[0]
    print(
        "Restauración validada: PostGIS "
        f"{postgis_version}; migración GPS presente; "
        f"{customer_count} clientes."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Falló la verificación de restauración: {exc}", file=sys.stderr)
        raise
