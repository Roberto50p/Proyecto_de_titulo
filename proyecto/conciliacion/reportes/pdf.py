"""Reporte PDF (ReportLab): resumen, matriz, un capítulo por medio de pago, pendientes y parámetros."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from xml.sax.saxutils import escape

from ..motor import categorias as cat
from .datos import armar

TINTA = colors.HexColor("#1B2430")
SUAVE = colors.HexColor("#4A5565")
LINEA = colors.HexColor("#D6DCE3")
FONDO_ENC = colors.HexColor("#EEF1F5")
TIPO_COLOR = {"Operación": "#B42318", "Dato": "#6B3FA0", "Pendiente": "#475467", "Aviso": "#5B6675",
              "OK": "#2F7D4F"}

_base = getSampleStyleSheet()
E = {
    "normal": ParagraphStyle("normal", parent=_base["Normal"], fontName="Helvetica", fontSize=9, leading=12,
                             textColor=TINTA),
    "chico": ParagraphStyle("chico", parent=_base["Normal"], fontName="Helvetica", fontSize=7.5, leading=9.5,
                            textColor=TINTA),
    "suave": ParagraphStyle("suave", parent=_base["Normal"], fontName="Helvetica", fontSize=9, leading=12,
                            textColor=SUAVE),
    "titulo": ParagraphStyle("titulo", parent=_base["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22,
                             alignment=0, textColor=TINTA, spaceAfter=2),
    "h2": ParagraphStyle("h2", parent=_base["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16,
                         textColor=TINTA, spaceBefore=6, spaceAfter=6),
    "h3": ParagraphStyle("h3", parent=_base["Heading3"], fontName="Helvetica-Bold", fontSize=10.5, leading=13,
                         textColor=TINTA, spaceBefore=6, spaceAfter=4),
    "num": ParagraphStyle("num", parent=_base["Normal"], fontName="Helvetica", fontSize=8, alignment=TA_RIGHT),
}


def pesos(valor) -> str:
    if valor is None or valor == "":
        return "-"
    signo = "-" if valor < 0 else ""
    return f"{signo}${abs(int(valor)):,}".replace(",", ".")


def entero(valor) -> str:
    return f"{int(valor or 0):,}".replace(",", ".")


def _estilo_tabla(n_filas, numericas=(), total=False):
    estilo = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), SUAVE),
        ("BACKGROUND", (0, 0), (-1, 0), FONDO_ENC),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for c in numericas:
        estilo.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if total:
        estilo += [("FONTNAME", (0, n_filas - 1), (-1, n_filas - 1), "Helvetica-Bold"),
                   ("LINEABOVE", (0, n_filas - 1), (-1, n_filas - 1), 1, TINTA)]
    return estilo


def _tabla(filas, anchos, numericas=(), total=False, extra=()):
    t = Table(filas, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle(_estilo_tabla(len(filas), numericas, total) + list(extra)))
    return t


def _etiqueta_tipo(tipo):
    color = TIPO_COLOR.get(tipo, "#4A5565")
    return Paragraph(f'<font color="{color}"><b>{tipo}</b></font>', E["chico"])


def _cabecera_capitulo(texto, color):
    barra = Table([[Paragraph(f'<font color="{color}">{texto}</font>', E["h2"])]], colWidths=[267 * mm])
    barra.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, 0), 5, colors.HexColor(color)),
                               ("LEFTPADDING", (0, 0), (0, 0), 8)]))
    return barra


class LienzoNumerado(canvas.Canvas):
    """Canvas que escribe 'Página X de Y' al final, cuando ya conoce el total de páginas."""

    pie = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(SUAVE)
            ancho, _ = landscape(A4)
            self.drawString(15 * mm, 8 * mm, self.pie)
            self.drawRightString(ancho - 15 * mm, 8 * mm, f"Página {self._pageNumber} de {total}")
            super().showPage()
        super().save()


def _seccion_resumen(d, h):
    e = d["encabezado"]
    h += [Paragraph(f"<b>{e['empresa']}</b> · {e['departamento']} · RUT {e['rut']}", E["suave"]),
          Paragraph(e["titulo"], E["titulo"]),
          Paragraph(f"{e['subtitulo']} · {e['cuenta']} · Generado {e['generado']:%d/%m/%Y %H:%M}", E["suave"]),
          Spacer(1, 6 * mm),
          Paragraph("1. Resumen", E["h2"])]
    filas = [["Medio de pago", "Ventas Transbank", "Comisión + IVA", "Abono Transbank", "Abono en cartola",
              "Diferencial", "N° ventas", "Con falla"]]
    extra = []
    for i, r in enumerate(d["resumen_medios"], 1):
        filas.append([Paragraph(f'<font color="{r["color"]}"><b>{r["etiqueta"]}</b></font>', E["normal"]),
                      pesos(r.get("ventas")), pesos(r.get("comision_iva")), pesos(r.get("abono_tbk")),
                      pesos(r.get("abono_cartola")), pesos(r.get("diferencial")), entero(r.get("n_ventas")),
                      entero(r.get("n_falla"))])
        extra.append(("LINEBEFORE", (0, i), (0, i), 4, colors.HexColor(r["color"])))
    t = d["total"]
    filas.append(["Total", pesos(t.get("ventas")), pesos(t.get("comision_iva")), pesos(t.get("abono_tbk")),
                  pesos(t.get("abono_cartola")), pesos(t.get("diferencial")), entero(t.get("n_ventas")),
                  entero(t.get("n_falla"))])
    h.append(_tabla(filas, [48 * mm, 32 * mm, 28 * mm, 32 * mm, 32 * mm, 28 * mm, 22 * mm, 22 * mm],
                    numericas=range(1, 8), total=True, extra=extra))
    dif = t.get("diferencial", 0)
    texto = ("Los abonos de Transbank cuadran con la cartola (diferencial $0)." if dif == 0 else
             f"Diferencial total entre Transbank y cartola: {pesos(dif)}. Ver detalle por medio de pago.")
    h += [Spacer(1, 3 * mm), Paragraph(texto, E["normal"]),
          Paragraph("Cuadratura correcta: en cada medio de pago la suma de las categorías es igual a "
                    "Ventas Transbank." if d["cuadra"] else
                    "<b>La suma de las categorías no coincide con Ventas Transbank en algún medio.</b>", E["normal"]),
          Paragraph(f"Pendientes abiertos al cierre: {len(d['pendientes'])} · cerrados este mes: "
                    f"{d['n_pendientes_cerrados']}.", E["normal"])]
    if d["cartola_sin_archivo"]:
        total = sum(m.abono for m in d["cartola_sin_archivo"])
        h += [Paragraph(f"Abonos de la cartola sin archivo Transbank ({len(d['cartola_sin_archivo'])} · "
                        f"{pesos(total)})", E["h3"]),
              Paragraph("Llegaron al banco en el mes pero no se cargó su archivo 'Abonos por día'; sus ventas no "
                        "se pudieron verificar. Cargar los archivos de esas fechas.", E["suave"]),
              _tabla([["Fecha", "Descripción en la cartola", "Medio probable", "Monto"]] +
                     [[f"{m.fecha:%d/%m/%Y}", Paragraph(escape(m.descripcion), E["chico"]), m.medio_probable,
                       pesos(m.abono)] for m in d["cartola_sin_archivo"]],
                     [24 * mm, 120 * mm, 34 * mm, 30 * mm], numericas=(3,))]


def _seccion_matriz(d, h):
    h.append(Paragraph("2. Matriz de resultados", E["h2"]))
    h.append(Paragraph("Cantidad de registros por categoría y medio de pago. Operación: revisar con Transbank o "
                       "el banco. Dato: corregir en el sistema del hotel. Aviso y Pendiente: no son fallas.",
                       E["suave"]))
    filas = [["Categoría", "Tipo"] + [cat.ETIQUETA_MEDIO[m] for m in cat.MEDIOS] + ["Total", "Monto total"]]
    extra = []
    for i, f in enumerate(d["matriz"], 1):
        filas.append([f["etiqueta"], _etiqueta_tipo(f["tipo"]), *[entero(c["n"]) if c["n"] else "-"
                                                                  for c in f["celdas"]],
                      entero(f["total_n"]), pesos(f["total_monto"])])
    for j, m in enumerate(cat.MEDIOS, 2):
        extra.append(("TEXTCOLOR", (j, 0), (j, 0), colors.HexColor(cat.COLOR_MEDIO[m])))
    h.append(_tabla(filas, [70 * mm, 24 * mm, 26 * mm, 26 * mm, 26 * mm, 24 * mm, 34 * mm],
                    numericas=range(2, 7), extra=extra))
    h.append(Paragraph("Red Compra (RCO) puede ser débito o prepago; sus pendientes se muestran bajo Débito.",
                       E["suave"]))


def _tabla_ventas(ventas, con_mensaje=True):
    filas = [["Fecha", "Código", "Local", "Monto TBK", "Monto bordero", "Dif.", "Categoría", "Tipo"]
             + (["Qué hacer"] if con_mensaje else [])]
    for v in ventas:
        fila = [f"{v.fecha_venta:%d/%m/%Y}", v.codigo_autorizacion, Paragraph(escape(v.local), E["chico"]),
                pesos(v.monto_original), pesos(v.monto_bordero), pesos(v.diferencia),
                Paragraph(cat.ETIQUETA.get(v.categoria, ""), E["chico"]), _etiqueta_tipo(v.tipo)]
        if con_mensaje:
            fila.append(Paragraph(escape(v.mensaje), E["chico"]))
        filas.append(fila)
    anchos = [18 * mm, 18 * mm, 30 * mm, 21 * mm, 21 * mm, 16 * mm, 32 * mm, 18 * mm]
    if con_mensaje:
        anchos.append(93 * mm)
    return _tabla(filas, anchos, numericas=(3, 4, 5))


def _seccion_capitulo(d, h, numero, medio):
    cap = d["capitulos"][medio]
    r = cap["resumen"]
    h += [PageBreak(), _cabecera_capitulo(f"{numero}. {cap['etiqueta']}", cap["color"])]
    h.append(Paragraph(
        f"{entero(r.get('n_ventas'))} ventas · {entero(r.get('n_falla'))} con falla · ventas Transbank "
        f"{pesos(r.get('ventas'))} · comisión + IVA {pesos(r.get('comision_iva'))} · abono "
        f"{pesos(r.get('abono_tbk'))}", E["normal"]))
    for a in cap["abonos"]:
        estado = "cuadra con la cartola" if a.categoria == cat.OK else "<b>no cuadra con la cartola</b>"
        h.append(Paragraph(f"Abono del {a.fecha_abono:%d/%m/%Y} por {pesos(a.total_abono)}: {estado}. "
                           f"{escape(a.mensaje) if a.categoria != cat.OK else ''}", E["normal"]))
    h.append(Paragraph("Ventas con falla", E["h3"]))
    if cap["fallas"]:
        h.append(_tabla_ventas(cap["fallas"]))
    else:
        h.append(Paragraph("Sin fallas en este medio de pago.", E["suave"]))
    if cap["avisos"]:
        h.append(Paragraph(f"Avisos ({len(cap['avisos'])}): no son fallas, se informan para seguimiento", E["h3"]))
        h.append(_tabla_ventas(cap["avisos"], con_mensaje=medio != cat.CREDITO))
    if medio == cat.CREDITO:
        h.append(Paragraph("Cuotas", E["h3"]))
        filas = [["Fecha venta", "Código", "Local", "Cuota", "Monto venta", "Monto de esta cuota", "Categoría"]]
        for v in d["cuotas"]:
            filas.append([f"{v.fecha_venta:%d/%m/%Y}", v.codigo_autorizacion, v.local, v.cuota,
                          pesos(v.monto_original), pesos(v.monto_abono_valido), cat.ETIQUETA.get(v.categoria)])
        if len(filas) > 1:
            h.append(_tabla(filas, [24 * mm, 22 * mm, 50 * mm, 16 * mm, 30 * mm, 34 * mm, 50 * mm],
                            numericas=(4, 5)))
        else:
            h.append(Paragraph("No hay ventas en cuotas en este mes.", E["suave"]))
    if cap["otros"]:
        h.append(Paragraph("Otros movimientos (no son ventas)", E["h3"]))
        h.append(_tabla([["Fecha", "Tipo de movimiento", "Código", "Monto"]] +
                        [[f"{v.fecha_venta:%d/%m/%Y}", v.tipo_movimiento, v.codigo_autorizacion,
                          pesos(v.monto_original)] for v in cap["otros"]],
                        [24 * mm, 50 * mm, 30 * mm, 30 * mm], numericas=(3,)))
    h.append(Spacer(1, 4 * mm))


def _seccion_pendientes(d, h):
    h += [PageBreak(), Paragraph("6. Pendientes", E["h2"])]
    h.append(Paragraph(f"Pagos con tarjeta del bordero sin abono de Transbank al cierre ({len(d['pendientes'])}). "
                       "Se revisan automáticamente en la conciliación del mes siguiente.", E["suave"]))
    if d["pendientes"]:
        filas = [["Fecha", "Cod. Deb.", "Medio", "Documento", "Monto", "Cuenta", "Mes de origen", "Observación"]]
        for p in d["pendientes"]:
            filas.append([f"{p.pago.fecha:%d/%m/%Y}", p.pago.cod_deb, cat.ETIQUETA_MEDIO[p.medio],
                          p.pago.documento, pesos(abs(p.pago.valor)), p.pago.cuenta, p.origen.etiqueta,
                          Paragraph(escape(p.observacion), E["chico"])])
        h.append(_tabla(filas, [22 * mm, 20 * mm, 20 * mm, 30 * mm, 26 * mm, 24 * mm, 30 * mm, 95 * mm],
                        numericas=(4,)))
    if d["invalidos_bordero"]:
        h.append(Paragraph("Datos inválidos del bordero (pagos con tarjeta con monto positivo)", E["h3"]))
        h.append(_tabla([["Fecha", "Cod. Deb.", "Documento", "Monto", "Descripción"]] +
                        [[f"{p.fecha:%d/%m/%Y}", p.cod_deb, p.documento, pesos(p.valor), p.descripcion]
                         for p in d["invalidos_bordero"]],
                        [24 * mm, 20 * mm, 30 * mm, 26 * mm, 60 * mm], numericas=(3,)))


def _seccion_parametros(d, h):
    p = d["parametros"]
    h.append(Paragraph("7. Parámetros y archivos", E["h2"]))
    filas = [["Parámetro", "Valor"],
             ["Tolerancia en pesos", pesos(p.get("tolerancia_clp"))],
             ["Similitud mínima de códigos", str(p.get("umbral_similitud"))],
             ["Días hábiles de holgura en cartola", str(p.get("dias_holgura"))],
             ["Días máximos entre venta y bordero", str(p.get("ventana_dias"))],
             ["Textos de abonos en cartola", ", ".join(p.get("patrones_cartola", []))],
             ["Medio probable según cartola",
              Paragraph(escape("; ".join(f"{t} = {m}" for t, m in p.get("reglas_medio_cartola", []))), E["chico"])],
             ["Omitir archivos en moneda extranjera", "Sí" if p.get("omitir_moneda_extranjera") else "No"]]
    filas += [[f"Equivalencia {k}", ", ".join(cat.ETIQUETA_MEDIO.get(m, m) for m in v)]
              for k, v in p.get("equivalencias", {}).items()]
    h.append(KeepTogether(_tabla(filas, [80 * mm, 80 * mm])))
    h.append(Spacer(1, 4 * mm))
    filas = [["Archivo", "Tipo", "Medio", "Período / abono", "Filas", "Total abono"]]
    for a in d["archivos"]:
        periodo = (f"abono {a.fecha_abono:%d/%m/%Y}" if a.fecha_abono else
                   f"{a.desde:%d/%m/%Y} a {a.hasta:%d/%m/%Y}" if a.desde else "-")
        tipo = a.get_tipo_display() + (f" (omitido, {a.moneda})" if a.moneda_extranjera else "")
        filas.append([Paragraph(escape(a.nombre), E["chico"]), Paragraph(escape(tipo), E["chico"]),
                      Paragraph(escape(a.etiqueta_medio or "-"), E["chico"]), periodo,
                      entero(a.filas), pesos(a.total_abono) if a.total_abono is not None else "-"])
    h.append(_tabla(filas, [80 * mm, 26 * mm, 24 * mm, 50 * mm, 20 * mm, 32 * mm], numericas=(4, 5)))


def generar(conciliacion) -> bytes:
    d = armar(conciliacion)
    salida = BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm,
                            title=d["encabezado"]["titulo"], author=d["encabezado"]["empresa"])
    h = []
    _seccion_resumen(d, h)
    _seccion_matriz(d, h)
    _seccion_capitulo(d, h, 3, cat.DEBITO)
    _seccion_capitulo(d, h, 4, cat.CREDITO)
    _seccion_capitulo(d, h, 5, cat.PREPAGO)
    _seccion_pendientes(d, h)
    _seccion_parametros(d, h)

    pie = f"{d['encabezado']['empresa']} · {d['encabezado']['titulo']} · generado " \
          f"{d['encabezado']['generado']:%d/%m/%Y %H:%M}"

    class Lienzo(LienzoNumerado):
        pass

    Lienzo.pie = pie
    doc.build(h, canvasmaker=Lienzo)
    return salida.getvalue()
