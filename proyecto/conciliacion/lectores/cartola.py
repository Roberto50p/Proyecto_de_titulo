"""Lector de la cartola bancaria (movimientos de cuenta corriente).

Formatos reconocidos:
- Banco de Chile: una hoja con cabecera ("Cuenta N°", "Moneda:") y la tabla de movimientos debajo.
- BancoEstado "Cartola Histórica": hoja "Resumen" (N° Cuenta Corriente, Fecha Inicio/Final, saldos en $)
  y hoja "Movimientos" con la tabla.
"""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .comunes import (
    ArchivoNoReconocido,
    a_entero,
    buscar_celda,
    clave,
    leer_libro,
    parse_fecha_dmy,
    texto,
    valor_a_la_derecha,
)

BANCO_DE_CHILE = "Banco de Chile"
BANCOESTADO = "BancoEstado"

# Encabezado (sin acentos, minúsculas, sin "(CLP)") -> columna interna. Incluye los nombres de ambos bancos.
ENCABEZADOS = {
    "fecha": "fecha", "descripcion": "descripcion",
    "canal o sucursal": "canal", "sucursal": "canal",
    "nro. docto.": "nro_docto", "n° operacion": "nro_docto",
    "cargos": "cargo", "cheques / cargos": "cargo",
    "abonos": "abono", "depositos / abonos": "abono",
    "saldo": "saldo",
}


@dataclass
class ArchivoCartola:
    banco: str
    cuenta: str
    moneda: str
    desde: date
    hasta: date
    movimientos: pd.DataFrame = field(repr=False)


def es_bancoestado(hoja: pd.DataFrame) -> bool:
    return buscar_celda(hoja, "Cartola Histórica") is not None and buscar_celda(hoja, "N° Cuenta Corriente") is not None


def _fila_encabezado(hoja) -> int | None:
    for fila in range(len(hoja)):
        valores = {clave(v) for v in hoja.iloc[fila]}
        if "fecha" in valores and "descripcion" in valores:
            return fila
    return None


def _movimientos(hoja: pd.DataFrame, fila_enc: int) -> pd.DataFrame:
    columnas = {}
    for col in range(hoja.shape[1]):
        k = clave(hoja.iat[fila_enc, col]).split(" (")[0]
        if k in ENCABEZADOS and ENCABEZADOS[k] not in columnas:
            columnas[ENCABEZADOS[k]] = col
    faltan = {"fecha", "descripcion", "cargo", "abono", "saldo"} - set(columnas)
    if faltan:
        raise ArchivoNoReconocido(f"A la tabla de movimientos de la cartola le faltan columnas: {', '.join(sorted(faltan))}.")

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
    return movimientos


def _banco_de_chile(hoja: pd.DataFrame) -> ArchivoCartola:
    fila_enc = _fila_encabezado(hoja)
    pos_cuenta = buscar_celda(hoja, "Cuenta N")
    if fila_enc is None or pos_cuenta is None:
        raise ArchivoNoReconocido("No es una cartola bancaria (faltan 'Cuenta N°' o la tabla de movimientos).")
    cuenta = texto(valor_a_la_derecha(hoja, *pos_cuenta))
    pos_moneda = buscar_celda(hoja, "Moneda:")
    moneda = texto(valor_a_la_derecha(hoja, *pos_moneda)) if pos_moneda else ""
    movimientos = _movimientos(hoja, fila_enc)
    return ArchivoCartola(BANCO_DE_CHILE, cuenta, moneda, movimientos.fecha.min(), movimientos.fecha.max(), movimientos)


def _bancoestado(libro: dict[str, pd.DataFrame]) -> ArchivoCartola:
    resumen = next(iter(libro.values()))

    def dato(etiqueta):
        pos = buscar_celda(resumen, etiqueta)
        return valor_a_la_derecha(resumen, *pos) if pos else None

    tablas = [(h, f) for h in libro.values() if (f := _fila_encabezado(h)) is not None]
    if not tablas:
        raise ArchivoNoReconocido("La cartola de BancoEstado no trae la hoja 'Movimientos'.")
    movimientos = _movimientos(*tablas[0])
    # La cartola no informa la moneda; los saldos de una cuenta en pesos vienen como "$144.501.293".
    moneda = "Pesos" if texto(dato("Saldo Inicial")).startswith("$") else "No informada"
    try:
        desde, hasta = parse_fecha_dmy(dato("Fecha Inicio")), parse_fecha_dmy(dato("Fecha Final"))
    except (ValueError, TypeError):
        desde, hasta = movimientos.fecha.min(), movimientos.fecha.max()
    return ArchivoCartola(BANCOESTADO, texto(dato("N° Cuenta Corriente")), moneda, desde, hasta, movimientos)


def leer_cartola(archivo) -> ArchivoCartola:
    libro = leer_libro(archivo)
    primera = next(iter(libro.values()))
    if es_bancoestado(primera):
        return _bancoestado(libro)
    return _banco_de_chile(primera)
