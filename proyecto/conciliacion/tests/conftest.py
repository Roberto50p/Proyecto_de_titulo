from pathlib import Path

import pytest
from django.conf import settings
from django.core.files import File

ARCHIVOS_SEPTIEMBRE = [
    "BORDERO 04-09 A 07-09.xlsx",
    "cartola.xlsx",
    "DEBITOS TBK 08-09.xlsx",
    "CREDITOS TBK 08-09.xlsx",
    "PREPAGO TBK 08-09.xlsx",
]
ARCHIVOS_OCTUBRE = [
    "BORDERO DEBITO Y CREDITO OCTUBRE 2026.XLS",
    "TBK.xls",
    "TBK_5.xls",  # dólares
    *[f"Cartola_{n}.xlsx" for n in range(1, 10)],
]


def _carpeta(ruta):
    carpeta = Path(ruta)
    if not carpeta.is_dir():
        pytest.skip(f"No se encontraron los datos de prueba en {carpeta}")
    return carpeta


@pytest.fixture
def datos_reales():
    """Carpeta con los archivos reales del hotel (no versionados). Se omite la prueba si no está."""
    return _carpeta(settings.CONCILIACION_DATOS_PRUEBA)


@pytest.fixture
def datos_octubre():
    """Archivos reales de octubre (no versionados). Se omite la prueba si no están."""
    return _carpeta(settings.CONCILIACION_DATOS_OCTUBRE)


@pytest.fixture
def media_temporal(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


def _crear(carpeta, anio, mes, nombres):
    from conciliacion.models import ArchivoCargado, Conciliacion
    from conciliacion.servicio import leer_archivo, sha256_de

    conc = Conciliacion.objects.create(anio=anio, mes=mes)
    for nombre in nombres:
        with open(carpeta / nombre, "rb") as f:
            archivo = File(f, name=nombre)
            ac = ArchivoCargado(conciliacion=conc, nombre=nombre, sha256=sha256_de(archivo))
            ac.archivo.save(nombre, archivo, save=False)
            ac.save()
        leer_archivo(ac)
    return conc


@pytest.fixture
def crear_conciliacion(db, datos_reales, media_temporal):
    """Crea una conciliación con archivos reales ya leídos (sin procesar)."""

    def crear(anio=2026, mes=9, nombres=ARCHIVOS_SEPTIEMBRE):
        return _crear(datos_reales, anio, mes, nombres)

    return crear


@pytest.fixture
def octubre_cargado(db, datos_octubre, media_temporal):
    """Conciliación de octubre con los archivos reales leídos (sin procesar)."""
    return _crear(datos_octubre, 2026, 10, ARCHIVOS_OCTUBRE)


@pytest.fixture
def septiembre_procesado(crear_conciliacion):
    from conciliacion.servicio import procesar

    return procesar(crear_conciliacion())
