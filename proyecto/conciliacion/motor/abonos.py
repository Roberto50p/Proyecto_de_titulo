"""Cruce de los abonos Transbank (Total abono de cada archivo) con las líneas de la cartola."""

from datetime import date, timedelta

import pandas as pd

from ..lectores.comunes import clave
from . import categorias as c
from .mensajes import fecha, pesos
from .parametros import Parametros


def sumar_dias_habiles(dia: date, dias: int) -> date:
    actual = dia
    while dias > 0:
        actual += timedelta(days=1)
        if actual.weekday() < 5:
            dias -= 1
    return actual


def cuadratura_archivo(resumen: dict) -> int:
    """Diferencia entre el Total abono informado y el calculado desde el resumen (0 si cuadra)."""
    calculado = (resumen.get("total_ventas", 0) + resumen.get("devoluciones", 0) - resumen.get("descuentos", 0)
                 - resumen.get("comision", 0) - resumen.get("iva_comision", 0) - resumen.get("anulaciones", 0)
                 - resumen.get("cobros", 0) - resumen.get("iva_cobros", 0))
    return calculado - resumen.get("total_abono", 0)


def conciliar_abonos(abonos: list[dict], cartola: pd.DataFrame, cartola_rango: tuple[date, date],
                     params: Parametros) -> list[dict]:
    patrones = [clave(p) for p in params.patrones_cartola]
    # Cada línea recuerda su posición en la cartola para poder marcarla como usada.
    lineas = [
        {**l, "indice": i} for i, l in enumerate(cartola.to_dict("records"))
        if l["abono"] > 0 and any(p in clave(l["descripcion"]) for p in patrones)
    ]
    usadas: set[int] = set()
    resultados: dict[int, dict] = {}

    def ventana(a):
        hasta = sumar_dias_habiles(a["fecha_abono"], params.dias_holgura)
        return [i for i, l in enumerate(lineas) if i not in usadas and a["fecha_abono"] <= l["fecha"] <= hasta]

    def resultado(a, categoria, l=None, mensaje=""):
        return {**a, "categoria": categoria,
                "cartola_fecha": l["fecha"] if l else None,
                "cartola_descripcion": l["descripcion"] if l else "",
                "cartola_monto": l["abono"] if l else None,
                "cartola_indice": l["indice"] if l else None,
                "diferencia": a["total_abono"] - l["abono"] if l else None,
                "mensaje": mensaje}

    # 1) Montos que calzan (dentro de tolerancia), prefiriendo el mismo día.
    for n, a in enumerate(abonos):
        candidatas = [i for i in ventana(a) if abs(lineas[i]["abono"] - a["total_abono"]) <= params.tolerancia_clp]
        if candidatas:
            i = min(candidatas, key=lambda i: (lineas[i]["fecha"] - a["fecha_abono"]).days)
            usadas.add(i)
            resultados[n] = resultado(a, c.OK, lineas[i], "Abono encontrado en la cartola.")

    # 2) Lo que queda: cartola que no cubre la fecha, monto distinto o sin línea.
    medio = lambda a: c.ETIQUETA_MEDIO.get(a["medio"], a["medio"])
    for n, a in enumerate(abonos):
        if n in resultados:
            continue
        desde, hasta = cartola_rango
        if not (desde <= a["fecha_abono"] <= hasta):
            resultados[n] = resultado(a, c.ABONO_CARTOLA, mensaje=(
                f"La cartola no cubre el {fecha(a['fecha_abono'])} (cubre {fecha(desde)} a {fecha(hasta)}). "
                f"Cargar la cartola que incluya el abono de {medio(a)}."))
            continue
        candidatas = ventana(a)
        if candidatas:
            i = min(candidatas, key=lambda i: abs(lineas[i]["abono"] - a["total_abono"]))
            usadas.add(i)
            l = lineas[i]
            resultados[n] = resultado(a, c.ABONO_CARTOLA, l, (
                f"El abono de {medio(a)} del {fecha(a['fecha_abono'])} es {pesos(a['total_abono'])}, pero la cartola "
                f"registra {pesos(l['abono'])} el {fecha(l['fecha'])}. Revisar la liquidación con Transbank."))
        else:
            resultados[n] = resultado(a, c.ABONO_CARTOLA, mensaje=(
                f"No llegó a la cartola el abono de {medio(a)} del {fecha(a['fecha_abono'])} por "
                f"{pesos(a['total_abono'])}. Revisar con Transbank y el banco."))
    return [resultados[n] for n in range(len(abonos))]
