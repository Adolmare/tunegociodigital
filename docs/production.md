# Producción en Render

No uses `docker-compose.yml` en producción: contiene credenciales locales de
desarrollo. `render.yaml` despliega la aplicación. Antes del primer deploy, crea la base
PostgreSQL gestionada y proporciona las variables marcadas como manuales.

## Qué ejecuta el despliegue

`render.yaml` define un web service Docker de plan Starter. La imagen instala
GDAL/GEOS para GeoDjango, recopila los estáticos con WhiteNoise y ejecuta
Uvicorn sobre `config.asgi:application`. El proceso ASGI sirve el stream SSE
de cobros sin reservar un worker síncrono durante toda la conexión.

El pre-deploy command aplica las migraciones con `MIGRATOR_DATABASE_URL`.
Configura el servicio para desplegar después de que pase el workflow de GitHub
Actions (`.github/workflows/tests.yml`). El endpoint `/health/` verifica que la
aplicación puede consultar su base de datos.

## Base PostgreSQL/PostGIS y RLS

1. Crea una base Render PostgreSQL en un plan que incluya los backups que
   necesita la empresa. Selecciona una versión compatible con la imagen
   `postgis/postgis:16-3.5` usada en CI.
2. Configura la conexión de propietario como `MIGRATOR_DATABASE_URL`.
   No uses ese usuario para atender peticiones. El usuario de esta conexión
   necesita permiso `CREATEROLE` y autoridad para administrar `tn_app`; si el
   rol ya existe, debe tener membresía con `ADMIN OPTION`. Si el proveedor no
   permite esos privilegios, aprovisiona `tn_app` por el mecanismo
   administrativo del proveedor antes del deploy.
3. Genera una contraseña aleatoria para el rol de aplicación. Usa la misma
   contraseña en `APP_DB_PASSWORD` y en la URL `DATABASE_URL`, con usuario
   `tn_app`. Render ejecuta `scripts/provision_app_role.py` antes de las
   migraciones en cada deploy; el script es idempotente, crea/actualiza
   `tn_app` como `NOSUPERUSER NOBYPASSRLS` y otorga permisos de datos y
   privilegios por defecto para futuras migraciones.
   Si necesitas aprovisionar el rol manualmente, ejecuta:

   ```powershell
   $env:MIGRATOR_DATABASE_URL = "<URL del propietario>"
   $env:APP_DB_PASSWORD = "<contraseña aleatoria nueva>"
   .\.venv\Scripts\python.exe scripts\provision_app_role.py
   ```

4. Configura `DATABASE_URL` con la URL del mismo servidor/base, pero con el
   usuario `tn_app` y la contraseña recién generada. `MIGRATOR_DATABASE_URL`
   debe usar el usuario propietario y solo se usa para desplegar/migrar.
5. La migración de clientes habilita `postgis` y crea la columna de punto GPS.

No configures el mismo rol propietario en `DATABASE_URL`: hacerlo permitiría
que el propietario de las tablas ignore las políticas RLS.

## Documentos en Cloudflare R2

Los documentos usan el storage S3-compatible de R2 con URLs firmadas; no se
sirven desde el disco efímero de Render.

1. Crea un bucket privado en Cloudflare R2.
2. Crea una API token limitada a lectura/escritura de objetos de ese bucket.
   Usa el Access Key ID y Secret Access Key de esa token, no una Global API Key.
3. Configura `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` y
   `R2_BUCKET_NAME` en Render. El servicio se negará a arrancar si falta alguno.
4. No hagas público el bucket ni habilites dominios públicos: el backend genera
   URLs firmadas para acceder a los archivos.

## Variables del servicio

Render genera `SECRET_KEY` con `generateValue`. El servicio requiere además
`DATABASE_URL`, `MIGRATOR_DATABASE_URL` y `CSRF_TRUSTED_ORIGINS`. El hostname
`*.onrender.com` se añade automáticamente a `ALLOWED_HOSTS` y a los orígenes
CSRF confiables. Añade los dominios personalizados a `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS` y, si corresponde, `CORS_ALLOWED_ORIGINS`.

Para correo, configura en Render las variables `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL` y
`DEFAULT_FROM_EMAIL` para el proveedor SMTP elegido. No pongas claves ni URL
con contraseñas en Git.

La configuración activa HTTPS redirigido detrás del proxy TLS de Render, HSTS,
cookies seguras, CSRF y encabezados de seguridad. Si se mueve el servicio fuera
de Render, revisa `SECURE_PROXY_SSL_HEADER` para que solo confíe en el proxy
real que elimina encabezados de cliente no confiables.
HSTS para subdominios y preload quedan desactivados por defecto; actívalos con
`SECURE_HSTS_INCLUDE_SUBDOMAINS=true` y `SECURE_HSTS_PRELOAD=true` solo cuando
el dominio personalizado y todos sus subdominios estén permanentemente en HTTPS.

## Stream de cobros

El comando de imagen usa Uvicorn/ASGI y dos workers por defecto; se puede ajustar
con `WEB_CONCURRENCY`. El heartbeat SSE se envía cada 15 segundos. No reemplaces
el arranque por un servidor WSGI para este endpoint: WSGI no puede mantener
correctamente el iterador asíncrono.

El stream exige un JWT Bearer y `X-Tenant-ID`. La API nativa `EventSource` del
navegador no permite establecer esos encabezados; el cliente debe consumir
`fetch()` como stream o implementar una estrategia autenticada equivalente.

## Backups y prueba de restauración

- Activa en Render los backups automáticos/PITR que permita el plan contratado.
- Como política inicial, conserva un respaldo diario durante 30 días y genera
  otro antes de cada despliegue que cambie el esquema. Guarda copias cifradas
  fuera de Render; los archivos del contenedor no son almacenamiento durable.
- Genera un dump custom con `MIGRATOR_DATABASE_URL`:

  ```powershell
  $env:MIGRATOR_DATABASE_URL = "<URL del propietario>"
  $env:BACKUP_DIR = ".\backups"
  .\.venv\Scripts\python.exe scripts\backup_postgres.py
  ```

- Para probar un dump, crea una base vacía temporal llamada
  `restore_check_<fecha>` con un usuario propietario que pueda crear PostGIS.
  Define `RESTORE_DATABASE_URL` para esa base y `BACKUP_FILE` para el dump, y
  ejecuta `scripts/restore_check_postgres.py`. El script rechaza nombres de
  base fuera del prefijo de prueba, rechaza una base que ya tenga Django y
  verifica la extensión PostGIS, la migración GPS y la tabla de clientes.
- Registra fecha, checksum, duración y resultado de la restauración; elimina
  la base temporal de prueba al terminar. Usa herramientas `pg_dump` /
  `pg_restore` compatibles con la versión principal del servidor. La imagen
  Docker incluye `postgresql-client` para esos comandos.

## Operación y observabilidad

La aplicación escribe logs de Django a stdout/stderr para consultarlos desde
Render. Configura alertas en Render para fallos de despliegue, reinicios,
errores HTTP y uso de recursos; `/health/` puede usarse también desde un
monitor externo. Antes de producción, valida una copia de restauración y el
flujo completo de login, admin, GPS y cobro en el servicio desplegado.
