"""Cruce venta a venta entre Transbank y el bordero, y clasificación de cada venta.

Precedencia (gana la primera que aplica):
  DATO_INVALIDO → cruce exacto por código [DIF_MONTO | MEDIO_DISTINTO | OK]
  → cruce por error de digitación (DIGITACION)
  → sin cruce: CUOTA (cuota fuera de cobertura) | FUERA_PERIODO | SIN_BORDERO
"""

from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher

import pandas as pd

from . import categorias as c
from .mensajes import fecha, mensaje, pesos
from .parametros import Parametros

COLUMNAS_SALIDA = ["venta_id", "categoria", "pago_id", "monto_bordero", "diferencia",
                   "codigo_sugerido", "nota", "mensaje"]


def pagos_tarjeta(movimientos: pd.DataFrame, params: Parametros) -> pd.DataFrame:
    """Filas del bordero que son medios de pago con tarjeta; las de monto positivo son reversas (inválidas)."""
    if movimientos.empty:
        return movimientos.assign(invalido=pd.Series(dtype=bool))
    tarjetas = movimientos[movimientos.cod_deb.isin(params.equivalencias.keys())].copy()
    tarjetas["invalido"] = tarjetas.valor >= 0
    return tarjetas


def _cubierta(dia: date, cobertura: list[tuple[date, date]]) -> bool:
    return any(desde <= dia <= hasta for desde, hasta in cobertura)


def _vacio(valor) -> bool:
    return valor is None or (not isinstance(valor, str) and pd.isna(valor))


def conciliar_ventas(ventas: pd.DataFrame, pagos: pd.DataFrame,
                     cobertura: list[tuple[date, date]], params: Parametros) -> pd.DataFrame:
    pagos_por_id = {p["id"]: p for p in pagos.to_dict("records")} if not pagos.empty else {}
    por_codigo = defaultdict(list)
    por_fecha = defaultdict(list)
    for p in pagos_por_id.values():
        if p["documento_norm"]:
            por_codigo[p["documento_norm"]].append(p["id"])
        por_fecha[p["fecha"]].append(p["id"])
    usados: set = set()
    resultados: dict = {}
    registros = ventas.to_dict("records")

    def contexto(v, p=None) -> dict:
        cuota = "" if _vacio(v.get("cuota_num")) else f"{int(v['cuota_num'])}/{int(v['cuota_total'])}"
        return {
            "codigo": v["codigo_autorizacion"] or "(vacío)",
            "monto_tbk": pesos(v["monto_original"]),
            "fecha_venta": fecha(v["fecha_venta"]),
            "local": v.get("local", ""),
            "medio": c.ETIQUETA_MEDIO.get(v["medio"], v["medio"]),
            "cuota": cuota,
            "monto_bordero": pesos(abs(p["valor"])) if p else "-",
            "fecha_bordero": fecha(p["fecha"]) if p else "-",
            "sugerido": p["documento"] if p else "",
            "cod_deb": p["cod_deb"] if p else "",
            "diferencia": pesos(v["monto_original"] - abs(p["valor"])) if p else "-",
        }

    def notas(v, p=None) -> str:
        partes = []
        if not _vacio(v.get("cuota_num")):
            partes.append(f"Cuota {int(v['cuota_num'])}/{int(v['cuota_total'])}")
        if p is not None and p.get("pendiente_mes"):
            partes.append(f"cierra pendiente de {p['pendiente_mes']}")
        return "; ".join(partes)

    def guardar(v, categoria, p=None, sugerido=None):
        dif = v["monto_original"] - abs(p["valor"]) if p else None
        resultados[v["id"]] = {
            "venta_id": v["id"], "categoria": categoria,
            "pago_id": p["id"] if p else None,
            "monto_bordero": abs(p["valor"]) if p else None,
            "diferencia": dif, "codigo_sugerido": sugerido, "nota": notas(v, p),
            "mensaje": mensaje(categoria, **contexto(v, p)),
        }
        if p:
            usados.add(p["id"])

    # 1) Datos inválidos.
    for v in registros:
        if not v["codigo_norm"] or v["monto_original"] <= 0:
            resultados[v["id"]] = {
                "venta_id": v["id"], "categoria": c.DATO_INVALIDO, "pago_id": None, "monto_bordero": None,
                "diferencia": None, "codigo_sugerido": None, "nota": notas(v),
                "mensaje": mensaje(c.DATO_INVALIDO, detalle=(
                    "Venta Transbank sin código de autorización o con monto cero; no se puede conciliar.")),
            }

    # 2) Cruce exacto por código normalizado, dentro de la ventana de días.
    for v in registros:
        if v["id"] in resultados:
            continue
        candidatos = [pagos_por_id[i] for i in por_codigo.get(v["codigo_norm"], []) if i not in usados]
        candidatos = [p for p in candidatos if abs((p["fecha"] - v["fecha_venta"]).days) <= params.ventana_dias]
        if not candidatos:
            continue
        p = min(candidatos, key=lambda p: (abs(v["monto_original"] - abs(p["valor"])),
                                           abs((p["fecha"] - v["fecha_venta"]).days)))
        if abs(v["monto_original"] - abs(p["valor"])) > params.tolerancia_clp:
            guardar(v, c.DIF_MONTO, p)
        elif v["medio"] not in params.medios_de(p["cod_deb"]):
            guardar(v, c.MEDIO_DISTINTO, p)
        else:
            guardar(v, c.OK, p)

    # 3) Error de digitación: misma fecha, medio compatible, mismo monto y código parecido.
    for v in registros:
        if v["id"] in resultados:
            continue
        mejor, mejor_ratio = None, params.umbral_similitud
        for i in por_fecha.get(v["fecha_venta"], []):
            p = pagos_por_id[i]
            if i in usados or not p["documento_norm"]:
                continue
            if v["medio"] not in params.medios_de(p["cod_deb"]):
                continue
            if abs(v["monto_original"] - abs(p["valor"])) > params.tolerancia_clp:
                continue
            ratio = SequenceMatcher(None, v["codigo_norm"], p["documento_norm"]).ratio()
            if ratio >= mejor_ratio:
                mejor, mejor_ratio = p, ratio
        if mejor is not None:
            guardar(v, c.DIGITACION, mejor, sugerido=mejor["documento"])

    # 4) Sin cruce.
    for v in registros:
        if v["id"] in resultados:
            continue
        cubierta = _cubierta(v["fecha_venta"], cobertura)
        if not cubierta and not _vacio(v.get("cuota_num")):
            guardar(v, c.CUOTA)
        elif not cubierta:
            guardar(v, c.FUERA_PERIODO)
        else:
            guardar(v, c.SIN_BORDERO)

    return pd.DataFrame([resultados[v["id"]] for v in registros], columns=COLUMNAS_SALIDA)
