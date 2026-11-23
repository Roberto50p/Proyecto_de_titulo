"""Respaldo en Excel de las conciliaciones antes de borrarlas de la base: todas sus tablas.

A diferencia del reporte (excel.py), aquí va el dato completo fila por fila, para poder consultarlo después de
limpiar la base. Cada hoja trae primero columnas legibles (con el ID de la conciliación para relacionarlas entre
sí) y después, con el prefijo "BD ", todas las columnas de su tabla en la base tal como están guardadas (ids,
relaciones, campos internos y JSON). Así no se pierde ningún dato aunque quede repetido. Los campos JSON se
detallan además, valor por valor, en la hoja "Datos JSON".
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from django.db import models
from django.db.models import Q
from django.utils import timezone
from openpyxl import Workbook

from ..models import (ArchivoCargado, CoberturaBordero, Conciliacion, CorreccionManual, MovimientoCartola,
                      PagoBordero, Pendiente, ResultadoAbono, VentaDolar, VentaTransbank)
from ..motor import categorias as cat
from .excel import Hoja
from .excel_usd import DOLARES

BD = "BD "  # prefijo de las columnas con el valor tal cual está en la base
LIMITE_CELDA = 32767  # caracteres que admite una celda de Excel


@dataclass
class Tabla:
    nombre: str
    columnas: list[str]
    filas: list[list] = field(default_factory=list)
    montos: tuple[str, ...] = ()
    fechas: tuple[str, ...] = ()
    dolares: tuple[str, ...] = ()  # columnas en dólares, con centavos
    filas_en_dolares: set[int] | None = None  # si se indica, `dolares` aplica solo a esas filas (el resto, pesos)


def _si(valor: bool) -> str:
    return "Sí" if valor else "No"


def _local(momento: datetime | None) -> str:
    """Fecha y hora en la zona del hotel, como texto (el formato de fecha de las tablas no muestra la hora)."""
    return f"{timezone.localtime(momento):%d/%m/%Y %H:%M}" if momento else ""


def _fecha(iso: str | None) -> date | None:
    """Fecha guardada como texto AAAA-MM-DD en el resumen JSON."""
    return date.fromisoformat(iso) if iso else None


def _categoria(codigo: str) -> str:
    return cat.ETIQUETA.get(codigo, codigo)


def _medio(codigo: str) -> str:
    return cat.ETIQUETA_MEDIO.get(codigo, codigo)


def _campos(modelo) -> list:
    """Todas las columnas del modelo en la base, más sus relaciones muchos a muchos."""
    return [*modelo._meta.concrete_fields, *modelo._meta.many_to_many]


def columna_bd(campo) -> str:
    return BD + (campo.name if campo.many_to_many else campo.attname)


def _aplanar(valor, ruta=""):
    """Pares (ruta, valor) de cada dato de un JSON: "total.abono_tbk", "abonos[0].monto"..."""
    if isinstance(valor, dict) and valor:
        for k, v in valor.items():
            yield from _aplanar(v, f"{ruta}.{k}" if ruta else str(k))
    elif isinstance(valor, list) and valor:
        for i, v in enumerate(valor):
            yield from _aplanar(v, f"{ruta}[{i}]")
    elif isinstance(valor, (dict, list)):
        yield ruta, json.dumps(valor)
    else:
        yield ruta, valor


def _crudo(objeto, campo, datos_json: Tabla, hoja: str):
    """Valor de la base, apto para una celda. Los JSON van como texto y, dato por dato, en la hoja Datos JSON."""
    if campo.many_to_many:
        return ", ".join(str(pk) for pk in sorted(o.pk for o in getattr(objeto, campo.name).all()))
    valor = getattr(objeto, campo.attname)
    if isinstance(campo, models.JSONField):
        for ruta, dato in _aplanar(valor):
            datos_json.filas.append([hoja, objeto.pk, campo.name, ruta, dato])
        texto = json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)
        return texto if len(texto) <= LIMITE_CELDA else "(no cabe en una celda: ver hoja Datos JSON)"
    if isinstance(campo, models.FileField):
        return valor.name
    if isinstance(valor, datetime):  # con la hora completa y su zona (Excel no admite fechas con zona)
        return (timezone.localtime(valor) if timezone.is_aware(valor) else valor).isoformat()
    return valor


def _tabla(nombre, columnas, modelo, objetos, legible, datos_json: Tabla, **formato) -> Tabla:
    """Hoja con las columnas legibles (`legible(objeto)`) seguidas de todas las columnas del modelo en la base."""
    campos = _campos(modelo)
    fechas = tuple(columna_bd(c) for c in campos
                   if isinstance(c, models.DateField) and not isinstance(c, models.DateTimeField))
    t = Tabla(nombre, [*columnas, *map(columna_bd, campos)], **formato)
    t.fechas = (*t.fechas, *fechas)
    for o in objetos:
        t.filas.append([*legible(o), *(_crudo(o, c, datos_json, nombre) for c in campos)])
    return t


def tablas(conciliaciones) -> list[Tabla]:
    """Tablas del respaldo. `conciliaciones` es una lista de Conciliacion con `p_desde` y `p_hasta`
    (servicio.seleccionar).

    Incluye todo lo que se borra con ellas (servicio.eliminar_conciliaciones) y, por si acaso, también lo que solo
    se relaciona con ellas: pagos del bordero que usaron, dejaron pendientes o cerraron, y pendientes de otras
    conciliaciones que ellas cerraron. Si abarcan toda la base, van además todos los pagos y coberturas del bordero,
    porque "Limpiar toda la base" los borra aunque ya no cuelguen de ninguna conciliación."""
    ids = [c.pk for c in conciliaciones]
    toda_la_base = not Conciliacion.objects.exclude(pk__in=ids).exists()
    datos_json = Tabla("Datos JSON", ["Hoja", "ID en la base", "Campo", "Ruta", "Valor"])

    totales = ("Abono Transbank", "Abono en cartola", "Diferencial")  # en la moneda de cada conciliación
    resumen = _tabla(
        "Conciliaciones",
        ["ID", "Conciliación", "Estado", "Moneda", "Período desde", "Período hasta", "Creada", "Procesada",
         "Creada por", *totales, "Ventas", "Con falla"],
        Conciliacion, conciliaciones,
        lambda c: [c.pk, c.etiqueta, c.get_estado_display(), c.get_moneda_display(), c.p_desde, c.p_hasta,
                   _local(c.creada_en), _local(c.procesada_en),
                   c.creada_por.get_username() if c.creada_por else "",
                   *((c.resumen or {}).get("total", {}).get(k)
                     for k in ("abono_tbk", "abono_cartola", "diferencial", "n_ventas", "n_falla"))],
        datos_json, montos=totales, dolares=totales, fechas=("Período desde", "Período hasta"),
        filas_en_dolares={i for i, c in enumerate(conciliaciones) if c.moneda == Conciliacion.USD})

    archivos = _tabla(
        "Archivos",
        ["Conciliación ID", "Archivo", "Tipo", "Medio", "Banco", "Moneda", "Cuenta", "Fecha abono", "Desde", "Hasta",
         "Filas", "Total abono", "SHA-256", "Error de lectura", "Subido"],
        ArchivoCargado,
        ArchivoCargado.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "tipo", "nombre", "pk"),
        lambda a: [a.conciliacion_id, a.nombre, a.get_tipo_display(), a.etiqueta_medio, a.banco, a.moneda, a.cuenta,
                   a.fecha_abono, a.desde, a.hasta, a.filas, a.total_abono, a.sha256, a.error, _local(a.subido_en)],
        datos_json, montos=("Total abono",), fechas=("Fecha abono", "Desde", "Hasta"))

    coberturas = CoberturaBordero.objects.select_related("archivo")
    if not toda_la_base:
        coberturas = coberturas.filter(archivo__conciliacion_id__in=ids)
    cobertura = _tabla(
        "Cobertura bordero", ["Conciliación ID", "Archivo", "Desde", "Hasta"], CoberturaBordero,
        coberturas.order_by("desde", "hasta", "pk"),
        lambda c: [c.archivo.conciliacion_id if c.archivo else None, c.archivo.nombre if c.archivo else "",
                   c.desde, c.hasta],
        datos_json, fechas=("Desde", "Hasta"))

    ventas = _tabla(
        "Ventas Transbank",
        ["Conciliación ID", "Medio", "Fecha venta", "Tipo movimiento", "Código comercio", "Local", "Monto original",
         "Monto vuelto", "Monto válido para abono", "Comisión", "IVA comisión", "Total abono", "Tipo venta", "Cuota",
         "Tarjeta", "Código autorización", "Boleta", "Categoría", "Monto bordero", "Diferencia", "Código sugerido",
         "Nota", "Mensaje", "Documento pago bordero", "Fecha pago bordero", "Cod. Deb. pago bordero"],
        VentaTransbank,
        VentaTransbank.objects.filter(conciliacion_id__in=ids).select_related("pago")
        .order_by("conciliacion_id", "medio", "fecha_venta", "fila", "pk"),
        lambda v: [v.conciliacion_id, _medio(v.medio), v.fecha_venta, v.tipo_movimiento, v.codigo_comercio, v.local,
                   v.monto_original, v.monto_vuelto, v.monto_abono_valido, v.comision, v.iva_comision, v.total_abono,
                   v.tipo_venta, v.cuota, v.tarjeta, v.codigo_autorizacion, v.boleta, _categoria(v.categoria),
                   v.monto_bordero, v.diferencia, v.codigo_sugerido, v.nota, v.mensaje,
                   v.pago.documento if v.pago else "", v.pago.fecha if v.pago else None,
                   v.pago.cod_deb if v.pago else ""],
        datos_json,
        montos=("Monto original", "Monto vuelto", "Monto válido para abono", "Comisión", "IVA comisión",
                "Total abono", "Monto bordero", "Diferencia"),
        fechas=("Fecha venta", "Fecha pago bordero"))

    abonos = _tabla(
        "Abonos",
        ["Conciliación ID", "Medio", "Fecha abono", "Total abono", "Categoría", "Fecha cartola",
         "Descripción cartola", "Monto cartola", "Diferencia", "Mensaje"],
        ResultadoAbono,
        ResultadoAbono.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "medio", "fecha_abono",
                                                                        "pk"),
        lambda r: [r.conciliacion_id, _medio(r.medio), r.fecha_abono, r.total_abono, _categoria(r.categoria),
                   r.cartola_fecha, r.cartola_descripcion, r.cartola_monto, r.diferencia, r.mensaje],
        datos_json, montos=("Total abono", "Monto cartola", "Diferencia"), fechas=("Fecha abono", "Fecha cartola"))

    # Conciliaciones en dólares: sus ventas cruzadas con el ERP y la cartera, y la verificación de cada abono en la
    # cartola US$ (que solo se guarda en el resumen de la conciliación).
    ventas_usd = _tabla(
        "Ventas US$",
        ["Conciliación ID", "Tarjeta", "Fecha venta", "Hora", "Código autorización", "Monto Transbank US$",
         "Comisión US$", "Documento ERP", "Valor ERP $", "Cartera US$", "Diferencia US$", "Resultado", "Mensaje"],
        VentaDolar,
        VentaDolar.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "tarjeta", "fecha_venta",
                                                                    "hora", "fila", "pk"),
        lambda v: [v.conciliacion_id, v.get_tarjeta_display(), v.fecha_venta, v.hora, v.codigo_autorizacion,
                   v.monto_original, v.comision, v.documento, v.valor_erp, v.monto_cartera, v.diferencia,
                   v.get_categoria_display(), v.mensaje],
        datos_json, montos=("Valor ERP $",), fechas=("Fecha venta",),
        dolares=("Monto Transbank US$", "Comisión US$", "Cartera US$", "Diferencia US$"))

    abonos_usd = Tabla("Abonos US$",
                       ["Conciliación ID", "Fecha abono", "Abono US$", "En cartola", "Fecha cartola",
                        "Descripción cartola", "Mensaje"],
                       fechas=("Fecha abono", "Fecha cartola"), dolares=("Abono US$",))
    for c in conciliaciones:
        if c.moneda != Conciliacion.USD:
            continue
        for a in (c.resumen or {}).get("abonos", []):
            abonos_usd.filas.append([
                c.pk, _fecha(a["fecha_abono"]), Decimal(a["monto"]),
                "" if a["en_cartola"] is None else _si(a["en_cartola"]), _fecha(a["cartola_fecha"]),
                a["cartola_descripcion"], a["mensaje"],
            ])

    cartola = _tabla(
        "Cartola",
        ["Conciliación ID", "Fecha", "Descripción", "Canal", "N° documento", "Cargo", "Abono", "Saldo",
         "Abono Transbank", "Conciliado", "Medio probable"],
        MovimientoCartola,
        MovimientoCartola.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "fecha", "pk"),
        lambda m: [m.conciliacion_id, m.fecha, m.descripcion, m.canal, m.nro_docto, m.cargo, m.abono, m.saldo,
                   _si(m.es_transbank), _si(m.conciliado), m.medio_probable],
        datos_json, montos=("Cargo", "Abono", "Saldo"), fechas=("Fecha",))

    pendientes = _tabla(
        "Pendientes",
        ["Conciliación ID", "Medio", "Fecha", "Hora", "Cod. Deb.", "Documento", "Valor", "Cuenta", "Reserva", "Hab.",
         "Abierto", "Cerrado en conciliación ID", "Mensaje", "Revisado", "Observación"],
        Pendiente,
        Pendiente.objects.filter(Q(origen_id__in=ids) | Q(cierre_id__in=ids)).select_related("pago")
        .order_by("origen_id", "pago__fecha", "pago__hora", "pk"),
        lambda p: [p.origen_id, _medio(p.medio), p.pago.fecha, p.pago.hora, p.pago.cod_deb, p.pago.documento,
                   p.pago.valor, p.pago.cuenta, p.pago.reserva, p.pago.hab, _si(p.abierto), p.cierre_id, p.mensaje,
                   _si(p.revisado), p.observacion],
        datos_json, montos=("Valor",), fechas=("Fecha",))

    correcciones = _tabla(
        "Correcciones manuales",
        ["Conciliación ID", "Medio", "Fecha venta", "Código", "Cuota", "Monto venta", "Local", "Categoría original",
         "Documento original", "Monto bordero original", "Cod. Deb. original", "Documento editado",
         "Monto editado", "Cod. Deb. editado", "Fecha bordero editada", "Aceptada sin corregir", "Comentario",
         "Creada", "Modificada", "Mensaje original"],
        CorreccionManual,
        CorreccionManual.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "fecha_venta", "pk"),
        lambda c: [c.conciliacion_id, _medio(c.medio), c.fecha_venta, c.codigo_autorizacion, c.cuota_num or "",
                   c.monto_original, c.local, _categoria(c.categoria_original), c.documento_original,
                   c.monto_bordero_original, c.cod_deb_original, c.documento, c.monto, c.cod_deb, c.fecha_bordero,
                   _si(c.aceptada), c.comentario, _local(c.creada), _local(c.modificada), c.mensaje_original],
        datos_json, montos=("Monto venta", "Monto bordero original", "Monto editado"),
        fechas=("Fecha venta", "Fecha bordero editada"))

    pagos_bordero = PagoBordero.objects.all()
    if not toda_la_base:
        pagos_bordero = pagos_bordero.filter(
            Q(archivos__conciliacion_id__in=ids) | Q(conciliacion_id__in=ids) | Q(ventas__conciliacion_id__in=ids)
            | Q(pendiente__origen_id__in=ids) | Q(pendiente__cierre_id__in=ids)).distinct()
    pagos = _tabla(
        "Pagos bordero",
        ["Fecha", "Hora", "Hab.", "Reserva", "Cuenta", "Cod. Deb.", "Descripción", "Factura", "Valor", "Documento",
         "Usuario", "Designación", "Inválido", "Conciliado en conciliación ID", "Borderos de las conciliaciones ID"],
        PagoBordero, pagos_bordero.prefetch_related("archivos").order_by("fecha", "hora", "pk"),
        lambda p: [p.fecha, p.hora, p.hab, p.reserva, p.cuenta, p.cod_deb, p.descripcion, p.factura, p.valor,
                   p.documento, p.usuario, p.designacion, _si(p.invalido), p.conciliacion_id,
                   ", ".join(str(i) for i in sorted({a.conciliacion_id for a in p.archivos.all()}))],
        datos_json, montos=("Valor",), fechas=("Fecha",))

    return [resumen, archivos, cobertura, ventas, abonos, ventas_usd, abonos_usd, cartola, pendientes, correcciones,
            pagos, datos_json]


def huella(lista: list[Tabla]) -> str:
    """Huella del contenido del respaldo: cambia si cambia cualquier dato exportado (se procesa la conciliación, se
    agregan archivos o correcciones, se revisa un pendiente...). Permite saber si el Excel descargado sigue
    respaldando lo que hay en la base antes de borrarlo."""
    h = hashlib.sha256()
    for t in lista:
        h.update(repr((t.nombre, t.columnas, t.filas)).encode())
    return h.hexdigest()


def nombre_archivo() -> str:
    return f"respaldo_conciliaciones_{timezone.localtime():%d-%m-%Y_%H-%M}.xlsx"


def excel(lista: list[Tabla]) -> bytes:
    libro = Workbook()
    libro.remove(libro.active)
    for t in lista:
        h = Hoja(libro, t.nombre)
        inicio = h.fila + 1  # primera fila de datos, bajo el encabezado
        h.tabla(t.columnas, t.filas, montos=t.montos, fechas=t.fechas, filtro=True, congelar=True,
                anchos=[max(12, min(40, len(c) + 4)) for c in t.columnas])
        for col in (t.columnas.index(nombre) + 1 for nombre in t.dolares):
            for i in range(len(t.filas)):
                if t.filas_en_dolares is None or i in t.filas_en_dolares:
                    h.ws.cell(inicio + i, col).number_format = DOLARES
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()
