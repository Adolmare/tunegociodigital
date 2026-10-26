# Acceso de empleados a un negocio

## Identificador y código del negocio

Cada negocio conserva su UUID como identificador técnico (`Tenant.id`) y expone un `join_code` alfanumérico corto para que el propietario pueda compartirlo con los cobradores. El código no otorga acceso por sí solo.

## Flujo de solicitud

1. El empleado crea su usuario mediante el registro normal y obtiene sesión mediante login.
2. Envía el código a `POST /api/v1/tenant-join-requests/` con `{"join_code":"CODIGO" }`.
3. La API valida que el negocio exista y esté activo o en prueba, y crea una solicitud pendiente.
4. El propietario usa el encabezado `X-Tenant-ID` y consulta `GET /api/v1/tenant-join-requests/manage/`.
5. El propietario responde a `POST /api/v1/tenant-join-requests/manage/` con `{"request_id":"UUID","decision":"accept"}` o `decision: "reject"`.
6. Solo al aceptar se crea/activa la membresía con rol `employee` y se crea o reactiva el perfil de empleado/cobrador.

Las solicitudes se guardan con el tenant explícito, una restricción que evita dos solicitudes pendientes simultáneas del mismo usuario para el mismo negocio, y una política PostgreSQL RLS. La revisión se limita al negocio indicado por el encabezado y al rol propietario.

## Interfaz y validación

El portal de préstamos incorpora registro de cuenta con código de negocio, una pantalla para enviar solicitudes pendientes y una bandeja para que el propietario las acepte o rechace. Aun así, hay que validar el flujo completo en el navegador y contra PostgreSQL/PostGIS antes de producción. El empleado no puede elegir su rol ni marcarse a sí mismo como aceptado.
