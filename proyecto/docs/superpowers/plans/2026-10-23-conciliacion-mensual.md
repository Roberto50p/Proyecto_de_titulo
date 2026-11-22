# Conciliación mensual Transbank · Bordero · Cartola — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web Django + SQLite que concilia mensualmente (por fecha de abono) bordero, Transbank débito/crédito/prepago y cartola, y entrega PDF y Excel de discrepancias separados por medio de pago.

**Architecture:** `lectores/` convierte cada Excel en DataFrames normalizados; `motor/` (pandas puro, sin Django) cruza y clasifica; `servicio.py` persiste en SQLite (pagos de bordero únicos globalmente, pendientes entre meses); `reportes/` arma PDF/Excel desde la base; vistas con asistente de 4 pasos.

**Tech Stack:** Python 3.14, Django 5.2 LTS, pandas ≥ 2.3, openpyxl, ReportLab, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-10-23-conciliacion-mensual-design.md`

## Global Constraints

- Todo dentro de `proyecto/`; app nueva `conciliacion`; paquete de settings sigue siendo `hotel`.
- Interfaz, mensajes, nombres de dominio y commits en español; commits cortos estilo estudiante ("Agrego lector de bordero").
- Medios: constantes `DEBITO`, `CREDITO`, `PREPAGO`; etiquetas "Débito", "Crédito", "Prepago"; colores Débito `#1F5FA8`, Crédito `#B7791F`, Prepago `#2F7D4F`, y el nombre siempre junto al color.
- Categorías (códigos exactos): `OK, DIF_MONTO, DIGITACION, SIN_BORDERO, FUERA_PERIODO, CUOTA, MEDIO_DISTINTO, SIN_ABONO, ABONO_CARTOLA, DATO_INVALIDO`; tipos `Operación, Dato, Aviso, Pendiente`; gravedad Operación > Dato > Pendiente > Aviso.
- Parámetros por defecto: tolerancia CLP 100; umbral similitud 0,75; holgura cartola 1 día hábil; patrones cartola `transbank`, `tbk`; equivalencias `RCO→{DEBITO,PREPAGO}`, `V$→{CREDITO}`, `MC$→{CREDITO}`, `AME$→{CREDITO}`, `D$→{CREDITO}`.
- Códigos: texto, sin espacios, mayúsculas, sin ceros a la izquierda; nunca `int()`.
- Montos CLP como `int`. Cruce con Monto original; totales con Monto venta válido para abono.
- Sin CDN: estáticos locales. Secretos por variables de entorno (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`), valores de desarrollo por defecto.
- Datos reales nunca se versionan; tests de integración leen `CONCILIACION_DATOS_PRUEBA` (por defecto `<repo>/../referencia/datos de prueba 8 sept`) y se omiten si no existe.
- Comandos de prueba desde `proyecto/`: `.venv\Scripts\python -m pytest`.

## Review Focus

1. Archivo equivocado (PDF, Excel ajeno, abono en dólares) → la revisión lo marca "no reconocido"/"moneda no soportada" y bloquea; nunca un error 500. (Task 3, Task 9)
2. Archivo Transbank con fecha de abono fuera del mes elegido → error bloqueante en revisión. (Task 9)
3. El mismo archivo Transbank subido dos veces (mismo SHA-256) → se rechaza el duplicado; los totales no se duplican. (Task 9)
4. Bordero que se traslapa con uno ya cargado → no se duplican pagos (clave de identidad). (Task 6)
5. Cartola que no cubre la fecha de abono → ABONO_CARTOLA con mensaje "la cartola no cubre el <fecha>", no OK silencioso. (Task 5)

---

### Task 1: Limpieza del proyecto y base de la app

**Files:**
- Delete: `proyecto/web/`, `proyecto/media/`, `proyecto/hotel/conciliacion/`, `proyecto/hotel/mydbengine/`, `proyecto/requerimientos_v2.txt`, `proyecto/instalar_requirements.bat`
- Create: `proyecto/requirements.txt`, `proyecto/pytest.ini`, `proyecto/conciliacion/{__init__,apps,urls,views}.py`, `proyecto/conciliacion/templates/conciliacion/base.html`, `proyecto/conciliacion/templates/registration/login.html`, `proyecto/conciliacion/static/conciliacion/app.css`, `proyecto/conciliacion/tests/__init__.py`, `proyecto/conciliacion/tests/test_base.py`
- Modify: `proyecto/hotel/settings.py`, `proyecto/hotel/urls.py`, `proyecto/.gitignore`, `proyecto/ejecutar_proyecto.bat`, `proyecto/readme.md`

**Interfaces:**
- Produces: URL names `conciliacion:inicio`, `login`, `logout`; template `conciliacion/base.html` con bloques `titulo`, `contenido`, menú lateral (Nueva conciliación, Conciliaciones, Pendientes abiertos, Parámetros).

- [ ] **Step 1:** Crear `.venv` con Python 3.14 e instalar `requirements.txt` (`Django>=5.2,<5.3`, `pandas>=2.3`, `openpyxl>=3.1`, `reportlab>=4.4`, `pytest>=8`, `pytest-django>=4.9`). UTF-8.
- [ ] **Step 2: Test que falla** — `test_inicio_requiere_login`: `client.get("/")` → 302 a `/login/?next=/`; `test_login_muestra_formulario`: GET `/login/` 200 y contiene "Ingresar".
- [ ] **Step 3:** Borrar código heredado; settings: `INSTALLED_APPS` solo contrib + `conciliacion`; `LANGUAGE_CODE="es-cl"`, `TIME_ZONE="America/Santiago"`, `LOGIN_URL="login"`, `LOGIN_REDIRECT_URL="conciliacion:inicio"`, `MEDIA_ROOT=BASE_DIR/"media"`, secretos por entorno; quitar SMTP. `.gitignore`: `media/`, `.venv/`, `db.sqlite3`, `.pytest_cache/`.
- [ ] **Step 4:** Vista `inicio` (`login_required`) que redirige a la lista de conciliaciones (placeholder de lista vacía hasta Task 10 con texto "Aún no hay conciliaciones").
- [ ] **Step 5:** `pytest` → PASS; `python manage.py check` sin errores.
- [ ] **Step 6: Commit** "Limpio el proyecto heredado y creo la app conciliacion"

### Task 2: Lectores comunes y Transbank

**Files:**
- Create: `proyecto/conciliacion/lectores/{__init__,comunes,transbank}.py`, `proyecto/conciliacion/tests/conftest.py`, `proyecto/conciliacion/tests/test_lector_transbank.py`

**Interfaces:**
- Produces:
  - `comunes.normalizar_codigo(valor) -> str` ("" si vacío/NaN)
  - `comunes.parse_fecha_es(texto: str) -> date` ("07 septiembre 2026")
  - `comunes.parse_fecha_dmy(valor) -> date` ("04/09/2026" o datetime)
  - `comunes.a_entero(valor) -> int` (NaN→0)
  - `class ArchivoNoReconocido(Exception)`
  - `transbank.leer_transbank(archivo) -> ArchivoTransbank` (dataclass: `medio: str`, `moneda: str`, `cuenta: str`, `fecha_abono: date`, `resumen: dict[str,int]` con claves `total_ventas, devoluciones, comision, iva_comision, anulaciones, cobros, iva_cobros, total_abono`, `ventas: DataFrame`)
  - columnas de `ventas`: `fila, fecha_venta(date), tipo_movimiento, codigo_comercio, local, monto_original, monto_vuelto, tipo_venta, cuota_num(int|None), cuota_total(int|None), monto_abono_valido, comision, iva_comision, total_abono, tarjeta, codigo_autorizacion, codigo_norm, boleta, medio`
  - fixture `datos_reales` (Path) en `conftest.py`, con `pytest.skip` si no existe.

- [ ] **Step 1: Tests que fallan**
```python
def test_normalizar_codigo():
    assert normalizar_codigo("003098") == "3098"
    assert normalizar_codigo(" 0fofuaz ") == "FOFUAZ"
    assert normalizar_codigo(float("nan")) == ""
def test_parse_fecha_es():
    assert parse_fecha_es("07 septiembre 2026") == date(2026, 9, 7)
def test_lee_debito_real(datos_reales):
    a = leer_transbank(datos_reales / "DEBITOS TBK 08-09.xlsx")
    assert (a.medio, a.fecha_abono, a.moneda) == ("DEBITO", date(2026, 9, 8), "Pesos")
    assert a.resumen["total_abono"] == 5_269_462 and len(a.ventas) == 90
    assert a.ventas.monto_abono_valido.sum() == a.resumen["total_ventas"] == 5_331_713
def test_lee_credito_cuotas(datos_reales):
    v = leer_transbank(datos_reales / "CREDITOS TBK 08-09.xlsx").ventas.set_index("codigo_autorizacion")
    assert (v.loc["659416", "cuota_num"], v.loc["659416", "cuota_total"]) == (1, 3)
    assert v.loc["626135", "fecha_venta"] == date(2026, 7, 4)
def test_prepago_total(datos_reales):
    assert leer_transbank(datos_reales / "PREPAGO TBK 08-09.xlsx").resumen["total_abono"] == 861_527
def test_archivo_ajeno(tmp_path):  # Review Focus 1
    p = tmp_path / "x.xlsx"; pd.DataFrame({"a": [1]}).to_excel(p)
    with pytest.raises(ArchivoNoReconocido): leer_transbank(p)
```
- [ ] **Step 2:** Correr → FAIL (módulo no existe).
- [ ] **Step 3:** Implementar. Encabezado: fila que contiene "Monto original de venta" (subcolumnas) + fila anterior con `ffill` (grupos); "N° de cuota" "k/n"→(k,n), "S/C"→None; medio desde la celda bajo "Medio de pago:" mapeado a constantes; fecha de abono desde "Día desde" (o "Periodo de consulta").
- [ ] **Step 4:** Correr → PASS.
- [ ] **Step 5: Commit** "Agrego lector de archivos Transbank"

### Task 3: Lectores de bordero, cartola y detección de tipo

**Files:**
- Create: `proyecto/conciliacion/lectores/{bordero,cartola,deteccion}.py`, `proyecto/conciliacion/tests/test_lector_bordero_cartola.py`

**Interfaces:**
- Produces:
  - `bordero.leer_bordero(archivo) -> ArchivoBordero` (`desde: date`, `hasta: date`, `movimientos: DataFrame` con `hab, reserva, cuenta, cod_deb, descripcion, factura, valor(int), documento, documento_norm, fecha(date), hora(str), usuario, designacion`)
  - `cartola.leer_cartola(archivo) -> ArchivoCartola` (`cuenta: str`, `moneda: str`, `movimientos: DataFrame` con `fecha, descripcion, canal, nro_docto, cargo(int), abono(int), saldo(int)`; `desde`, `hasta`)
  - `deteccion.detectar(archivo) -> str` ∈ {`"transbank"`, `"bordero"`, `"cartola"`}; lanza `ArchivoNoReconocido`.

- [ ] **Step 1: Tests que fallan**
```python
def test_bordero_real(datos_reales):
    b = leer_bordero(datos_reales / "BORDERO 04-09 A 07-09.xlsx")
    assert (b.desde, b.hasta) == (date(2026, 9, 4), date(2026, 9, 7))
    assert len(b.movimientos) == 1859
    assert not b.movimientos.cod_deb.isin(["Cod. Deb."]).any()
    assert (b.movimientos.cod_deb == "RCO").sum() == 143
def test_cartola_real(datos_reales):
    c = leer_cartola(datos_reales / "cartola.xlsx")
    assert c.cuenta == "00-000-62110-02" and c.moneda.startswith("Pesos")
    assert {861_527, 5_269_462, 2_597_371} <= set(c.movimientos.query("fecha == @date(2026,9,8)").abono)
def test_detecta_tipos(datos_reales):
    assert detectar(datos_reales / "cartola.xlsx") == "cartola"
    assert detectar(datos_reales / "BORDERO 04-09 A 07-09.xlsx") == "bordero"
    assert detectar(datos_reales / "PREPAGO TBK 08-09.xlsx") == "transbank"
def test_detecta_no_reconocido(tmp_path):  # Review Focus 1
    p = tmp_path / "otro.xlsx"; pd.DataFrame({"x": [1]}).to_excel(p)
    with pytest.raises(ArchivoNoReconocido): detectar(p)
    q = tmp_path / "doc.pdf"; q.write_bytes(b"%PDF-1.4")
    with pytest.raises(ArchivoNoReconocido): detectar(q)
```
- [ ] **Step 2:** Correr → FAIL.
- [ ] **Step 3:** Implementar. Bordero por posición (col 6 = factura); excluir títulos, totales, pies "FrontOffice"; período desde la fila "Periodo de:". Cartola: fila de encabezado con "Fecha" y "Descripción"; cuenta desde "Cuenta N°:". Detección por marcadores: "Abonos por día" → transbank; "Cargos de Débitos y Créditos" → bordero; "Movimientos" + "Cargos (" → cartola; leer solo las primeras ~40 filas.
- [ ] **Step 4:** Correr → PASS.
- [ ] **Step 5: Commit** "Agrego lectores de bordero y cartola con detección de tipo"

### Task 4: Motor — cruce de ventas y clasificación

**Files:**
- Create: `proyecto/conciliacion/motor/{__init__,parametros,categorias,mensajes,cruce}.py`, `proyecto/conciliacion/tests/test_cruce_ventas.py`

**Interfaces:**
- Produces:
  - `parametros.Parametros` (dataclass: `tolerancia_clp=100`, `umbral_similitud=0.75`, `dias_holgura=1`, `patrones_cartola=("transbank","tbk")`, `equivalencias: dict[str, frozenset[str]]`), `Parametros.desde_dict(d)`, `.a_dict()`
  - `categorias`: constantes de medios y categorías, `TIPO[cat]`, `GRAVEDAD[cat]`, `ETIQUETA[cat]`, `ETIQUETA_MEDIO[medio]`, `COLOR_MEDIO[medio]`
  - `mensajes.mensaje(categoria: str, **ctx) -> str`
  - `cruce.conciliar_ventas(ventas: DataFrame, pagos: DataFrame, cobertura: list[tuple[date, date]], params: Parametros) -> DataFrame` — `ventas` = columnas de Task 2 (+`id`); `pagos` columnas `id, documento_norm, fecha, valor, cod_deb, pendiente_mes(str|None)`. Devuelve una fila por venta con `venta_id, categoria, pago_id(int|None), monto_bordero(int|None), diferencia(int|None), codigo_sugerido(str|None), nota(str), mensaje(str)`. Cada `pago_id` aparece a lo sumo una vez.
  - `cruce.pagos_tarjeta(pagos: DataFrame, params) -> DataFrame` (filtra cod_deb en equivalencias; valor < 0 = pago; valor > 0 → marcados `invalido=True`)

- [ ] **Step 1: Tests que fallan** (DataFrames sintéticos con helper `venta(...)`/`pago(...)` en el archivo de test)
  - `test_ok_con_ceros`: venta "003098" 57420 débito vs pago "3098" −57421 → OK, diferencia −1.
  - `test_dif_monto`: 115204 vs −113700 → DIF_MONTO, diferencia 1504.
  - `test_digitacion`: venta "F0FUAZ" 106999 06/09 vs pago "0FOFUAZ" −106999 06/09 → DIGITACION, `codigo_sugerido == "0FOFUAZ"`; el mensaje contiene "F0FUAZ" y "0FOFUAZ".
  - `test_digitacion_exige_mismo_dia_y_monto`: mismo código parecido pero otra fecha → SIN_BORDERO.
  - `test_sin_bordero` y `test_fuera_periodo` (fecha fuera de cobertura).
  - `test_cuota_fuera_cobertura`: cuota 1/3 del 03/09 con cobertura 04–07/09 → CUOTA.
  - `test_medio_distinto`: venta CREDITO cruza con pago RCO, monto igual → MEDIO_DISTINTO; con diferencia > 100 → DIF_MONTO (precedencia).
  - `test_pago_usado_una_vez`: dos ventas con mismo código → solo una OK.
  - `test_cierra_pendiente`: pago con `pendiente_mes="2026-08"` → OK y `nota` contiene "cierra pendiente de 2026-08".
  - `test_dato_invalido`: venta con código vacío → DATO_INVALIDO.
  - `test_toda_venta_clasificada`: `len(salida) == len(ventas)` y sin categorías nulas.
- [ ] **Step 2:** Correr → FAIL.
- [ ] **Step 3:** Implementar en el orden de precedencia de la spec §13.4. Exacto: agrupar pagos libres por `documento_norm`; si hay varios, menor |dif| y luego fecha más cercana. Digitación: candidatos libres de misma fecha, medio compatible y |dif| ≤ tolerancia; `difflib.SequenceMatcher(None, a, b).ratio() >= umbral`; mejor ratio.
- [ ] **Step 4:** Correr → PASS.
- [ ] **Step 5: Commit** "Agrego motor de cruce de ventas Transbank con bordero"

### Task 5: Motor — abonos contra cartola y cuadratura

**Files:**
- Create: `proyecto/conciliacion/motor/abonos.py`, `proyecto/conciliacion/tests/test_abonos.py`

**Interfaces:**
- Consumes: `ArchivoTransbank.resumen`, `ArchivoCartola.movimientos`, `Parametros`.
- Produces:
  - `abonos.conciliar_abonos(abonos: list[dict], cartola: DataFrame, cartola_rango: tuple[date, date], params) -> list[dict]` — entrada `{"archivo_id", "medio", "fecha_abono", "total_abono"}`; salida agrega `categoria ("OK"|"ABONO_CARTOLA"), cartola_fecha, cartola_descripcion, cartola_monto, diferencia, mensaje`. Cada línea de cartola se usa una vez.
  - `abonos.cuadratura_archivo(resumen: dict) -> int` (diferencia; 0 si cuadra).

- [ ] **Step 1: Tests que fallan**
  - `test_tres_abonos_reales` (con `datos_reales`): los 3 archivos → 3 OK, diferencia 0.
  - `test_abono_mismo_monto_dos_medios`: dos abonos y dos líneas iguales → cada línea usada una vez.
  - `test_holgura_dia_habil`: abono viernes, línea lunes con holgura 1 → OK.
  - `test_cartola_no_cubre` (Review Focus 5): fecha fuera del rango de la cartola → ABONO_CARTOLA y mensaje contiene "no cubre".
  - `test_abono_con_diferencia`: línea con monto +500 → ABONO_CARTOLA, diferencia 500.
  - `test_cuadratura_archivo_real`: `cuadratura_archivo(resumen débito) == 0`.
- [ ] **Step 2–4:** FAIL → implementar (solo líneas con abono > 0 y descripción que contiene algún patrón, sin mayúsculas) → PASS.
- [ ] **Step 5: Commit** "Agrego cruce de abonos Transbank con la cartola"

### Task 6: Modelos y servicio de procesamiento (integración con datos reales)

**Files:**
- Create: `proyecto/conciliacion/models.py`, `proyecto/conciliacion/admin.py`, `proyecto/conciliacion/migrations/0001_initial.py`, `0002_parametros_iniciales.py` (data migration), `proyecto/conciliacion/servicio.py`, `proyecto/conciliacion/tests/test_servicio.py`, `proyecto/conciliacion/tests/test_integracion_real.py`

**Interfaces:**
- Produces (modelos): `Conciliacion(anio, mes, estado[BORRADOR|PROCESADA|ERROR], parametros JSON, resumen JSON, creada_por, creada_en, procesada_en)` unique (anio, mes), propiedad `etiqueta` ("Septiembre 2026"); `ArchivoCargado(conciliacion, tipo, medio, archivo, nombre, sha256, fecha_abono, desde, hasta, filas, total_abono, resumen JSON, error)`; `CoberturaBordero(desde, hasta, archivo)`; `PagoBordero` (campos de lector + `documento_norm`, `archivo`, `conciliacion` FK null = dónde quedó conciliado, `invalido`, unique (documento_norm, fecha, hora, valor, cuenta, cod_deb)); `VentaTransbank` (campos de lector + resultado de `conciliar_ventas` + `revisado`, `observacion`); `ResultadoAbono`; `MovimientoCartola`; `Pendiente(pago OneToOne, origen FK, cierre FK null, abierto, observacion)`; `ParametrosSistema` (singleton id=1) y `EquivalenciaMedio(cod_deb, medio)`.
- Produces (servicio):
  - `servicio.leer_archivo(archivo_cargado: ArchivoCargado) -> None` (detecta tipo, guarda metadatos o `error`)
  - `servicio.validar(conciliacion) -> list[str]` (errores bloqueantes)
  - `servicio.procesar(conciliacion) -> Conciliacion` (transacción atómica; reemplaza resultados anteriores; registra pagos con `get_or_create` por clave; abre/cierra pendientes; guarda `resumen` por medio con `ventas, comision_iva, abono_tbk, abono_cartola, diferencial, n_ventas, n_falla` y `matriz[categoria][medio] = {n, monto}`)
  - `servicio.parametros_actuales() -> Parametros`

- [ ] **Step 1: Tests que fallan**
  - `test_bordero_traslapado_no_duplica` (Review Focus 4): procesar dos meses con el mismo bordero → `PagoBordero.objects.count()` igual a filas únicas.
  - `test_pendiente_se_cierra_mes_siguiente`: mes 1 deja SIN_ABONO → `Pendiente.abierto`; mes 2 con la venta → cerrado y venta OK con nota.
  - `test_reprocesar_conserva_observacion`: observación en una venta DIF_MONTO se mantiene tras `procesar` de nuevo.
  - `test_integracion_real` (`datos_reales`, Septiembre 2026 con los 5 archivos): conteos por medio y categoría según spec §10: Débito `OK 82, DIF_MONTO 1, DIGITACION 3, SIN_BORDERO 4`; Crédito `CUOTA 2, FUERA_PERIODO 28, DIF_MONTO 1, DIGITACION 1, SIN_BORDERO 3, OK 4`; Prepago `DIF_MONTO 1, DIGITACION 1`, resto OK; 3 abonos OK; por medio Σ `monto_abono_valido` por categoría == `resumen.total_ventas`. Desvíos razonados se documentan en el test.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementar modelos, migraciones (parámetros por defecto de Global Constraints), servicio.
- [ ] **Step 4:** PASS; `python manage.py makemigrations --check` sin cambios.
- [ ] **Step 5: Commit** "Agrego modelos y servicio que guarda la conciliación"

### Task 7: Reporte Excel

**Files:**
- Create: `proyecto/conciliacion/reportes/{__init__,datos,excel}.py`, `proyecto/conciliacion/tests/test_reporte_excel.py`

**Interfaces:**
- Produces: `datos.armar(conciliacion) -> dict` (claves `encabezado, resumen_medios, total, matriz, capitulos{DEBITO,CREDITO,PREPAGO}: {resumen, fallas, conciliados, otros}, cuotas, pendientes, parametros, archivos`) compartido con PDF y vista; `excel.generar(conciliacion) -> bytes`.

- [ ] **Step 1: Test que falla** — con conciliación procesada (fixture desde datos reales o factory sintética): hojas exactas `["Resumen","Débito","Crédito","Cuotas","Prepago","Pendientes","Conciliados","Parámetros"]`; en `Resumen` la fila Total de abono == suma de los 3 medios; en `Débito` las filas de falla = n_falla débito; columnas `Observación` y `Corregir` presentes en `Pendientes`; autofiltro y panel fijo en hojas de detalle.
- [ ] **Step 2–4:** FAIL → implementar (formato `#,##0`, color de pestaña por medio, encabezado con nombre del medio, ancho de columnas) → PASS.
- [ ] **Step 5: Commit** "Agrego exportación a Excel de la conciliación"

### Task 8: Reporte PDF

**Files:**
- Create: `proyecto/conciliacion/reportes/pdf.py`, `proyecto/conciliacion/tests/test_reporte_pdf.py`

**Interfaces:**
- Consumes: `datos.armar`.
- Produces: `pdf.generar(conciliacion) -> bytes`.

- [ ] **Step 1: Test que falla** — el resultado empieza con `b"%PDF"`; extraer texto (con `pypdf`, dependencia solo de test) y verificar que aparecen en orden "Resumen", "Matriz", "Débito", "Crédito", "Cuotas", "Prepago", "Pendientes", "Parámetros", y "HOTELERA SAN FRANCISCO S.A."; pie "Página 1 de".
- [ ] **Step 2–4:** FAIL → implementar con `SimpleDocTemplate` A4 apaisado, tablas con banda de color del medio + nombre, números alineados a la derecha con miles "." → PASS.
- [ ] **Step 5: Commit** "Agrego reporte PDF de discrepancias"

### Task 9: Asistente "Nueva conciliación", resultado y descargas

**Files:**
- Create: `proyecto/conciliacion/forms.py`, `proyecto/conciliacion/templates/conciliacion/{nueva_mes,nueva_archivos,nueva_revision,resultado}.html`, `proyecto/conciliacion/tests/test_vistas_asistente.py`
- Modify: `proyecto/conciliacion/views.py`, `proyecto/conciliacion/urls.py`, `proyecto/conciliacion/static/conciliacion/app.css`

**Interfaces:**
- Produces URLs: `conciliacion:nueva` (paso 1), `conciliacion:archivos <pk>`, `conciliacion:revision <pk>`, `conciliacion:procesar <pk>` (POST), `conciliacion:detalle <pk>` (`?medio=&categoria=&local=`), `conciliacion:pdf <pk>`, `conciliacion:excel <pk>`.

- [ ] **Step 1: Tests que fallan**
  - Flujo completo con datos reales (subida múltiple) → `detalle` 200 contiene "Débito", "Crédito", "Prepago" y "Diferencial"; `pdf` responde `application/pdf`; `excel` responde `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` con nombre `conciliacion_2026_09.xlsx`.
  - `test_mes_existente_pide_confirmacion`: elegir un mes ya procesado muestra aviso y requiere confirmar reemplazo.
  - Review Focus 1: subir un PDF → revisión muestra "Archivo no reconocido" y el botón Conciliar está deshabilitado; sin error 500.
  - Review Focus 2: archivo Transbank con abono fuera del mes → error "La fecha de abono 08/09/2026 no pertenece a Octubre 2026".
  - Review Focus 3: mismo archivo Transbank dos veces → "Archivo duplicado" y no se guarda dos veces.
  - Faltan archivos (sin cartola o sin bordero o sin Transbank) → error bloqueante con el nombre del faltante.
  - Usuario no autenticado → redirige a login en todas las URLs.
- [ ] **Step 2–4:** FAIL → implementar (formulario con `<input type=file multiple>`; tabla de revisión por archivo: tipo, medio, período/fecha abono, filas, total; indicadores, pestañas por medio con color y nombre, matriz, tabla de fallas filtrable) → PASS.
- [ ] **Step 5: Commit** "Agrego asistente de nueva conciliación y pantalla de resultados"

### Task 10: Historial, pendientes, parámetros, revisión de hallazgos y cierre

**Files:**
- Create: `proyecto/conciliacion/templates/conciliacion/{lista,pendientes,parametros}.html`, `proyecto/conciliacion/tests/test_vistas_gestion.py`
- Modify: `views.py`, `urls.py`, `forms.py`, `app.css`, `proyecto/readme.md`

**Interfaces:**
- Produces URLs: `conciliacion:lista`, `conciliacion:pendientes`, `conciliacion:parametros`, `conciliacion:revisar_venta <pk>` (POST `revisado`, `observacion`), `conciliacion:revisar_pendiente <pk>` (POST).

- [ ] **Step 1: Tests que fallan** — lista muestra "Septiembre 2026" con su diferencial y n° de fallas; pendientes lista abiertos con mes de origen; guardar parámetros con tolerancia 200 cambia `parametros_actuales().tolerancia_clp`; tolerancia negativa → error de formulario; revisar venta guarda observación y vuelve al detalle con el mismo filtro.
- [ ] **Step 2–4:** FAIL → implementar → PASS; suite completa verde.
- [ ] **Step 5:** `readme.md`: instalación (`py -3 -m venv .venv`, `pip install -r requirements.txt`, `migrate`, `createsuperuser`, `runserver`), cómo correr tests y dónde poner los datos de prueba.
- [ ] **Step 6:** Smoke manual: `runserver`, login, conciliar Septiembre 2026 con los 5 archivos reales, revisar pantallas y abrir PDF/Excel descargados.
- [ ] **Step 7: Commit** "Agrego historial, pendientes y parámetros; actualizo readme"
