"""Detecta qué tipo de archivo subió el usuario mirando su contenido (no su nombre)."""

from .comunes import ArchivoNoReconocido, buscar_celda, leer_hoja

TRANSBANK = "transbank"
BORDERO = "bordero"
CARTOLA = "cartola"


def detectar(archivo) -> str:
    hoja = leer_hoja(archivo, max_filas=40)
    if buscar_celda(hoja, "Abonos por día") is not None and buscar_celda(hoja, "Medio de pago:") is not None:
        return TRANSBANK
    if buscar_celda(hoja, "Cargos de Débitos y Créditos") is not None:
        return BORDERO
    if buscar_celda(hoja, "Movimientos") is not None and buscar_celda(hoja, "Cuenta N") is not None:
        return CARTOLA
    raise ArchivoNoReconocido(
        "No se reconoce el archivo. Se esperan: bordero de FrontOffice, cartola del banco o "
        "reporte Transbank 'Abonos por día'."
    )
