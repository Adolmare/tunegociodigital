# Flujo de caja y resumen de cartera

Este documento describe los endpoints iniciales del flujo de caja del módulo `loans`.

Todos los endpoints requieren JWT y el encabezado `X-Tenant-ID`. El tenant se valida mediante una membresía activa; los modelos nuevos son tenant-owned y tienen Row-Level Security (RLS) en PostgreSQL.

## Endpoints

| Método | Ruta | Uso |
|---|---|---|
| GET, POST | `/api/v1/collector-daily-cash/` | Consultar o registrar el dinero inicial diario de un cobrador. |
| GET, POST | `/api/v1/collector-expenses/` | Consultar o registrar gastos con categoría, descripción, fecha y monto. |
| GET | `/api/v1/collector-cash-summary/?period=day&date=YYYY-MM-DD` | Cierre diario por cobrador. |
| GET | `/api/v1/collector-cash-summary/?period=week&date=YYYY-MM-DD` | Resumen de la semana que contiene la fecha. |
| GET | `/api/v1/collector-cash-summary/?period=month&date=YYYY-MM-DD` | Resumen del mes que contiene la fecha. |
| GET | `/api/v1/customer-loan-summary/?search=nombre&start=YYYY-MM-DD&end=YYYY-MM-DD` | Agrupar préstamos por cliente y buscar por nombre. |

Los empleados solo pueden consultar y registrar sus propios movimientos. Los roles de dirección pueden consultar los cobradores del negocio activo. El backend determina el tenant desde la membresía y no acepta un tenant enviado en el cuerpo para asignar movimientos.

## Fórmula de caja

Para cada cobrador y período:

`saldo_esperado = dinero_inicial + recogido - gastos - capital_prestado + papeleria`

- **Dinero inicial:** suma de los registros de caja diaria dentro del período.
- **Recogido:** pagos registrados en el período, netos de reversas.
- **Gastos:** suma de los gastos del cobrador en el período.
- **Capital prestado:** capital de los préstamos asignados al cobrador y cuya fecha de inicio está dentro del período.
- **Papelería:** suma de `Loan.paperwork_fee` de esos préstamos; no se agrega una segunda vez desde los pagos.

La fórmula informa un saldo esperado de caja según los movimientos registrados. No es una medida contable de utilidad neta: la rentabilidad debe analizar capital recuperado, intereses, saldos y costos por separado.

## Resumen por cliente

El endpoint agrupa en una sola fila todos los préstamos de cada cliente. Las sumas de pagos se consultan por préstamo en una agregación separada, evitando que los joins de cuotas o pagos multipliquen el capital o la papelería. Cada fila conserva un arreglo `loans` con el detalle individual para abrir el perfil y revisar sus fechas, frecuencia, valores y saldos.

## Pendiente antes de producción

- Ejecutar las migraciones y toda la suite de pruebas contra PostgreSQL/PostGIS.
- Añadir pruebas de regresión de RLS para ambos modelos nuevos y para el resumen por cliente.
- Conectar estos endpoints a la interfaz del portal; el registro de datos en API no implica que los formularios ya estén visibles en el frontend.
- Implementar el flujo separado de solicitud de acceso de empleado, aprobación del propietario y panel visual del cobrador.
