"""Reporte Excel de la conciliación en dólares: Resumen · Con falla · Conciliadas · Archivos."""

from io import BytesIO

from django.utils import timezone
from openpyxl import Workbook

from ..models import VentaDolar
from .excel import Hoja

DOLARES = "#,##0.00"
COLUMNAS_VENTA = ["Tarjeta", "Fecha venta", "Hora", "Código autorización", "Monto Transbank US$", "Documento ERP",
                  "Valor ERP $", "Cartera US$", "Diferencia US$", "Resultado", "Mensaje"]


def _tabla(h: Hoja, columnas, filas, dolares=(), **opciones):
    """Hoja.tabla con formato de dólares (con centavos) en las columnas `dolares`."""
    inicio = h.fila + 1
    h.tabla(columnas, filas, **opciones)
    for c in (columnas.index(t) + 1 for t in dolares):
        for f in range(inicio, inicio + len(filas)):
            h.ws.cell(f, c).number_format = DOLARES


def _ventas(h: Hoja, ventas):
    filas = [[v.get_tarjeta_display(), v.fecha_venta, v.hora, v.codigo_autorizacion, v.monto_original, v.documento,
              v.valor_erp, v.monto_cartera, v.diferencia, v.get_categoria_display(), v.mensaje] for v in ventas]
    _tabla(h, COLUMNAS_VENTA, filas, dolares=["Monto Transbank US$", "Cartera US$", "Diferencia US$"],
           montos=["Valor ERP $"], fechas=["Fecha venta"], filtro=True, congelar=True,
           anchos=[12, 12, 7, 16, 16, 14, 13, 13, 14, 26, 80])


def _hoja(libro, conc, nombre, titulo, color=None) -> Hoja:
    h = Hoja(libro, nombre, color)
    h.texto(titulo, negrita=True, tamano=14)
    h.texto(f"{conc.etiqueta} · en dólares · generado {timezone.localtime():%d/%m/%Y %H:%M}")
    h.salto()
    return h


def generar(conc) -> bytes:
    libro = Workbook()
    libro.remove(libro.active)
    ventas = list(conc.ventas_usd.all())
    r = conc.resumen

    h = _hoja(libro, conc, "Resumen", "Conciliación en dólares")
    columnas = ["Tarjeta", "N° ventas", "Con falla", "Ventas US$", "Conciliado US$", "En cartera US$", "Diferencia US$"]
    claves = ["n_ventas", "n_falla", "ventas", "conciliado", "cartera", "diferencia"]
    filas = [[n, *(r["tarjetas"][t][k] for k in claves)] for t, n in VentaDolar.TARJETAS if t in r["tarjetas"]]
    filas.append(["Total", *(r["total"][k] for k in claves)])
    _tabla(h, columnas, filas, dolares=columnas[3:], anchos=[16, 11, 11, 15, 15, 15, 15])
    h.texto("Abonos Transbank US$ contra la cartola", negrita=True, tamano=12)
    _tabla(h, ["Día de abono", "Abono US$", "En cartola", "Fecha cartola", "Mensaje"],
           [[a["fecha_abono"], float(a["monto"]), {True: "Sí", False: "No"}.get(a["en_cartola"], "Sin cartola"),
             a["cartola_fecha"] or "", a["mensaje"]] for a in r["abonos"]], dolares=["Abono US$"])

    _ventas(_hoja(libro, conc, "Con falla", "Ventas no ubicadas en el ERP o en la cartera", "#B42318"),
            [v for v in ventas if v.es_falla])
    _ventas(_hoja(libro, conc, "Conciliadas", "Ventas abonadas y diferencias", "#2F7D4F"),
            [v for v in ventas if not v.es_falla])

    h = _hoja(libro, conc, "Archivos", "Archivos procesados")
    h.tabla(["Archivo", "Tipo", "Detalle", "Desde", "Hasta", "Día de abono", "Filas", "SHA-256"],
            [[a.nombre, a.get_tipo_display(), a.banco or a.moneda, a.desde, a.hasta, a.fecha_abono, a.filas,
              a.sha256[:16]] for a in conc.archivos.all()],
            fechas=["Desde", "Hasta", "Día de abono"], anchos=[34, 24, 22, 12, 12, 12, 8, 18])

    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()
