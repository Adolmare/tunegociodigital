"""
Crea la base de datos test_tunegocio con PostGIS habilitado como superusuario,
otorga todos los privilegios a tn_owner y tn_app.
Debe ejecutarse con el usuario postgres (superusuario).
"""
import subprocess, sys

PSQL = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"

def run(sql, dbname="postgres"):
    r = subprocess.run(
        [PSQL, "-U", "postgres", "-d", dbname, "-c", sql],
        capture_output=True, text=True
    )
    out = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0
    print(f"  {'OK' if ok else 'FAIL'} | {sql[:80]!r}")
    if out:
        print(f"       {out[:200]}")
    return ok

print("=== Setup test_tunegocio ===")

# 1. Crear DB si no existe
r = subprocess.run(
    [PSQL, "-U", "postgres", "-tc",
     "SELECT 1 FROM pg_database WHERE datname='test_tunegocio'"],
    capture_output=True, text=True
)
if "1" not in r.stdout:
    run("CREATE DATABASE test_tunegocio OWNER tn_owner")
else:
    print("  DB test_tunegocio ya existe")

# 2. Habilitar PostGIS como superusuario
run("CREATE EXTENSION IF NOT EXISTS postgis", dbname="test_tunegocio")
run("CREATE EXTENSION IF NOT EXISTS postgis_topology", dbname="test_tunegocio")

# 3. Privilegios sobre el schema public
run("GRANT ALL ON SCHEMA public TO tn_owner", dbname="test_tunegocio")
run("GRANT ALL ON SCHEMA public TO tn_app", dbname="test_tunegocio")

# 4. tn_owner puede crear objetos y tiene privilegios totales
run("GRANT ALL PRIVILEGES ON DATABASE test_tunegocio TO tn_owner", dbname="test_tunegocio")
run("GRANT ALL PRIVILEGES ON DATABASE test_tunegocio TO tn_app", dbname="test_tunegocio")

# 5. tn_app puede acceder a futuras tablas
run("ALTER DEFAULT PRIVILEGES FOR ROLE tn_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tn_app", dbname="test_tunegocio")
run("ALTER DEFAULT PRIVILEGES FOR ROLE tn_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO tn_app", dbname="test_tunegocio")

print("\n=== Listo ===")
