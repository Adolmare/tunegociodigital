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


def upload_to_r2(backup_file: Path, checksum_file: Path):
    account_id = os.environ.get("R2_ACCOUNT_ID", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    bucket_name = os.environ.get("R2_BUCKET_NAME", "").strip()
    if not all([account_id, access_key, secret_key, bucket_name]):
        return False

    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    for file_path in (backup_file, checksum_file):
        key = f"backups/{file_path.name}"
        s3.upload_file(str(file_path), bucket_name, key)
        print(f"Subido a Cloudflare R2: s3://{bucket_name}/{key}")
    return True


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
    if upload_to_r2(backup_path, checksum_path):
        print("Backup sincronizado exitosamente en Cloudflare R2.")
    else:
        print("Copia el dump y su checksum a almacenamiento externo (o configura R2_*) antes de terminar.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Falló el backup PostgreSQL: {exc}", file=sys.stderr)
        raise
