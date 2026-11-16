# Conciliación sin mes ni año + protección contra archivos ya conciliados — Diseño

## Por qué

Se entendió mal un requerimiento: las conciliaciones se crearon "por mes de abono", pero los usuarios deben poder
conciliar día a día (o cuando quieran) para hacer seguimiento. Hoy la app obliga a elegir mes y año antes de subir
archivos, rechaza archivos Transbank de otro mes y nombra los reportes `conciliacion_AAAA_MM`. Por ordenanza, lo
único que debe llevar fecha es el reporte descargado (evitar redundancia).

Al quitar el mes desaparece la única barrera que impedía volver a conciliar archivos ya conciliados. Si un usuario
sube en una conciliación nueva los mismos Transbank de otra, el motor no encuentra los pagos del bordero (ya usados)
y llena el reporte de anomalías falsas ("Sin registro en bordero"), además de duplicar los abonos.

## Objetivos

1. "Nueva conciliación" no pide fecha: crea la conciliación y lleva directo a subir archivos (3 pasos: Archivos →
   Revisión → Resultado).
2. Se pueden crear todas las conciliaciones que se quiera; ya no existe "una por mes".
3. Cada conciliación se identifica como **"Conciliación N° {id}"**, sin fecha.
4. Los reportes se descargan como `conciliacion_DD-MM-AAAA.xlsx` / `.pdf` con la **fecha de generación** (guiones
   porque `/` no es válido en nombres de archivo).
5. Detección de archivos Transbank ya conciliados en **otra** conciliación:
   - mismo archivo (SHA-256), o
   - mismo medio de pago y mismo día de abono, o
   - ventas repetidas por **código de autorización + medio + N° de cuota + fecha y monto de la venta** (las cuotas
     comparten código, y los códigos de autorización se repiten con el tiempo).
   - Solo cuentan conciliaciones **procesadas**: un borrador abandonado no bloquea (gana la que se procesa primero).
6. Ante un duplicado: se **bloquea** el procesamiento y se muestra el **enlace** a la conciliación donde ya está, y
   además un botón **"Reemplazar"** que quita el archivo de la conciliación anterior (esta vuelve a borrador con sus
   observaciones conservadas) y deja el nuevo. El usuario elige.

## No objetivos

- No se cambia el motor de cruce (`motor/cruce.py`, `motor/abonos.py`) ni los lectores: su lógica es correcta.
- No se toca `web/templates` (app antigua de dólares; no pide mes ni año).
- Bordero y cartola **no** se marcan como duplicados: el bordero ya no se duplica en la base y la cartola mensual
  se reutiliza legítimamente en varias conciliaciones diarias.

## Anti-objetivos

- Que un reporte ya emitido cambie en silencio (por eso "Reemplazar" es explícito y avisa qué conciliación volvió a
  borrador).
- Que al subir la cuota 2/3 se borre o bloquee la cuota 1/3.

## Decisiones

- Usuario: sin mes/año; solo el reporte lleva fecha (de generación); bloquear + enlace + botón Reemplazar.
- Claude (decisiones propias, revisables):
  - Etiqueta "Conciliación N° {id}"; orden de la lista: más reciente primero.
  - Pendientes "abiertos al cierre" y "cerrados en esta conciliación" se ordenan por N° de conciliación en vez de
    por mes (misma regla, otra referencia).
  - "Abonos en cartola sin archivo Transbank": solo los de los días de abono de los archivos cargados (sin holgura:
    el día siguiente es de la próxima conciliación) y sin las líneas que ya calzaron en otra conciliación (la cartola
    mensual se reutiliza).
  - "Nueva conciliación" es un POST; si ya existe un borrador vacío que nunca se procesó, se reutiliza en vez de
    crear otro.
  - El reemplazo trabaja por archivo completo (quita el archivo anterior entero), porque los totales de abono de la
    conciliación anterior vienen del archivo; quitar ventas sueltas la descuadraría.
  - Textos: "próximo mes" → "próxima conciliación", "Cerrados este mes" → "Cerrados en esta conciliación",
    "Mes de origen" → "Conciliación de origen".
