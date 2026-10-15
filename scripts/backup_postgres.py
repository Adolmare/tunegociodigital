import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def postgres_environment(database_url):
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("MIGRATOR_DATABASE_URL debe ser una URL PostgreSQL válida.")
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
        raise ValueError("La URL migradora debe incluir usuario, clave y base de datos.")
    return result


def main():
    database_url = os.environ.get("MIGRATOR_DATABASE_URL")
    if not database_url:
        raise RuntimeError("MIGRATOR_DATABASE_URL no está configurada.")
    output_dir = Path(os.environ.get("BACKUP_DIR", "backups"))
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = output_dir / f"tunegocio-{timestamp}.dump"
    env = postgres_environment(database_url)
    subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            str(backup_path),
        ],
        env=env,
        check=True,
    )
    os.chmod(backup_path, 0o600)
    hasher = hashlib.sha256()
    with backup_path.open("rb") as backup:
        for chunk in iter(lambda: backup.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    checksum_path = backup_path.with_suffix(".sha256")
    checksum_path.write_text(f"{digest}  {backup_path.name}\n", encoding="ascii")
    os.chmod(checksum_path, 0o600)
    print(f"Backup creado: {backup_path}")
    print(f"SHA-256: {digest}")
    print("Copia el dump y su checksum a almacenamiento externo antes de terminar.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Falló el backup PostgreSQL: {exc}", file=sys.stderr)
        raise
