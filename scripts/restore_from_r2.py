import hashlib
import os
import subprocess
import sys
import tempfile
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


def get_r2_client():
    account_id = os.environ.get("R2_ACCOUNT_ID", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    bucket_name = os.environ.get("R2_BUCKET_NAME", "").strip()
    if not all([account_id, access_key, secret_key, bucket_name]):
        raise RuntimeError(
            "Define R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY y R2_BUCKET_NAME."
        )
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    return client, bucket_name


def find_latest_backup_key(s3_client, bucket_name: str) -> str:
    explicit_key = os.environ.get("BACKUP_KEY", "").strip()
    if explicit_key:
        return explicit_key

    response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix="backups/tunegocio-")
    contents = response.get("Contents") or []
    dumps = [obj["Key"] for obj in contents if obj["Key"].endswith(".dump")]
    if not dumps:
        raise RuntimeError(f"No se encontraron respaldos .dump en s3://{bucket_name}/backups/")
    dumps.sort()
    return dumps[-1]


def verify_sha256(dump_path: Path, sha256_path: Path):
    expected = sha256_path.read_text(encoding="ascii").strip().split()[0]
    hasher = hashlib.sha256()
    with dump_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    actual = hasher.hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"Checksum SHA-256 inválido: esperado {expected}, calculado {actual}."
        )


def main():
    database_url = os.environ.get("MIGRATOR_DATABASE_URL")
    if not database_url:
        raise RuntimeError("Define MIGRATOR_DATABASE_URL para restaurar la base de datos.")

    s3_client, bucket_name = get_r2_client()
    backup_key = find_latest_backup_key(s3_client, bucket_name)
    checksum_key = backup_key[:-5] + ".sha256"

    env = postgres_environment(database_url)
    database_name = env["PGDATABASE"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        local_dump = tmp_path / Path(backup_key).name
        local_sha = tmp_path / Path(checksum_key).name

        print(f"Descargando {backup_key} desde Cloudflare R2 ({bucket_name})...")
        s3_client.download_file(bucket_name, backup_key, str(local_dump))
        try:
            s3_client.download_file(bucket_name, checksum_key, str(local_sha))
            verify_sha256(local_dump, local_sha)
            print("Checksum SHA-256 verificado correctamente.")
        except Exception as exc:
            print(f"Aviso de verificación SHA-256: {exc}")

        print(f"Restaurando en base de datos '{database_name}'...")
        subprocess.run(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                "--dbname",
                database_name,
                str(local_dump),
            ],
            env=env,
            check=True,
        )

    if os.environ.get("APP_DB_PASSWORD"):
        from provision_app_role import main as provision_role

        provision_role()

    print(f"Base de datos restaurada exitosamente desde s3://{bucket_name}/{backup_key}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Falló la restauración desde Cloudflare R2: {exc}", file=sys.stderr)
        raise
