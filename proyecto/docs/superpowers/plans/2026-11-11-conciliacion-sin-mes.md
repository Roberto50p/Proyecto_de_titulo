# Conciliación sin mes ni año + protección de archivos ya conciliados — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la conciliación no pida mes ni año (se puede conciliar día a día), que solo el reporte descargado lleve fecha (de generación), y que el sistema detecte archivos Transbank ya conciliados en otra conciliación ofreciendo "ver enlace" o "Reemplazar".

**Architecture:** Se quitan `anio`/`mes` de `Conciliacion` (migración 0006) y la identidad pasa a ser su N° (`pk`). Lo que dependía del mes (validación de fecha de abono, pendientes al cierre, cartola sin archivo) se reemplaza por orden de N° o por los días de abono cargados. La detección de duplicados vive en `servicio.py` (`conflictos`, `reemplazar`) y se integra en `validar()` y en la vista/plantilla de archivos. El motor (`motor/cruce.py`, `motor/abonos.py`) y los lectores no cambian.

**Tech Stack:** Python 3.14, Django 5.2, pandas, openpyxl, ReportLab, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-11-11-conciliacion-sin-mes-design.md`

## Global Constraints

- Todo dentro de `proyecto/`. Comandos de prueba desde `proyecto/`: `.venv\Scripts\python -m pytest`.
- Interfaz y mensajes en español.
- **No hacer commits sin autorización del usuario.** Los pasos "Commit" son puntos de control: se ejecutan solo si el usuario lo aprobó.
- No tocar `motor/cruce.py`, `motor/abonos.py`, `lectores/*` ni `web/`.
- Etiqueta exacta: `Conciliación N° {pk}`.
- Nombre de reportes: `conciliacion_DD-MM-AAAA.xlsx` / `.pdf` con `timezone.localdate()` (fecha de generación).
- Clave de venta para duplicados: `(medio, codigo_norm, cuota_num or 0)`; ventas sin `codigo_norm` no participan.
- Solo archivos Transbank utilizables (sin error y en pesos) participan en la detección; bordero y cartola nunca.
- Textos: "próximo mes" → "próxima conciliación"; "Cerrados este mes" → "Cerrados en esta conciliación"; "Mes de origen" → "Conciliación de origen"; "No hay ventas con falla este mes." → "No hay ventas con falla en esta conciliación."

## Review Focus

1. Cuota 2/3 de una venta cuya cuota 1/3 se concilió en otra conciliación → no es duplicado y se sigue conciliando como hoy (Task 4).
2. La misma cartola mensual (o el mismo bordero) subida en dos conciliaciones diarias → no bloquea (Task 4).
3. "Reemplazar" sobre una conciliación anterior ya procesada → esa conciliación vuelve a borrador, conserva observaciones y el mensaje la nombra con enlace (Task 5).
4. Archivo Transbank con error o en dólares en otra conciliación → no cuenta como duplicado (Task 4).
5. Pulsar "Nueva conciliación" varias veces seguidas → no se acumulan borradores vacíos (Task 3).

---

### Task 1: Modelo sin mes ni año

**Files:**
- Modify: `conciliacion/models.py` (`Conciliacion`, quitar constante `MESES` si nadie más la usa)
- Create: `conciliacion/migrations/0006_conciliacion_sin_mes.py` (con `makemigrations`)
- Modify: `conciliacion/admin.py` (si filtra u ordena por `anio`/`mes`)
- Modify: `conciliacion/tests/conftest.py` (`_crear` y `crear_conciliacion` sin `anio`/`mes`)
- Test: `conciliacion/tests/test_base.py`

**Interfaces:**
- Produces: `Conciliacion` sin `anio`/`mes`, `Meta.ordering = ["-id"]`, sin `unique_together`; `Conciliacion.etiqueta -> str` = `f"Conciliación N° {self.pk}"`. Fixture `crear_conciliacion(nombres=ARCHIVOS_SEPTIEMBRE)`.

- [ ] **Step 1: Write the failing test** en `test_base.py`

```python
def test_conciliaciones_sin_mes_se_pueden_repetir(db):
    a = Conciliacion.objects.create()
    b = Conciliacion.objects.create()
    assert a.etiqueta == f"Conciliación N° {a.pk}"
    assert list(Conciliacion.objects.all()) == [b, a]
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest conciliacion/tests/test_base.py -k sin_mes` → FAIL (`anio` NOT NULL).
- [ ] **Step 3: Implement** los cambios del modelo y `makemigrations conciliacion -n conciliacion_sin_mes`. Actualizar `conftest._crear(carpeta, nombres)` y `crear_conciliacion(nombres=ARCHIVOS_SEPTIEMBRE)`; reemplazar en todos los tests las llamadas `crear_conciliacion(2026, 8, [...])` → `crear_conciliacion([...])` y `Conciliacion.objects.create(anio=..., mes=...)` → `Conciliacion.objects.create()`.
- [ ] **Step 4: Run** el test → PASS. Los tests de vistas y servicio que dependen del mes se arreglan en Tasks 2 y 3.
- [ ] **Step 5: Commit** (solo con autorización): `Quito mes y año de la conciliación`

### Task 2: Servicio y reportes sin mes

**Files:**
- Modify: `conciliacion/servicio.py` (`validar`, `cartola_sin_archivo`)
- Modify: `conciliacion/reportes/datos.py` (`pendientes_abiertos_al_cierre`)
- Modify: `conciliacion/motor/mensajes.py` (texto `SIN_ABONO`), `conciliacion/reportes/excel.py`, `conciliacion/reportes/pdf.py` (textos de Global Constraints)
- Test: `conciliacion/tests/test_servicio.py`, `conciliacion/tests/test_vistas_asistente.py`

**Interfaces:**
- Consumes: `Conciliacion.etiqueta` (Task 1).
- Produces: `validar(conc)` sin la regla "fecha de abono no pertenece a..."; `cartola_sin_archivo(conc) -> list[MovimientoCartola]` filtrado a `[min(fecha_abono), sumar_dias_habiles(max(fecha_abono), dias_holgura)]` de los Transbank utilizables (lista vacía si no hay Transbank); `pendientes_abiertos_al_cierre(conc)` con `origen_id <= conc.id` y `(abierto | cierre_id > conc.id)`.

- [ ] **Step 1: Write the failing tests**
  - `test_vistas_asistente.py`: reemplazar `test_abono_fuera_del_mes` por `test_acepta_abono_de_cualquier_fecha`: conciliación con `ARCHIVOS_SEPTIEMBRE` → `servicio.validar(conc) == []`.
  - `test_servicio.py`: renombrar `test_pendiente_se_cierra_mes_siguiente` → `test_pendiente_se_cierra_en_la_conciliacion_siguiente`, con la nota esperada `f"cierra pendiente de {agosto.etiqueta}"`. Renombrar `test_reporte_de_un_mes_no_cambia_al_procesar_el_siguiente` → `..._de_una_conciliacion_...` (mismos 227).
  - `test_abonos_de_cartola_sin_archivo`: todas las líneas devueltas tienen `date(2026, 9, 8) <= fecha <= date(2026, 9, 9)`. Ejecutar una vez, anotar `n` y `monto` nuevos y fijarlos en el assert (reemplazan 16 / 26.036.232, que eran del mes completo).
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest conciliacion/tests/test_servicio.py conciliacion/tests/test_vistas_asistente.py -k "cualquier_fecha or pendiente or cartola"` → FAIL.
- [ ] **Step 3: Implement** los cambios de Interfaces y los textos de Global Constraints.
- [ ] **Step 4: Run** los mismos tests → PASS.
- [ ] **Step 5: Commit** (solo con autorización): `Servicio y reportes sin depender del mes`

### Task 3: Vistas, nombre de reportes y plantillas sin mes

**Files:**
- Modify: `conciliacion/views.py` (`PASOS`, `nueva`, `descargar_pdf`, `descargar_excel`, mensajes con `etiqueta`)
- Modify: `conciliacion/forms.py` (borrar `MesForm`)
- Delete: `conciliacion/templates/conciliacion/nueva_mes.html`
- Modify: `conciliacion/templates/conciliacion/lista.html`, `resultado.html`, `nueva_archivos.html`, `nueva_revision.html`, `pendientes.html`
- Test: `conciliacion/tests/test_vistas_asistente.py`, `conciliacion/tests/test_modificar.py`, `conciliacion/tests/test_vistas_gestion.py`

**Interfaces:**
- Consumes: Task 1 y Task 2.
- Produces: `PASOS = ["Archivos", "Revisión de lectura", "Resultado"]` (los `_pasos(n)` de las vistas bajan en 1); `nueva` con `@login_required @require_POST`: reutiliza la última conciliación en `BORRADOR` sin archivos o crea una con `creada_por=request.user`, y redirige a `archivos`; `_nombre_reporte(extension: str) -> str` = `f"conciliacion_{timezone.localdate():%d-%m-%Y}.{extension}"`.

- [ ] **Step 1: Write the failing tests** en `test_vistas_asistente.py`
  - Helper `nueva(cliente)` → `cliente.post(reverse("conciliacion:nueva"))`; en `test_flujo_completo`, `conc = Conciliacion.objects.get()`, y el assert del Excel pasa a `f"conciliacion_{timezone.localdate():%d-%m-%Y}.xlsx"`; agregar el mismo assert para `.pdf`.
  - `test_nueva_dos_veces_no_crea_borradores_vacios`: dos POST → `Conciliacion.objects.count() == 1`.
  - `test_lista_no_pide_mes`: GET `lista` → el HTML no contiene `Mes de abono` y contiene un `<form method="post" action="{% url 'conciliacion:nueva' %}">`.
  - Borrar `test_mes_existente_pide_confirmacion`. En `test_modificar.py`, la fixture `septiembre` hace POST sin datos.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest conciliacion/tests/test_vistas_asistente.py conciliacion/tests/test_modificar.py` → FAIL.
- [ ] **Step 3: Implement** las vistas y las plantillas:
  - `lista.html`: botón "Nueva conciliación" como form POST; la columna "Mes de abono" pasa a "Conciliación" (con `c.etiqueta`); textos de ayuda sin "mes".
  - `resultado.html`: `<h1>{{ conc.etiqueta }}</h1>` (sin "Conciliación" repetido) y los textos de Global Constraints.
  - `nueva_archivos.html` y `nueva_revision.html`: quitar "de este mismo mes".
  - `pendientes.html`: "Conciliación de origen".
- [ ] **Step 4: Run** la suite completa `.venv\Scripts\python -m pytest` → PASS.
- [ ] **Step 5: Commit** (solo con autorización): `Conciliación sin mes en vistas y reportes con fecha de generación`

### Task 4: Detección de archivos ya conciliados (servicio)

**Files:**
- Modify: `conciliacion/servicio.py` (nuevas `conflictos`, `reemplazar`; `validar` las usa)
- Test: `conciliacion/tests/test_duplicados.py` (nuevo)

**Interfaces:**
- Consumes: `utilizables`, `quitar_archivo`, `leer_transbank` (ya existen).
- Produces:
  - `conflictos(conc: Conciliacion) -> dict[int, list[ArchivoCargado]]`: para cada Transbank utilizable de `conc` (clave: su id), los Transbank utilizables de **otras** conciliaciones que (a) tienen el mismo `sha256`, o (b) comparten un medio de `por_medio` y la misma `fecha_abono`, o (c) son el `archivo` de una `VentaTransbank` con `es_venta=True` de otra conciliación con la misma clave `(medio, codigo_norm, cuota_num or 0)`. Sin repetidos y ordenados por `conciliacion_id`. Solo se incluyen los archivos con al menos un conflicto.
  - `reemplazar(ac: ArchivoCargado) -> list[Conciliacion]`: `@transaction.atomic`; aplica `quitar_archivo` a cada archivo de `conflictos(ac.conciliacion)[ac.id]` y devuelve las conciliaciones afectadas (sin repetir).
  - `validar(conc)` agrega por cada conflicto: `f"{a.nombre}: ya se concilió en {otro.conciliacion.etiqueta} ({otro.nombre})."`

- [ ] **Step 1: Write the failing tests** en `test_duplicados.py` (con `crear_conciliacion` y `servicio.procesar`)
  - `test_mismos_transbank_en_otra_conciliacion_bloquean`: A = septiembre procesada; B = `crear_conciliacion()` → `conflictos(B)` tiene 3 entradas (débito, crédito, prepago), cada una apunta a un archivo de A; `validar(B)` contiene `"ya se concilió en Conciliación N° {A.pk}"`.
  - `test_cartola_y_bordero_repetidos_no_bloquean`: A procesada; B = `crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx", "cartola.xlsx"])` → `conflictos(B) == {}`.
  - `test_venta_repetida_por_codigo`: A con una `VentaTransbank` creada a mano (archivo Transbank de A con otra `fecha_abono`) con el `medio`/`codigo_norm`/`cuota_num` de la primera venta leída de `CREDITOS TBK 08-09.xlsx`; B con ese archivo → `conflictos(B)` lo incluye.
  - `test_otra_cuota_no_es_duplicado`: igual que el anterior pero con `cuota_num` distinto → `conflictos(B) == {}`.
  - `test_transbank_con_error_en_otra_conciliacion_no_cuenta`: el archivo de A con `error="x"` → `conflictos(B) == {}`.
  - `test_reemplazar_quita_de_la_anterior`: A procesada con una observación en una venta; B con los mismos Transbank → `reemplazar(ac_debito_de_B)` devuelve `[A]`, A queda en `BORRADOR` sin ese archivo y `A.observaciones` conserva la observación; `servicio.procesar(B)` deja ventas `OK` en débito (no `SIN_BORDERO`).
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest conciliacion/tests/test_duplicados.py` → FAIL (`conflictos` no existe).
- [ ] **Step 3: Implement** `conflictos`, `reemplazar` y la línea en `validar`. Para (c), leer las ventas de cada archivo con `leer_transbank(ac.archivo.path).ventas`, filtrar `tipo_movimiento.lower() == "venta"` con `codigo_norm` no vacío, y hacer una sola consulta `VentaTransbank.objects.exclude(conciliacion=conc).filter(es_venta=True, codigo_norm__in=...)` con `select_related("archivo__conciliacion")`.
- [ ] **Step 4: Run** `test_duplicados.py` y después la suite completa → PASS.
- [ ] **Step 5: Commit** (solo con autorización): `Detecto Transbank ya conciliados en otra conciliación`

### Task 5: Duplicados en pantalla: enlace + botón Reemplazar

**Files:**
- Modify: `conciliacion/views.py` (`archivos`: acción POST `reemplazar`; `archivos` y `revision` pasan `conflictos` al contexto)
- Modify: `conciliacion/templates/conciliacion/nueva_archivos.html`, `nueva_revision.html`
- Modify: `conciliacion/templatetags/conciliacion_extras.py` (filtro `get_item` si la plantilla lo necesita para leer el dict por id)
- Test: `conciliacion/tests/test_duplicados.py`

**Interfaces:**
- Consumes: `servicio.conflictos`, `servicio.reemplazar` (Task 4).
- Produces: POST a `conciliacion:archivos` con `reemplazar=<ac.pk>` → `servicio.reemplazar(ac)`; mensaje `warning` por cada conciliación afectada: `f"Se quitó el archivo de {otra.etiqueta}, que volvió a borrador: vuelve a conciliarla."`; redirige a `archivos`.

- [ ] **Step 1: Write the failing tests** (cliente logueado como en `test_vistas_asistente.py`)
  - `test_archivos_muestra_enlace_y_boton_reemplazar`: A procesada; B con los mismos Transbank → el HTML de `archivos` de B contiene `reverse("conciliacion:detalle", args=[A.pk])`, el texto `Ya conciliado en Conciliación N° {A.pk}` y `name="reemplazar"`.
  - `test_boton_reemplazar`: POST `{"reemplazar": ac.pk}` → 302; A en `BORRADOR`; el mensaje de la siguiente página nombra `Conciliación N° {A.pk}`; `servicio.validar(B)` ya no tiene errores de duplicado.
  - `test_revision_bloquea_con_duplicado`: en la página `revision` de B, el botón `procesar` está `disabled` y aparece el enlace a A.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest conciliacion/tests/test_duplicados.py -k "boton or enlace or revision"` → FAIL.
- [ ] **Step 3: Implement**: en la columna Estado de `nueva_archivos.html`, si el archivo tiene conflictos, mostrar `<span class="estado-error">Ya conciliado en <a href="detalle o archivos de la otra">{{ otro.conciliacion.etiqueta }}</a></span>` y, junto a "Quitar", un form POST con botón `name="reemplazar"` y texto "Reemplazar", con `title` que explique que se quita de la otra conciliación. En `nueva_revision.html`, mostrar el mismo enlace en la lista de errores (el texto de `validar` ya bloquea el botón). El enlace va a `detalle` si la otra está `PROCESADA` y a `archivos` si está en `BORRADOR`.
- [ ] **Step 4: Run** la suite completa `.venv\Scripts\python -m pytest` → PASS.
- [ ] **Step 5: Commit** (solo con autorización): `Agrego enlace y botón Reemplazar para archivos ya conciliados`

### Task 6: Verificación final en la app

- [ ] **Step 1:** `.venv\Scripts\python manage.py migrate` sobre la base de desarrollo → aplica `0006` sin errores; las conciliaciones existentes aparecen en la lista como "Conciliación N° X".
- [ ] **Step 2:** `.venv\Scripts\python manage.py runserver`, crear una conciliación, subir los archivos del 08-09 y conciliar; descargar el Excel y el PDF y verificar el nombre `conciliacion_<hoy>`.
- [ ] **Step 3:** Crear otra conciliación con los mismos Transbank → aparecen el enlace y "Reemplazar"; probar ambos caminos.
- [ ] **Step 4:** Informar al usuario el resultado y los números nuevos de "cartola sin archivo" (Task 2).
