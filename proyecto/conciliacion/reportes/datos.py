"""Arma los datos del reporte (estructura 'opción C') a partir de lo guardado en la base."""

from django.utils import timezone

from ..models import ArchivoCargado, Conciliacion, PagoBordero
from ..motor import categorias as cat
from ..servicio import cartola_sin_archivo, periodo_ventas, utilizables

EMPRESA = "HOTELERA SAN FRANCISCO S.A."
DEPARTAMENTO = "Depto. Adm. y Finanzas"
RUT = "99.511.100-4"
AVISOS = {cat.FUERA_PERIODO, cat.CUOTA, cat.MEDIO_DISTINTO}


def _orden(v):
    return (cat.GRAVEDAD.get(cat.TIPO.get(v.categoria, ""), 9), cat.ORDEN_CATEGORIAS.index(v.categoria),
            v.fecha_venta, v.codigo_autorizacion)


def _invalidos_del_periodo(conc: Conciliacion) -> list:
    """Reversas del bordero dentro del período de las ventas Transbank (no todo el histórico del bordero)."""
    invalidos = PagoBordero.objects.filter(archivos__conciliacion=conc, invalido=True)
    desde, hasta = periodo_ventas(conc)
    if desde:
        invalidos = invalidos.filter(fecha__range=(desde, hasta))
    return list(invalidos.distinct())


def armar(conc: Conciliacion) -> dict:
    resumen = conc.resumen or {}
    medios = resumen.get("medios", {})
    cartola = next((a for a in utilizables(conc) if a.tipo == ArchivoCargado.CARTOLA), None)

    resumen_medios = []
    for m in cat.MEDIOS:
        r = medios.get(m, {})
        resumen_medios.append({"medio": m, "etiqueta": cat.ETIQUETA_MEDIO[m], "color": cat.COLOR_MEDIO[m], **r})

    matriz = []
    for k in cat.ORDEN_CATEGORIAS:
        celdas = resumen.get("matriz", {}).get(k, {})
        fila = {"categoria": k, "etiqueta": cat.ETIQUETA[k], "tipo": cat.TIPO[k],
                "celdas": [{"medio": m, **celdas.get(m, {"n": 0, "monto": 0})} for m in cat.MEDIOS]}
        fila["total_n"] = sum(c["n"] for c in fila["celdas"])
        fila["total_monto"] = sum(c["monto"] for c in fila["celdas"])
        matriz.append(fila)

    ventas = list(conc.ventas.select_related("pago"))
    capitulos = {}
    for m in cat.MEDIOS:
        del_medio = [v for v in ventas if v.medio == m]
        capitulos[m] = {
            "medio": m, "etiqueta": cat.ETIQUETA_MEDIO[m], "color": cat.COLOR_MEDIO[m],
            "resumen": next(r for r in resumen_medios if r["medio"] == m),
            "fallas": sorted([v for v in del_medio if v.es_venta and v.es_falla], key=_orden),
            "avisos": sorted([v for v in del_medio if v.es_venta and v.categoria in AVISOS], key=_orden),
            "conciliados": [v for v in del_medio if v.es_venta and v.categoria == cat.OK],
            "otros": [v for v in del_medio if not v.es_venta],
            "abonos": list(conc.abonos.filter(medio=m)),
        }

    return {
        "conciliacion": conc,
        "encabezado": {
            "empresa": EMPRESA, "departamento": DEPARTAMENTO, "rut": RUT,
            "titulo": conc.etiqueta,
            "subtitulo": "Cierre por fecha de abono",
            "cuenta": f"{cartola.banco} {cartola.cuenta}".strip() if cartola else "Sin cartola",
            "generado": timezone.localtime(),
            "procesada_en": conc.procesada_en,
        },
        "resumen_medios": resumen_medios,
        "total": resumen.get("total", {}),
        "matriz": matriz,
        "capitulos": capitulos,
        "cuotas": sorted([v for v in ventas if v.cuota_num], key=lambda v: (v.fecha_venta, v.codigo_autorizacion)),
        "parametros": conc.parametros,
        "archivos": list(conc.archivos.all()),
        "invalidos_bordero": _invalidos_del_periodo(conc),
        "cartola_sin_archivo": cartola_sin_archivo(conc),
        "cuadra": all(r.get("cuadratura", 0) == 0 for r in resumen_medios),
    }
