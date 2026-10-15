import os
import sys

import psycopg
from psycopg import sql


def main():
    database_url = os.environ.get("MIGRATOR_DATABASE_URL")
    app_password = os.environ.get("APP_DB_PASSWORD")
    if not database_url or not app_password:
        raise RuntimeError(
            "Define MIGRATOR_DATABASE_URL y APP_DB_PASSWORD en el entorno."
        )

    with psycopg.connect(database_url, autocommit=True) as connection:
        role_name = "tn_app"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                [role_name],
            )
            role_exists = cursor.fetchone() is not None
            if not role_exists:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOBYPASSRLS"
                    ).format(sql.Identifier(role_name))
                )
            cursor.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s",
                [role_name],
            )
            is_superuser, bypasses_rls = cursor.fetchone()
            if is_superuser or bypasses_rls:
                raise RuntimeError(
                    "El rol tn_app existente tiene privilegios incompatibles con RLS."
                )
            cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH LOGIN PASSWORD {} NOCREATEDB "
                    "NOCREATEROLE NOINHERIT"
                ).format(
                    sql.Identifier(role_name),
                    sql.Literal(app_password),
                )
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(connection.info.dbname),
                    sql.Identifier(role_name),
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(role_name)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                    "IN SCHEMA public TO {}"
                ).format(sql.Identifier(role_name))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
                ).format(sql.Identifier(role_name))
            )
            cursor.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT "
                    "SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
                ).format(sql.Identifier(role_name))
            )
            cursor.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT "
                    "USAGE, SELECT ON SEQUENCES TO {}"
                ).format(sql.Identifier(role_name))
            )
    print("Rol tn_app configurado con privilegios limitados y RLS activo.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"No se pudo configurar el rol de aplicación: {exc}", file=sys.stderr)
        raise
