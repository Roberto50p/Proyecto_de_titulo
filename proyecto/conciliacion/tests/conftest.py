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


@pytest.fixture
def datos_reales():
    """Carpeta con los archivos reales del hotel (no versionados). Se omite la prueba si no está."""
    carpeta = Path(settings.CONCILIACION_DATOS_PRUEBA)
    if not carpeta.is_dir():
        pytest.skip(f"No se encontraron los datos de prueba en {carpeta}")
    return carpeta


@pytest.fixture
def media_temporal(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def crear_conciliacion(db, datos_reales, media_temporal):
    """Crea una conciliación con archivos reales ya leídos (sin procesar)."""
    from conciliacion.models import ArchivoCargado, Conciliacion
    from conciliacion.servicio import leer_archivo, sha256_de

    def crear(anio=2026, mes=9, nombres=ARCHIVOS_SEPTIEMBRE):
        conc = Conciliacion.objects.create(anio=anio, mes=mes)
        for nombre in nombres:
            with open(datos_reales / nombre, "rb") as f:
                archivo = File(f, name=nombre)
                ac = ArchivoCargado(conciliacion=conc, nombre=nombre, sha256=sha256_de(archivo))
                ac.archivo.save(nombre, archivo, save=False)
                ac.save()
            leer_archivo(ac)
        return conc

    return crear


@pytest.fixture
def septiembre_procesado(crear_conciliacion):
    from conciliacion.servicio import procesar

    return procesar(crear_conciliacion())
