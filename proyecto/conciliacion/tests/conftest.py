from pathlib import Path

import pytest
from django.conf import settings


@pytest.fixture
def datos_reales():
    """Carpeta con los archivos reales del hotel (no versionados). Se omite la prueba si no está."""
    carpeta = Path(settings.CONCILIACION_DATOS_PRUEBA)
    if not carpeta.is_dir():
        pytest.skip(f"No se encontraron los datos de prueba en {carpeta}")
    return carpeta
