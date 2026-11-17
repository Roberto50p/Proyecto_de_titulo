"""Detecta qué tipo de archivo subió el usuario mirando su contenido (no su nombre)."""

from .cartola import es_bancoestado
from .comunes import ArchivoNoReconocido, buscar_celda, leer_hoja
from .dolar import es_abono_dolar, es_cartera, es_erp

TRANSBANK = "transbank"
BORDERO = "bordero"
CARTOLA = "cartola"
ABONO_USD, ERP, EMISOR = "abono_usd", "erp", "emisor"


def detectar(archivo) -> str:
    hoja = leer_hoja(archivo, max_filas=40)
    if buscar_celda(hoja, "Abonos por día") is not None and buscar_celda(hoja, "Medio de pago:") is not None:
        return TRANSBANK
    if buscar_celda(hoja, "Cargos de Débitos y Créditos") is not None:
        return BORDERO
    if (buscar_celda(hoja, "Movimientos") is not None and buscar_celda(hoja, "Cuenta N") is not None) \
            or es_bancoestado(hoja):
        return CARTOLA
    if es_abono_dolar(hoja):
        return ABONO_USD
    if es_cartera(hoja):
        return EMISOR
    if es_erp(hoja):
        return ERP
    raise ArchivoNoReconocido(
        "No se reconoce el archivo. Se esperan: bordero de FrontOffice, cartola del banco (Banco de Chile o "
        "BancoEstado), reporte Transbank 'Abonos por día' o, en dólares, el abono Transbank US$, el ERP de tarjetas "
        "y la cartera 'Posición Por Clientes' de cada tarjeta."
    )
