"""Motor de la conciliación en dólares (funciones puras, sin base de datos).

Por cada venta del abono Transbank US$:
1. Se busca su código de autorización en el ERP (pagos "US$"), que da el documento y el valor cobrado en pesos.
2. Se busca ese documento en la cartera de su tarjeta; calza si el valor ERP es el "Saldo" o el "Saldo Corregido".
3. La diferencia es el monto Transbank menos el "Otra Moneda" (dólares) de la cartera.
Además, cada "Abono Calculado" del archivo Transbank se busca, por monto exacto, entre los abonos de la cartola US$.
"""

from datetime import date
from decimal import Decimal

import pandas as pd

from .mensajes import dolares, pesos
from .mensajes import fecha as fmt_fecha

OK, SIN_ERP, SIN_CARTERA, SALDO_DISTINTO = "OK", "SIN_ERP", "SIN_CARTERA", "SALDO_DISTINTO"
TARJETAS = {"AX": "Amex", "DI": "Diners", "VI": "Visa", "MC": "Mastercard"}
SALDOS = {"saldo": "Saldo", "saldo_corregido": "Saldo Corregido"}


def _sin_dato(valor) -> bool:
    return valor is None or (not isinstance(valor, Decimal) and pd.isna(valor))


def conciliar_ventas_dolar(ventas: pd.DataFrame, erp: pd.DataFrame, carteras: dict[str, pd.DataFrame]) -> list[dict]:
    """Un resultado por venta (en el mismo orden): documento, valor_erp, monto_cartera, diferencia, categoria y
    mensaje. `carteras` es tarjeta (AX/DI/VI/MC) -> documentos de su cartera."""
    por_codigo = {}
    for pago in erp.to_dict("records"):
        por_codigo.setdefault(pago["codigo_norm"], pago)  # el primero, como el proceso original
    resultados = []
    for v in ventas.to_dict("records"):
        marca, codigo = TARJETAS[v["tarjeta"]], v["codigo_autorizacion"]
        r = {"documento": "", "valor_erp": None, "monto_cartera": None, "diferencia": None}
        pago = por_codigo.get(v["codigo_norm"]) if v["codigo_norm"] else None
        if pago is None:
            resultados.append(r | {"categoria": SIN_ERP, "mensaje": (
                f"El código {codigo} ({marca}, {dolares(v['monto_original'])} del {fmt_fecha(v['fecha_venta'])}) no "
                "está en el ERP. Verificar si el pago se registró en el hotel o con otro código.")})
            continue
        documento, valor = pago["documento"], pago["valor"]
        r |= {"documento": documento, "valor_erp": valor}
        cartera = carteras.get(v["tarjeta"])
        filas = [] if cartera is None else cartera[cartera.documento == documento].to_dict("records")
        calza = next(((f, col) for f in filas for col in SALDOS if not _sin_dato(f[col]) and f[col] == valor), None)
        if calza is None:
            if filas:
                detalle = (f"está en la cartera de {marca}, pero ningún saldo coincide con el valor ERP {pesos(valor)}. "
                           "Revisar el cobro.")
            else:
                detalle = (f"({pesos(valor)}) no está en la cartera de {marca}. Revisar si ya se pagó o se registró con "
                           "otra tarjeta.")
            resultados.append(r | {"categoria": SALDO_DISTINTO if filas else SIN_CARTERA,
                                   "mensaje": f"El documento {documento} del ERP {detalle}"})
            continue
        fila, col = calza
        otra = None if _sin_dato(fila["otra_moneda"]) else fila["otra_moneda"]
        diferencia = None if otra is None else v["monto_original"] - otra
        resultados.append(r | {"monto_cartera": otra, "diferencia": diferencia, "categoria": OK, "mensaje": (
            f"Documento {documento}: el valor ERP {pesos(valor)} coincide con el {SALDOS[col]} de la cartera de "
            f"{marca}; la cartera registra {dolares(otra)} (diferencia {dolares(diferencia)}).")})
    return resultados


def verificar_abono(monto: Decimal, fecha_abono: date, movimientos: pd.DataFrame) -> dict:
    """Busca el abono en la cartola por monto exacto; prefiere el primero desde el día de abono."""
    candidatos = [] if movimientos.empty else movimientos[movimientos.abono == monto].to_dict("records")
    candidatos.sort(key=lambda m: (m["fecha"] < fecha_abono, m["fecha"]))
    m = candidatos[0] if candidatos else None
    if m:
        mensaje = f"El abono de {dolares(monto)} llegó a la cartola el {fmt_fecha(m['fecha'])} ({m['descripcion']})."
    else:
        mensaje = (f"El abono de {dolares(monto)} del {fmt_fecha(fecha_abono)} no aparece con ese monto exacto en la "
                   "cartola US$ cargada.")
        del_dia = [] if movimientos.empty else [x for x in movimientos.to_dict("records")
                                                if x["fecha"] == fecha_abono and x["abono"] > 0]
        if del_dia:
            cerca = min(del_dia, key=lambda x: abs(x["abono"] - monto))
            mensaje += (f" El abono más cercano de ese día es {dolares(cerca['abono'])} ({cerca['descripcion']}, "
                        f"diferencia {dolares(monto - cerca['abono'])}).")
    return {
        "monto": str(monto), "fecha_abono": fecha_abono.isoformat(), "en_cartola": m is not None,
        "cartola_fecha": m["fecha"].isoformat() if m else None, "cartola_descripcion": m["descripcion"] if m else "",
        "mensaje": mensaje,
    }
