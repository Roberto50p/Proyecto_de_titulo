"""Lector de la cartola del Banco de Chile (movimientos de cuenta corriente)."""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .comunes import (
    ArchivoNoReconocido,
    a_entero,
    buscar_celda,
    clave,
    leer_hoja,
    parse_fecha_dmy,
    texto,
    valor_a_la_derecha,
)

ENCABEZADOS = {
    "fecha": "fecha", "descripcion": "descripcion", "canal o sucursal": "canal",
    "nro. docto.": "nro_docto", "cargos": "cargo", "abonos": "abono", "saldo": "saldo",
}


@dataclass
class ArchivoCartola:
    cuenta: str
    moneda: str
    desde: date
    hasta: date
    movimientos: pd.DataFrame = field(repr=False)


def _fila_encabezado(hoja) -> int | None:
    for fila in range(len(hoja)):
        valores = {clave(v) for v in hoja.iloc[fila]}
        if "fecha" in valores and "descripcion" in valores:
            return fila
    return None


def leer_cartola(archivo) -> ArchivoCartola:
    hoja = leer_hoja(archivo)
    fila_enc = _fila_encabezado(hoja)
    pos_cuenta = buscar_celda(hoja, "Cuenta N")
    if fila_enc is None or pos_cuenta is None:
        raise ArchivoNoReconocido("No es una cartola bancaria (faltan 'Cuenta N°' o la tabla de movimientos).")
    cuenta = texto(valor_a_la_derecha(hoja, *pos_cuenta))
    pos_moneda = buscar_celda(hoja, "Moneda:")
    moneda = texto(valor_a_la_derecha(hoja, *pos_moneda)) if pos_moneda else ""

    columnas = {}
    for col in range(hoja.shape[1]):
        k = clave(hoja.iat[fila_enc, col]).split(" (")[0]
        if k in ENCABEZADOS and ENCABEZADOS[k] not in columnas:
            columnas[ENCABEZADOS[k]] = col

    filas = []
    for fila in range(fila_enc + 1, len(hoja)):
        try:
            fecha = parse_fecha_dmy(hoja.iat[fila, columnas["fecha"]])
        except (ValueError, TypeError):
            continue
        filas.append({
            "fila": fila + 1,
            "fecha": fecha,
            "descripcion": texto(hoja.iat[fila, columnas["descripcion"]]),
            "canal": texto(hoja.iat[fila, columnas["canal"]]) if "canal" in columnas else "",
            "nro_docto": texto(hoja.iat[fila, columnas["nro_docto"]]) if "nro_docto" in columnas else "",
            "cargo": a_entero(hoja.iat[fila, columnas["cargo"]]),
            "abono": a_entero(hoja.iat[fila, columnas["abono"]]),
            "saldo": a_entero(hoja.iat[fila, columnas["saldo"]]),
        })
    movimientos = pd.DataFrame(filas)
    if movimientos.empty:
        raise ArchivoNoReconocido("La cartola no tiene movimientos.")
    return ArchivoCartola(cuenta, moneda, movimientos.fecha.min(), movimientos.fecha.max(), movimientos)
