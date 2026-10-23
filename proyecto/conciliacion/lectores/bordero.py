"""Lector del bordero de FrontOffice ("Cargos de Débitos y Créditos")."""

import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .comunes import (
    ArchivoNoReconocido,
    a_entero,
    buscar_celda,
    clave,
    es_vacio,
    leer_hoja,
    normalizar_codigo,
    parse_fecha_dmy,
    texto,
)

_FECHA_DMY = re.compile(r"\d{2}/\d{2}/\d{4}")

ENCABEZADOS = {
    "hab": "hab", "reserva": "reserva", "cuenta": "cuenta", "cod. deb.": "cod_deb",
    "descripcion": "descripcion", "factura": "factura", "valor": "valor", "documento": "documento",
    "fecha": "fecha", "hora": "hora", "usuario": "usuario", "designacion": "designacion",
}


@dataclass
class ArchivoBordero:
    desde: date
    hasta: date
    movimientos: pd.DataFrame = field(repr=False)


def _es_numero(valor) -> bool:
    if isinstance(valor, (int, float)) and not es_vacio(valor):
        return True
    return bool(re.fullmatch(r"-?\d+([.,]\d+)?", texto(valor)))


def leer_bordero(archivo) -> ArchivoBordero:
    hoja = leer_hoja(archivo)
    if buscar_celda(hoja, "Cargos de Débitos y Créditos") is None:
        raise ArchivoNoReconocido("No es un bordero de FrontOffice ('Cargos de Débitos y Créditos').")

    pos = buscar_celda(hoja, "Periodo de:")
    fechas = []
    if pos:
        fila_texto = " ".join(texto(v) for v in hoja.iloc[pos[0]])
        fechas = [parse_fecha_dmy(f) for f in _FECHA_DMY.findall(fila_texto)]
    if len(fechas) < 2:
        raise ArchivoNoReconocido("El bordero no indica su período ('Periodo de: … hasta …').")

    fila_enc, _ = buscar_celda(hoja, "Cod. Deb.")
    columnas = {}
    for col in range(hoja.shape[1]):
        nombre = ENCABEZADOS.get(clave(hoja.iat[fila_enc, col]))
        if nombre and nombre not in columnas:
            columnas[nombre] = col

    filas = []
    for fila in range(len(hoja)):
        cod_deb = texto(hoja.iat[fila, columnas["cod_deb"]])
        valor = hoja.iat[fila, columnas["valor"]]
        if not cod_deb or clave(cod_deb) == "cod. deb." or not _es_numero(valor):
            continue
        # La factura viene una columna antes que su título.
        factura = texto(hoja.iat[fila, columnas["factura"] - 1]) or texto(hoja.iat[fila, columnas["factura"]])
        documento = texto(hoja.iat[fila, columnas["documento"]])
        filas.append({
            "fila": fila + 1,
            "hab": texto(hoja.iat[fila, columnas["hab"]]),
            "reserva": texto(hoja.iat[fila, columnas["reserva"]]),
            "cuenta": texto(hoja.iat[fila, columnas["cuenta"]]),
            "cod_deb": cod_deb,
            "descripcion": texto(hoja.iat[fila, columnas["descripcion"]]),
            "factura": factura,
            "valor": a_entero(valor),
            "documento": documento,
            "documento_norm": normalizar_codigo(documento),
            "fecha": parse_fecha_dmy(hoja.iat[fila, columnas["fecha"]]),
            "hora": texto(hoja.iat[fila, columnas["hora"]]),
            "usuario": texto(hoja.iat[fila, columnas["usuario"]]),
            "designacion": texto(hoja.iat[fila, columnas["designacion"]]),
        })
    return ArchivoBordero(min(fechas), max(fechas), pd.DataFrame(filas))
