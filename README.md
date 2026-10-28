# Conciliación Transbank · Hotel Plaza San Francisco

Plataforma web (Django + SQLite) que concilia cada mes las ventas con tarjeta del hotel:

- **Bordero** de FrontOffice ("Cargos de Débitos y Créditos"): lo que registró el hotel. Se lee en `.xlsx` y en el `.XLS` antiguo (Excel 4.0) que exporta FrontOffice.
- **Transbank** "Abonos por día": lo que liquidó Transbank. Sirve un archivo por medio de pago (**débito, crédito, prepago**) o uno con **todos los medios de pago**; en ese caso se separa por medio usando el detalle y se exige que sume el Total abono.
- **Cartola** en pesos de lo que llegó al banco: **Banco de Chile** (una hoja) o **BancoEstado** "Cartola Histórica" (hojas Resumen y Movimientos; se pueden subir varias, una por día).

El mes se cierra por **fecha de abono**. El resultado muestra las discrepancias separadas por medio de pago y se descarga en **PDF** y **Excel**.

Diseño: `docs/superpowers/specs/2026-10-23-conciliacion-mensual-design.md` · Plan: `docs/superpowers/plans/2026-10-23-conciliacion-mensual.md`.

# DEMO desplegada en VERCEL
Se ha desplegado una DEMO del proyecto para el cliente
Usuario: admin
Contraseña: admin
https://conciliacionhotelplaza.vercel.app/

# Instalacion Desarrollo
## Windows
Ambiente para las herramientas de desarrollo
```bat
cd proyecto
py -3.14 -m venv .venv
.venv\Scripts\activate
```
Instalación de las herramientas
```bat
py -m pip install -r requirements-dev.txt
py manage.py migrate
py manage.py createsuperuser
py manage.py runserver
```

Luego abrir http://127.0.0.1:8000 e ingresar con el usuario creado. También sirve `ejecutar_proyecto.bat` (migra y levanta el servidor).

Variables de entorno opcionales: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (`1`/`0`), `DJANGO_ALLOWED_HOSTS`, `CONCILIACION_DATOS_PRUEBA`, `CONCILIACION_DATOS_OCTUBRE`.

`requirements.txt` tiene solo lo que usa la app en producción; `requirements-dev.txt` agrega las pruebas (`pytest`).

## Despliegue en Vercel

Vercel reconoce el proyecto por `manage.py` (Python 3.14 según `.python-version`), usa `hotel.wsgi.application` y ejecuta `collectstatic` en el build. Configurar en Vercel (Settings → General) **Root Directory = `proyecto`** y estas variables de entorno:

- `DATABASE_URL`: PostgreSQL de **Neon** (Vercel la define al conectar Neon desde Storage/Marketplace).
- `DJANGO_SECRET_KEY`: clave larga y aleatoria. `DEBUG` queda apagado en Vercel salvo `DJANGO_DEBUG=1`.
- Archivos subidos en **Cloudflare R2**: `AWS_STORAGE_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` y `AWS_S3_ENDPOINT_URL` (`https://<id-cuenta>.r2.cloudflarestorage.com`).
- Con dominio propio, agregarlo a `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS` (estas variables reemplazan la lista por defecto).

Las migraciones y el usuario se crean una vez desde el PC apuntando a Neon (`vercel env pull .env.local` o copiando `DATABASE_URL`):

```bat
set DATABASE_URL=postgresql://...
py manage.py migrate
py manage.py createsuperuser
```

Límite: Vercel acepta peticiones de hasta **4,5 MB**, así que cada envío de archivos debe pesar menos que eso (subir los archivos en grupos si el bordero es grande).

## Uso

1. **Nueva conciliación** → elegir el mes de abono.
2. **Archivos** → subir el bordero (uno o más), las cartolas y los archivos Transbank de cada día de abono (uno por medio de pago o uno con todos los medios). Se reconocen por su contenido, el nombre no importa.
3. **Revisión de lectura** → confirmar qué entendió el sistema de cada archivo. Si falta algo o un archivo no corresponde, no deja conciliar.
4. **Resultado** → resumen, matriz de fallas por medio de pago, una pestaña por Débito / Crédito / Prepago y pendientes. Cada falla dice qué pasó y qué hacer; se puede anotar una observación y marcarla como revisada.

### Modificar una conciliación ya hecha

Desde **Conciliaciones → Modificar** (o "Modificar archivos o conciliar de nuevo" en el resultado) se vuelve a la pantalla de archivos del mes:

- **Agregar o quitar archivos**: la conciliación vuelve a borrador hasta que se concilie otra vez.
- **Conciliar de nuevo con otros archivos**: "Quitar todos los archivos" deja el mes vacío para subir otra versión del bordero, las cartolas y los Transbank del mismo mes. Sigue siendo una sola conciliación por mes; el resultado anterior se reemplaza.
- Al quitar un bordero se descartan su período cubierto y los pagos que solo venían en él, así no siguen cruzando con ventas. Los pagos que otro mes ya usó o dejó como pendientes se conservan.
- Las observaciones y marcas de "revisado" se guardan al cambiar archivos y se vuelven a aplicar al conciliar: en ventas por categoría, código y fecha; en abonos por medio y fecha de abono; en pendientes por pago del bordero.

Las categorías y reglas están en `conciliacion/motor/` (`categorias.py`, `cruce.py`, `abonos.py`). En **Parámetros** se editan:

- tolerancia en pesos, similitud de códigos, días de holgura en cartola y días entre venta y bordero;
- textos que identifican abonos Transbank en la cartola (`transbank, tbk`);
- **medio probable según la cartola**: una regla `texto = medio` por línea, para orientar los abonos que llegaron al banco sin archivo Transbank (gana la primera que calce; si ninguna calza dice "Sin determinar");
- **omitir archivos en moneda extranjera**: desmarcado, un Transbank o cartola en dólares bloquea la conciliación; marcado, se deja fuera con un aviso;
- equivalencias Cod. Deb. → medio de pago.

Cada conciliación guarda los parámetros con que se procesó y los muestra en el PDF y el Excel.

### Conciliación en dólares

La sección **Conciliación en US$** (`/dolares/`) es la app `web` de la rama `main`, incorporada sin cambiar su código Python (`web/` y `hotel/conciliacion/` son copia exacta de `main`). Solo se reescribió su plantilla `web/templates/procesamiento.html` con los estilos de la plataforma, manteniendo campos, textos y acciones. Se publican únicamente su vista de procesamiento y sus dos descargas Excel, y piden sesión como el resto (`hotel/urls.py`).

Se suben ERP, Amex, Diners, Visa y Mastercard en dólares, banco y Transbank, y se pulsa "Analizar Archivos por ERP". Necesita internet: en cada carga consulta el dólar en mindicador.cl. Los bloques "Consolidado en Pesos", "Parametrización de valores" y "Enviar por Email" vienen sin funcionalidad desde `main`.

## Estructura

```
proyecto/
  hotel/                 configuración Django (+ conciliacion/: ETL de la app web, copia de main)
  conciliacion/
    lectores/            lectura y limpieza de cada Excel (bordero, transbank, cartola, detección)
    motor/               reglas puras con pandas: cruce de ventas, abonos, categorías, mensajes
    servicio.py          guarda en SQLite, pendientes entre meses, resumen
    reportes/            datos.py (compartido), excel.py, pdf.py
    templates/, static/  interfaz
    tests/               pruebas (pytest)
  web/                   conciliación en dólares (copia de la rama main; solo cambió su plantilla)
```

## Pruebas

```bat
.venv\Scripts\python -m pytest
```

Las pruebas de integración usan los archivos reales del hotel, que **no se suben a git** (tienen nombres de huéspedes). Por defecto se buscan en `../../referencia/datos de prueba 8 sept` y `../../Datos de prueba octubre` (al lado del repositorio) o en las carpetas indicadas en `CONCILIACION_DATOS_PRUEBA` y `CONCILIACION_DATOS_OCTUBRE`. Si no están, esas pruebas se omiten.
