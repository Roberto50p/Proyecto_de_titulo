# Conciliación Transbank · Hotel Plaza San Francisco

Plataforma web (Django + SQLite) que concilia cada mes las ventas con tarjeta del hotel:

- **Bordero** de FrontOffice ("Cargos de Débitos y Créditos"): lo que registró el hotel.
- **Transbank** "Abonos por día" de **débito, crédito y prepago**: lo que liquidó Transbank.
- **Cartola** del Banco de Chile en pesos: lo que llegó al banco.

El mes se cierra por **fecha de abono**. El resultado muestra las discrepancias separadas por medio de pago y se descarga en **PDF** y **Excel**.

Diseño: `docs/superpowers/specs/2026-10-23-conciliacion-mensual-design.md` · Plan: `docs/superpowers/plans/2026-10-23-conciliacion-mensual.md`.

## Instalación (Windows)

```bat
cd proyecto
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py createsuperuser
.venv\Scripts\python manage.py runserver
```

Luego abrir http://127.0.0.1:8000 e ingresar con el usuario creado. También sirve `ejecutar_proyecto.bat` (migra y levanta el servidor).

Variables de entorno opcionales: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (`1`/`0`), `DJANGO_ALLOWED_HOSTS`, `CONCILIACION_DATOS_PRUEBA`.

## Uso

1. **Nueva conciliación** → elegir el mes de abono.
2. **Archivos** → subir el bordero (uno o más), la cartola y un archivo Transbank por medio de pago y día de abono. Se reconocen por su contenido, el nombre no importa.
3. **Revisión de lectura** → confirmar qué entendió el sistema de cada archivo. Si falta algo o un archivo no corresponde, no deja conciliar.
4. **Resultado** → resumen, matriz de fallas por medio de pago, una pestaña por Débito / Crédito / Prepago y pendientes. Cada falla dice qué pasó y qué hacer; se puede anotar una observación y marcarla como revisada.

Las categorías y reglas están en `conciliacion/motor/` (`categorias.py`, `cruce.py`, `abonos.py`). Los parámetros (tolerancia, similitud de códigos, equivalencias Cod. Deb. → medio de pago) se editan en **Parámetros**.

## Estructura

```
proyecto/
  hotel/                 configuración Django
  conciliacion/
    lectores/            lectura y limpieza de cada Excel (bordero, transbank, cartola, detección)
    motor/               reglas puras con pandas: cruce de ventas, abonos, categorías, mensajes
    servicio.py          guarda en SQLite, pendientes entre meses, resumen
    reportes/            datos.py (compartido), excel.py, pdf.py
    templates/, static/  interfaz
    tests/               pruebas (pytest)
```

## Pruebas

```bat
.venv\Scripts\python -m pytest
```

Las pruebas de integración usan los archivos reales del hotel, que **no se suben a git** (tienen nombres de huéspedes). Por defecto se buscan en `../../referencia/datos de prueba 8 sept` (al lado del repositorio) o en la carpeta indicada en `CONCILIACION_DATOS_PRUEBA`. Si no están, esas pruebas se omiten.
