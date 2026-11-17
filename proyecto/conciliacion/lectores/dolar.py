"""Lectores de la conciliación en dólares.

- Abono Transbank US$: resumen ("Día de Abono", "Abono Calculado (=)") y detalle de ventas por tarjeta (AX/DI/VI/MC).
- ERP de tarjetas: sin encabezados; cada fila es un pago con su documento, valor en pesos y código de autorización.
- Cartera de la tarjeta ("Posición Por Clientes" de Contas a Receber): documentos con su valor en dólares
  ("Otra Moneda") y en pesos ("Saldo" o "Saldo Corregido"), uno por tarjeta (Amex, Diners, Visa, Mastercard).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pandas as pd

from .comunes import (
    ArchivoNoReconocido,
    a_decimal,
    a_entero,
    buscar_celda,
    clave,
    es_vacio,
    leer_hoja,
    normalizar_codigo,
    parse_fecha_dmy,
    texto,
    valor_a_la_derecha,
)

# Palabra en el nombre del cliente de la cartera -> código de tarjeta del abono Transbank.
MARCAS = {"amex": "AX", "dinners": "DI", "diners": "DI", "visa": "VI", "master": "MC"}
# Descripciones del ERP (columna "Amex US$", "Visa $", ...); sirven para reconocer el archivo.
DESCRIPCIONES_ERP = {"amex us$", "amex $", "dinners us$", "diners us$", "visa us$", "visa $", "master card us$",
                     "master card $", "red compra"}

COLUMNAS_ABONO = {
    "tipo transaccion": "tipo", "fecha venta": "fecha_venta", "tipo tarjeta": "tarjeta",
    "monto original venta": "monto_original", "codigo autorizacion venta": "codigo_autorizacion",
    "monto para abono": "monto_abono", "comision e iva comision": "comision",
}
RESUMEN_ABONO = {"ventas (+)": "ventas", "comision (-)": "comision", "iva comision (-)": "iva_comision",
                 "abono calculado (=)": "abono"}
# Columnas fijas del ERP (0 = A): documento, descripción, valor en pesos, código de autorización, fecha.
ERP_DOCUMENTO, ERP_DESCRIPCION, ERP_VALOR, ERP_CODIGO, ERP_FECHA = 3, 5, 8, 9, 10


@dataclass
class ArchivoAbonoDolar:
    moneda: str
    cuenta: str
    fecha_abono: date
    resumen: dict[str, Decimal]
    ventas: pd.DataFrame = field(repr=False)


@dataclass
class ArchivoCartera:
    marca: str  # AX, DI, VI o MC
    documentos: pd.DataFrame = field(repr=False)  # documento, otra_moneda, saldo, saldo_corregido


def es_abono_dolar(hoja) -> bool:
    return buscar_celda(hoja, "Abono Calculado") is not None and buscar_celda(hoja, "Día de Abono") is not None


def es_cartera(hoja) -> bool:
    return buscar_celda(hoja, "Posición Por Clientes") is not None


def es_erp(hoja) -> bool:
    if hoja.shape[1] <= ERP_FECHA:
        return False
    return any(clave(v) in DESCRIPCIONES_ERP for v in hoja.iloc[:, ERP_DESCRIPCION])


def _dato(hoja, etiqueta):
    pos = buscar_celda(hoja, etiqueta)
    return valor_a_la_derecha(hoja, *pos) if pos else None


def leer_abono_dolar(archivo) -> ArchivoAbonoDolar:
    hoja = leer_hoja(archivo)
    pos_enc = buscar_celda(hoja, "Tipo Transacción")
    if not es_abono_dolar(hoja) or pos_enc is None:
        raise ArchivoNoReconocido("No es un abono Transbank en dólares (faltan 'Día de Abono' o el detalle de ventas).")
    try:
        fecha_abono = parse_fecha_dmy(_dato(hoja, "Día de Abono"))
    except (ValueError, TypeError) as exc:
        raise ArchivoNoReconocido("No se reconoce el 'Día de Abono' del archivo Transbank US$.") from exc
    fila_enc = pos_enc[0]
    resumen = {k: Decimal(0) for k in RESUMEN_ABONO.values()}
    for fila in range(fila_enc):
        for col in range(hoja.shape[1]):
            k = RESUMEN_ABONO.get(clave(hoja.iat[fila, col]).rstrip(":"))
            if k:
                resumen[k] = a_decimal(valor_a_la_derecha(hoja, fila, col))
                break

    columnas = {COLUMNAS_ABONO[k]: c for c in range(hoja.shape[1])
                if (k := clave(hoja.iat[fila_enc, c])) in COLUMNAS_ABONO}
    faltan = set(COLUMNAS_ABONO.values()) - set(columnas)
    if faltan:
        raise ArchivoNoReconocido(f"Al detalle del abono Transbank US$ le faltan columnas: {', '.join(sorted(faltan))}.")
    filas = []
    for fila in range(fila_enc + 1, len(hoja)):
        celda = {k: hoja.iat[fila, c] for k, c in columnas.items()}
        tarjeta = texto(celda["tarjeta"]).upper()
        if clave(celda["tipo"]) != "venta" or tarjeta not in MARCAS.values() or es_vacio(celda["fecha_venta"]):
            continue
        momento = pd.Timestamp(celda["fecha_venta"])
        codigo = texto(celda["codigo_autorizacion"])
        filas.append({
            "fila": fila + 1, "tarjeta": tarjeta, "fecha_venta": momento.date(), "hora": momento.strftime("%H:%M"),
            "codigo_autorizacion": codigo, "codigo_norm": normalizar_codigo(codigo),
            "monto_original": a_decimal(celda["monto_original"]), "monto_abono": a_decimal(celda["monto_abono"]),
            "comision": a_decimal(celda["comision"]),
        })
    return ArchivoAbonoDolar(texto(_dato(hoja, "Moneda:")), texto(_dato(hoja, "Número:")), fecha_abono, resumen,
                             pd.DataFrame(filas))


def leer_cartera(archivo) -> ArchivoCartera:
    hoja = leer_hoja(archivo)
    pos_enc = buscar_celda(hoja, "Documento")
    if not es_cartera(hoja) or pos_enc is None:
        raise ArchivoNoReconocido("No es una cartera 'Posición Por Clientes' de tarjetas.")
    cliente = clave(_dato(hoja, "Cliente:"))
    marca = next((m for palabra, m in MARCAS.items() if palabra in cliente), None)
    if marca is None:
        raise ArchivoNoReconocido(f"No se reconoce la tarjeta de la cartera (cliente: {cliente or 'vacío'}).")
    fila_enc = pos_enc[0]
    nombres = {"documento": "documento", "otra moneda": "otra_moneda", "saldo": "saldo",
               "saldo corregido": "saldo_corregido"}
    columnas = {nombres[k]: c for c in range(hoja.shape[1]) if (k := clave(hoja.iat[fila_enc, c])) in nombres}
    if len(columnas) < len(nombres):
        raise ArchivoNoReconocido("A la cartera le faltan columnas (Documento, Otra Moneda, Saldo, Saldo Corregido).")
    filas = []
    for fila in range(fila_enc + 1, len(hoja)):
        documento = texto(hoja.iat[fila, columnas["documento"]])
        if not documento.isdigit():  # subtotales, pies de página y encabezados repetidos
            continue
        filas.append({"fila": fila + 1, "documento": documento,
                      **{k: None if es_vacio(hoja.iat[fila, c]) else a_decimal(hoja.iat[fila, c])
                         for k, c in columnas.items() if k != "documento"}})
    return ArchivoCartera(marca, pd.DataFrame(filas, columns=["fila", "documento", "otra_moneda", "saldo",
                                                              "saldo_corregido"]))


def leer_erp(archivo) -> pd.DataFrame:
    """Pagos con tarjeta en dólares del ERP (descripción con "US$"): documento, valor en pesos y código."""
    hoja = leer_hoja(archivo)
    if not es_erp(hoja):
        raise ArchivoNoReconocido("No es el reporte de tarjetas del ERP.")
    filas = []
    for fila in range(len(hoja)):
        descripcion = texto(hoja.iat[fila, ERP_DESCRIPCION])
        codigo = texto(hoja.iat[fila, ERP_CODIGO])
        if "US$" not in descripcion.upper() or not codigo:
            continue
        try:
            fecha = parse_fecha_dmy(hoja.iat[fila, ERP_FECHA])
        except (ValueError, TypeError):
            fecha = None
        filas.append({"fila": fila + 1, "documento": texto(hoja.iat[fila, ERP_DOCUMENTO]), "descripcion": descripcion,
                      "valor": abs(a_entero(hoja.iat[fila, ERP_VALOR])), "codigo_autorizacion": codigo,
                      "codigo_norm": normalizar_codigo(codigo), "fecha": fecha})
    return pd.DataFrame(filas, columns=["fila", "documento", "descripcion", "valor", "codigo_autorizacion",
                                        "codigo_norm", "fecha"])
