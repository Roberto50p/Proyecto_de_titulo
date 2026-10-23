"""Lector del reporte Transbank "Abonos por día" (débito, crédito o prepago)."""

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .comunes import (
    ArchivoNoReconocido,
    a_entero,
    buscar_celda,
    clave,
    es_vacio,
    fechas_es,
    leer_hoja,
    normalizar_codigo,
    parse_fecha_es,
    texto,
    valor_a_la_derecha,
)

MEDIOS_TEXTO = {"debito": "DEBITO", "credito": "CREDITO", "prepago": "PREPAGO"}

# Etiqueta del resumen (sin acentos, minúsculas) -> clave interna. Las devoluciones se suman.
ETIQUETAS_RESUMEN = {
    "total ventas (+)": "total_ventas",
    "devolucion comision por anulacion (+)": "devoluciones",
    "iva devolucion comision por anulacion (+)": "devoluciones",
    "descuentos aplicados (-)": "descuentos",
    "comision transbank (-)": "comision",
    "iva de comision transbank (-)": "iva_comision",
    "ventas anuladas (-)": "anulaciones",
    "cobros por servicio (-)": "cobros",
    "iva de cobros por servicio (-)": "iva_cobros",
    "total abono": "total_abono",
}

# Encabezado del detalle (sin acentos, minúsculas) -> columna interna.
COLUMNAS = {
    "fecha de venta": "fecha_venta",
    "tipo de movimiento": "tipo_movimiento",
    "codigo de comercio": "codigo_comercio",
    "nombre local": "nombre_local",
    "monto original de venta (+)": "monto_original",
    "monto vuelto": "monto_vuelto",
    "tipo de venta/cuota": "tipo_venta",
    "n° de cuota": "cuota",
    "monto venta valido para abono (+)": "monto_abono_valido",
    "comision transbank (-)": "comision",
    "iva comision transbank (-)": "iva_comision",
    "total abono (=)": "total_abono",
    "monto anulado (-)": "monto_anulado",
    "monto cobro por servicio (-)": "monto_cobro",
    "n° de tarjeta": "tarjeta",
    "codigo de autorizacion de venta": "codigo_autorizacion",
    "n° de boleta": "boleta",
}
MONTOS = ["monto_original", "monto_vuelto", "monto_abono_valido", "comision", "iva_comision",
          "total_abono", "monto_anulado", "monto_cobro"]


@dataclass
class ArchivoTransbank:
    medio: str
    moneda: str
    cuenta: str
    fecha_abono: date
    fecha_abono_hasta: date
    resumen: dict[str, int]
    ventas: pd.DataFrame = field(repr=False)


def _nombre_local(valor) -> str:
    """'RESTAURANT BRISTOL, AVENIDA ...' -> 'Restaurant Bristol'."""
    return texto(valor).split(",")[0].strip().title()


def _cuota(valor) -> tuple[int | None, int | None]:
    partes = texto(valor).split("/")
    if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
        return int(partes[0]), int(partes[1])
    return None, None


def _valor_bajo(hoja, etiqueta):
    pos = buscar_celda(hoja, etiqueta)
    if pos is None:
        return None
    fila, col = pos
    return hoja.iat[fila + 1, col] if fila + 1 < len(hoja) else None


def leer_transbank(archivo) -> ArchivoTransbank:
    hoja = leer_hoja(archivo)
    if buscar_celda(hoja, "Medio de pago:") is None or buscar_celda(hoja, "Monto original de venta") is None:
        raise ArchivoNoReconocido("No es un reporte Transbank 'Abonos por día'.")

    medio = MEDIOS_TEXTO.get(clave(_valor_bajo(hoja, "Medio de pago:")))
    if medio is None:
        raise ArchivoNoReconocido("No se reconoce el medio de pago del archivo Transbank.")
    moneda = texto(_valor_bajo(hoja, "Moneda:"))
    cuenta = texto(_valor_bajo(hoja, "Cuenta corriente:"))

    pos = buscar_celda(hoja, "Periodo de consulta")
    fechas = fechas_es(valor_a_la_derecha(hoja, *pos)) if pos else []
    if not fechas:
        raise ArchivoNoReconocido("No se encontró la fecha de abono (Periodo de consulta).")
    fecha_abono, fecha_hasta = min(fechas), max(fechas)

    fila_enc, _ = buscar_celda(hoja, "Monto original de venta")
    resumen = {k: 0 for k in set(ETIQUETAS_RESUMEN.values())}
    for fila in range(fila_enc):
        for col in range(hoja.shape[1]):
            k = ETIQUETAS_RESUMEN.get(clave(hoja.iat[fila, col]))
            if k:
                resumen[k] += a_entero(valor_a_la_derecha(hoja, fila, col))
                break

    # Encabezado en dos filas: grupo (fila anterior) y subcolumna.
    grupos = hoja.iloc[fila_enc - 1].ffill()
    nombres = []
    for col in range(hoja.shape[1]):
        sub = hoja.iat[fila_enc, col]
        nombres.append(COLUMNAS.get(clave(sub if not es_vacio(sub) else grupos.iloc[col])))

    filas = []
    for fila in range(fila_enc + 1, len(hoja)):
        registro = {n: hoja.iat[fila, c] for c, n in enumerate(nombres) if n}
        try:
            fecha_venta = parse_fecha_es(registro.get("fecha_venta"))
        except ValueError:
            continue
        cuota_num, cuota_total = _cuota(registro.get("cuota"))
        codigo = texto(registro.get("codigo_autorizacion"))
        filas.append({
            "fila": fila + 1,
            "fecha_venta": fecha_venta,
            "tipo_movimiento": texto(registro.get("tipo_movimiento")),
            "codigo_comercio": texto(registro.get("codigo_comercio")),
            "local": _nombre_local(registro.get("nombre_local")),
            **{m: a_entero(registro.get(m)) for m in MONTOS},
            "tipo_venta": texto(registro.get("tipo_venta")),
            "cuota_num": cuota_num,
            "cuota_total": cuota_total,
            "tarjeta": texto(registro.get("tarjeta")),
            "codigo_autorizacion": codigo,
            "codigo_norm": normalizar_codigo(codigo),
            "boleta": texto(registro.get("boleta")),
            "medio": medio,
        })

    ventas = pd.DataFrame(filas)
    if not ventas.empty:
        ventas["cuota_num"] = ventas["cuota_num"].astype("Int64")
        ventas["cuota_total"] = ventas["cuota_total"].astype("Int64")
    return ArchivoTransbank(medio, moneda, cuenta, fecha_abono, fecha_hasta, resumen, ventas)
