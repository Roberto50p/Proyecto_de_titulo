# Diseño MVP — Conciliación mensual Transbank · Bordero · Cartola (Hotel Plaza San Francisco)

Fecha: 2026-10-23 · Rama: `dev` · Equipo APT122: Roberto Bustos, Tomás Duhalde, Valentina Olivares.

## 1. Intención

El Depto. de Administración y Finanzas de Hotelera San Francisco S.A. concilia hoy a mano, en Excel, lo que el hotel registró, lo que Transbank liquidó y lo que llegó al banco. El producto final actual es una planilla mensual (`08_2026_CONCILIACIÓN BANCARIA HPSF.xlsx`): resumen de saldos, partidas pendientes con observación y "diferencial 0". El MVP automatiza esa conciliación para las ventas con tarjeta y deja **evidenciadas las discrepancias y los registros con fallas** en un PDF y un Excel bien estructurados, con **débito, crédito y prepago claramente diferenciados**. Debe estar listo para la beta (30–31/10/2026) y respaldarse con pruebas sobre datos reales.

Usuario: analista contable del hotel (uso mensual, en escritorio). Lectores del reporte: el analista (detalle) y jefatura de finanzas (resumen).

## 2. Objetivos

1. Conciliación **mensual** de tres fuentes, **cerrada por fecha de abono**:
   - **Bordero** (FrontOffice, "Cargos de Débitos y Créditos"): histórico de lo que registró el hotel.
   - **Transbank** "Abonos por día": débito, crédito y prepago (uno o más archivos por medio de pago).
   - **Cartola** Banco de Chile en pesos.
2. Detectar y clasificar fallas (sección 6) con un mensaje claro por registro: qué pasó y qué hacer.
3. Web Django + SQLite con login, asistente de carga, resultado navegable, historial y pendientes abiertos.
4. Reporte **PDF** y **Excel** con la estructura "opción C" (sección 8).
5. Pruebas automatizadas que reproduzcan los resultados conocidos de los datos reales (sección 10).

## 3. No objetivos (fuera del MVP)

- Conciliación en dólares, reportes por marca US$ y validación de tipo de cambio (API mindicador.cl). La pantalla antigua de dólares queda en `main`/historial git; el motor nuevo podrá extenderse después.
- Conciliación cartola vs **libro mayor** contable (es la planilla de agosto; solo se usa como referencia de formato).
- Conexión directa a Transbank, banco o FrontOffice (solo carga de archivos).
- Multiusuario con roles, multiempresa, despliegue en servidor.

## 4. Anti-objetivos (sería un fracaso aunque "funcione")

- Marcar como falla lo que es normal: diferencias de redondeo ≤ tolerancia, ventas de crédito abonadas días después, cuotas siguientes.
- Mezclar débito, crédito y prepago en un mismo bloque sin poder distinguirlos.
- Que el reporte requiera explicación: cada falla debe decir causa y acción.
- Perder un registro: todo lo leído termina conciliado, en falla, en aviso o en pendiente (los totales deben cuadrar).

## 5. Fuentes de datos (formatos reales observados)

Datos de prueba reales en `capstone-amor/referencia/datos de prueba 8 sept/` (fuera del repo): abono Transbank del **08-09-2026**, bordero 04–07/09/2026, cartola CLP al 08/09/2026.

### 5.1 Transbank "Abonos por día" (`.xlsx`, hoja `Abonos_por_día.xls`)
- Cabecera: fila 4 "Periodo de consulta" (texto "08 septiembre 2026"), "Día desde"/"Día hasta"; fila 9: empresa, RUT, **Cuenta corriente** ("BANCO DE CHILE 6211002"), **Moneda** ("Pesos"), **Medio de pago** ("Débito" | "Crédito" | "Prepago").
- Resumen (col 1 etiqueta, col 3 valor): Total ventas (+), Devoluciones (+), Comisión Transbank (−), IVA comisión (−), Ventas anuladas (−), Cobros por servicio (−) y su IVA, **Total abono**.
- Detalle con encabezado de 2 filas (grupo + subcolumna; buscar la fila que contiene "Monto original de venta"); 26 columnas: Fecha de venta (texto "07 septiembre 2026"), Tipo de movimiento, Código de comercio, Nombre local, Medio de pago, Monto original de venta, Monto vuelto, Tipo de venta/cuota, N° de cuota, Monto venta válido para abono, Comisión, IVA comisión, Total abono, campos de anulación y cobros, N° de tarjeta (enmascarado), **Código de autorización de venta** (texto, conserva ceros), Orden de pedido, Número único, ID de servicio, ID transacción (TID), N° de boleta.
- Locales: códigos de comercio 27941095 y 45695416 = Hotel; 47195679 = Restaurant Bristol.
- Crédito en cuotas: `C3C` con "1/3" (monto original 618.324; válido para abono 206.108) y "3/3" de una venta del 04/07/2026.
- **El tipo se detecta por el campo "Medio de pago" del archivo**, no por el nombre.
- **Fecha de abono** = día de "Periodo de consulta"/"Día desde". El detalle no trae fecha de abono por fila.

### 5.2 Bordero (`.xlsx`, FrontOffice v.5.01.95d)
- Encabezado repetido por página; "Periodo de: dd/mm/aaaa hasta dd/mm/aaaa" (se usa como **cobertura** del bordero).
- Columnas por posición: 0 Hab, 1 Tipo Hab, 2 Reserva, 3 Cuenta, 4 **Cod. Deb.**, 5 Descripción, 6 Factura, 8 **Valor**, 9 **Documento**, 10 Fecha (dd/mm/aaaa), 11 Hora, 12 Usuario, 13 Designación (nombre huésped).
- Filas válidas: Cod. Deb. no vacío, distinto de "Cod. Deb.", Valor numérico. Se excluyen "Total VHF/PDV/Total/Total General" y pies "FrontOffice … Página X de Y".
- Pagos con tarjeta = Valor negativo y Cod. Deb. en la tabla de equivalencias (sección 7.2). Documento numérico pierde ceros ("3098" vs Transbank "003098").

### 5.3 Cartola Banco de Chile CLP (`.xlsx`)
- Cabecera: Cuenta N° (00-000-62110-02), Moneda, saldos. Movimientos con encabezado en la fila que contiene "Fecha" y "Descripción": Fecha | Descripción | Canal o Sucursal | Nro. Docto. | Cargos (CLP) | Abonos (CLP) | Saldo (CLP); orden descendente.
- Abonos Transbank: descripción contiene "Transbank" o "Tbk" (patrones configurables). Ej. 08/09: "Abonos Realizados Por Transbank…" 861.527 (prepago) y 5.269.462 (débito); "Abono Comer. Tc Tbk…" 2.597.371 (crédito).

## 6. Clasificación de resultados

Cada registro Transbank (venta), registro de bordero (pago con tarjeta) y archivo Transbank (abono) termina en exactamente una categoría. Tipo: **Dato** (corregir en sistema del hotel), **Operación** (revisar con Transbank/banco), **Aviso** (no es falla), **Pendiente**.

| Código | Categoría | Regla | Tipo |
|---|---|---|---|
| OK | Conciliado | venta TBK ↔ pago bordero por código normalizado, \|monto original − \|Valor\|\| ≤ tolerancia | — |
| DIF_MONTO | Diferencia de monto | cruza por código, diferencia > tolerancia | Operación |
| DIGITACION | Error de digitación | sin cruce exacto; existe pago de bordero libre con misma fecha, mismo medio, \|dif\| ≤ tolerancia y similitud de código ≥ umbral | Dato |
| SIN_BORDERO | Venta Transbank sin registro en bordero | fecha de venta dentro de la cobertura del bordero y sin cruce exacto ni por digitación | Operación |
| FUERA_PERIODO | Fuera del período del bordero | fecha de venta fuera de la cobertura de los borderos cargados | Aviso |
| CUOTA | Cuota en seguimiento | venta con N° de cuota k/n; cuota 1 se concilia contra el bordero por monto original; cuotas k>1 se buscan en conciliaciones anteriores guardadas y, si no, quedan como aviso | Aviso |
| MEDIO_DISTINTO | Medio de pago distinto | cruza por código, pero el Cod. Deb. del bordero no corresponde al medio del archivo según la tabla de equivalencias | Aviso |
| SIN_ABONO | Pago en bordero aún no abonado | pago con tarjeta del bordero sin venta Transbank asociada al cierre | Pendiente |
| ABONO_CARTOLA | Abono no encontrado en cartola / con diferencia | Total abono del archivo sin línea Transbank en cartola con mismo día (o día hábil siguiente) y monto ± tolerancia | Operación |
| DATO_INVALIDO | Dato inválido | documento vacío, código basura, pago con monto positivo (reversa) | Dato |

Gravedad para ordenar: Operación > Dato > Pendiente > Aviso. Mensaje por registro con plantilla, p. ej. *"Código F0FUAZ de Transbank no existe en el bordero; el más parecido es 0FOFUAZ (06/09/2026, $106.999). Corregir documento en FrontOffice."*

## 7. Reglas de conciliación

### 7.1 Período (cierre por fecha de abono)
- La conciliación del mes M toma los archivos Transbank cuya **fecha de abono** cae en M.
- Las ventas asociadas pueden ser anteriores (crédito con desfase, cuotas): se buscan en **todos los borderos cargados** para esa conciliación; su cobertura es la unión de sus períodos.
- La cartola debe cubrir las fechas de abono.
- Al guardar, los registros SIN_ABONO del bordero quedan como **pendientes abiertos**. En conciliaciones posteriores, si aparece la venta Transbank correspondiente, el pendiente se cierra automáticamente (referencia a la conciliación que lo cerró). El analista puede además agregar observación y marcar un hallazgo como revisado.

### 7.2 Normalización y equivalencias
- Códigos/documentos: texto, sin espacios, mayúsculas, **sin ceros a la izquierda**; nunca convertir a entero.
- Fechas: Transbank texto en español ("07 septiembre 2026"), bordero/cartola dd/mm/aaaa.
- Montos: enteros CLP; bordero negativo para pagos → se compara valor absoluto.
- Tabla configurable Cod. Deb. → medio de pago (precarga): `RCO` Red Compra → Débito y Prepago; `V$` Visa, `MC$` MasterCard, `AME$` Amex, `D$` Diners → Crédito. No confirmada por el cliente: un desajuste es **aviso**.

### 7.3 Orden del cruce venta a venta
1. Exacto por código normalizado (cada pago del bordero se usa una sola vez; si hay varios candidatos, el de monto y fecha más cercanos).
2. Digitación: solo entre pendientes de ambos lados, misma fecha, monto en tolerancia, similitud (difflib ratio) ≥ umbral; mejor candidato.
3. Lo restante se clasifica según 6.
4. Abonos: cada archivo Transbank (Total abono) contra líneas Transbank de la cartola, 1 a 1, misma fecha de abono (o siguiente día hábil), monto ± tolerancia.

### 7.4 Parámetros (pantalla Parámetros, guardados en BD)
Tolerancia CLP (100), umbral de similitud de códigos (0,75), días de holgura cartola (1), patrones de descripción Transbank en cartola ("transbank", "tbk"), tabla Cod. Deb. → medio. Cada conciliación guarda una copia de los parámetros con que se ejecutó.

### 7.5 Cuadratura interna
Para cada medio de pago: Σ ventas Transbank = Σ por categoría; Total abono = ventas − comisión − IVA − anulaciones − cobros (validar contra el resumen del archivo; si no cuadra → DATO_INVALIDO a nivel archivo). Los totales del reporte deben cerrar en cero.

## 8. Reportes (opción C)

Colores fijos en web, PDF y Excel: **Débito azul, Crédito ámbar, Prepago verde**; además del color, cada bloque lleva el nombre del medio (no depender solo del color).

### 8.1 PDF (ReportLab)
1. **Portada/Resumen** (formato inspirado en la hoja "08.2026" del hotel): encabezado HOTELERA SAN FRANCISCO S.A., Depto. Adm. y Finanzas, RUT, "Conciliación Transbank — <Mes Año> · cierre por fecha de abono", cuenta bancaria, fecha de generación, usuario. Tabla por medio: Ventas Transbank | Comisión + IVA | Abono Transbank | Abono en cartola | Diferencial | N° ventas | Con falla; fila Total.
2. **Matriz** categoría × medio de pago (conteo y monto).
3. **Capítulo Débito**, **Capítulo Crédito** (incluye sección Cuotas), **Capítulo Prepago**: mini-resumen y tabla de fallas (fecha, código, local, monto TBK, monto bordero, diferencia, categoría, mensaje).
4. **Pendientes** (abiertos al cierre, incluidos los arrastrados).
5. **Parámetros** usados y archivos procesados (nombre, tipo detectado, filas, hash).
Pie con página X de Y.

### 8.2 Excel (openpyxl)
Hojas: `Resumen` (resumen + matriz) · `Débito` · `Crédito` · `Cuotas` · `Prepago` · `Pendientes` (con columnas Observación/Corregir como la hoja "PENDIENTE" del hotel) · `Conciliados` · `Parámetros`. Encabezados con filtro, paneles fijos, formato de miles CLP, color del medio en la pestaña y encabezado, una fila por registro con categoría y mensaje.

## 9. Aplicación web

- Login obligatorio (auth de Django; usuario creado por comando). Interfaz en español.
- Menú lateral: **Nueva conciliación** · **Conciliaciones** (historial) · **Pendientes abiertos** · **Parámetros**.
- Nueva conciliación (asistente): 1) Mes (año/mes) → 2) Archivos (bordero 1..n, cartola 1, Transbank 1..n; arrastrar o elegir) → 3) **Revisión de lectura**: por archivo, tipo detectado, período, filas, totales; errores bloqueantes (archivo ilegible, tipo desconocido, fecha de abono fuera del mes) y advertencias (bordero no cubre algunas ventas) → 4) Resultado.
- Resultado: indicadores (abonado, en cartola, diferencial, con falla), pestañas Resumen / Débito / Crédito / Prepago / Pendientes, filtros por categoría y local, descarga PDF y Excel, marcar revisado + observación.
- Estilo: claro, sobrio, contable; números con separador de miles y cifras tabulares; accesible (contraste 4.5:1, foco visible, etiquetas en formularios). Sin dependencias de CDN (recursos estáticos locales).

## 10. Pruebas (aceptación con datos reales del 08-09-2026)

Con los 5 archivos reales y parámetros por defecto, el resultado debe cumplir:
- Abonos: débito 5.269.462, crédito 2.597.371, prepago 861.527 encontrados en cartola 08/09 → diferencial 0 (ninguna ABONO_CARTOLA).
- Débito (90 ventas): 82 OK, 1 DIF_MONTO (código 007626: 115.204 vs 113.700), 3 DIGITACION (F0FUAZ→0FOFUAZ, LRJFAI→0LRJAI, 839049→836049), 4 SIN_BORDERO (537834, ANN3WM, 425788, 129728).
- Crédito (39): 2 CUOTA (659416 venta 03/09 cuota 1/3; 626135 venta 04/07 cuota 3/3, ambas fuera de la cobertura del bordero), 28 FUERA_PERIODO (resto de ventas del 03/09), 1 DIF_MONTO (819775: 129.140 vs 20.619), 1 DIGITACION (00543I), 3 SIN_BORDERO (227735, 234049, 853972), 4 OK.
- Prepago (12): 1 DIF_MONTO (823431: 9.800 vs 11.000), 1 DIGITACION (HCOVGZ→HC0VGZ); resto OK.
- Cuadratura: Σ por categoría = Σ ventas por medio.
(Las cifras exactas se fijan en el primer test verde y se documentan; si una regla cambia una cifra, se justifica.)
- Pruebas unitarias con DataFrames pequeños sintéticos para cada regla; pruebas de lectura y de integración con los archivos reales leídos desde una ruta configurable (variable de entorno `CONCILIACION_DATOS_PRUEBA`), omitidas si no existe. Los datos reales **no** se versionan (contienen nombres de huéspedes y tarjetas enmascaradas).
- Pruebas de reportes: el PDF se genera y contiene las secciones; el Excel tiene las hojas y los totales cuadran.

## 11. Arquitectura y decisiones técnicas

- Enfoque elegido (3): **pandas lee, limpia y cruza; resultados normalizados en SQLite**. Descartados: (1) todo en memoria — sin historial ni pendientes; (2) todo con ORM — cruce difuso y tolerancias incómodos y lentos.
- Django 5.2 LTS (compatible con Python 3.14 local), pandas, openpyxl, ReportLab (PDF sin dependencias de sistema en Windows).
- App nueva `conciliacion` con capas: `lectores/` (bordero, transbank, cartola + detección de tipo), `motor/` (normalización, cruce, clasificación, cuadratura), `reportes/` (pdf, excel), vistas/plantillas/estáticos propios.
- **Limpieza**: eliminar del proyecto el sistema de reservas heredado (modelos y migraciones de hotel, plantillas `basura/` y `admin/`, media de fotos/QR, vistas de QR/correo, i18n, `mydbengine`), la vista de dólares y el ETL anterior; credenciales SMTP y SECRET_KEY fuera del código (variables de entorno con valores de desarrollo). Se reescribe `requerimientos` en UTF-8.
- Modelo de datos (orientativo): Conciliacion(mes, estado, parámetros JSON, totales, creada_por/en) · ArchivoCargado(conciliación, tipo, medio, nombre, hash, período, filas, totales) · VentaTransbank · PagoBordero · AbonoTransbank · MovimientoCartola · Hallazgo(categoría, tipo, gravedad, mensaje, refs, revisado, observación) · Pendiente(pago bordero, abierto/cerrado, conciliación origen/cierre) · Parametro / EquivalenciaMedio.

## 12. Queda a criterio del constructor

Nombres exactos de modelos y campos, estructura interna de módulos, diseño visual concreto dentro de lo descrito en 9, textos de mensajes (siguiendo la plantilla), umbral exacto de similitud si con datos reales 0,75 produce falsos positivos (documentar), manejo de archivos subidos (guardar en `media/` ignorado por git).

## 13. Precisiones tras la revisión del constructor (decisiones propias, verificables)

1. **Identidad y deduplicación de pagos del bordero**: un pago de bordero se identifica por (Documento normalizado, Fecha, Hora, Valor, Cuenta, Cod. Deb.) y es **único en toda la base**, no por conciliación. Al cargar un bordero que repite días ya cargados, las filas existentes no se duplican. Un pago conciliado en un mes anterior **no vuelve a participar** del cruce ni puede ser SIN_ABONO.
2. **Pendientes como candidatos**: el universo de cruce del bordero = pagos sin conciliar de toda la base (cargados ahora o antes). Si una venta Transbank cruza con un pago que estaba como pendiente abierto, queda **OK** con nota "cierra pendiente de <mes>" y el pendiente se cierra. La cobertura (para FUERA_PERIODO) es la unión de los períodos de todos los borderos cargados históricamente.
3. **Restaurant Bristol**: sus ventas sí están en el bordero (RCO, V$, MC$); se concilian igual y el local es un filtro/columna, no una excepción.
4. **Precedencia de categorías** (se evalúa en este orden y gana la primera): DATO_INVALIDO → cruce exacto [DIF_MONTO si dif > tolerancia; si no, MEDIO_DISTINTO si el medio no calza; si no, OK (cuota k/n se anota como seguimiento)] → cruce por digitación (DIGITACION) → sin cruce: CUOTA si es cuota y su venta está fuera de la cobertura, FUERA_PERIODO si fuera de cobertura, SIN_BORDERO en otro caso. Cuota k>1 cuya venta se concilió en un mes anterior → OK con nota.
5. **Montos**: el cruce usa **Monto original de venta** (lo que registra el bordero; en cuotas, el total). Los totales "Ventas Transbank" del reporte y la cuadratura usan **Monto venta válido para abono** (coincide con "Total ventas (+)" del archivo). Cuadratura de archivo: Total abono = Total ventas + devoluciones − comisión − IVA − anulaciones − cobros − IVA cobros. Monto vuelto se informa pero no participa del cruce (todos 0 en los datos).
6. **Cifras de la sección 10**: son el objetivo; el test de integración las fija. Si una regla razonada produce otra cifra, el test se ajusta con comentario que la justifica (no se fuerzan reglas para calzar números).
7. **Movimientos que no son venta** (anulaciones, cobros por servicio): no cuentan como ventas; se listan en "Otros movimientos" del medio de pago y entran a la cuadratura del abono.
8. **Reprocesar un mes**: hay una conciliación por mes. Reprocesar pide confirmación, reemplaza la anterior (revierte los pendientes que abrió/cerró) y conserva las observaciones/marcas de revisado de hallazgos con la misma clave (categoría + código + fecha).
