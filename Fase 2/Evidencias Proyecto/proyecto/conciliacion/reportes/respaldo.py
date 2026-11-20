"""Respaldo en Excel de las conciliaciones antes de borrarlas de la base: todas sus tablas.

A diferencia del reporte (excel.py), aquí va el dato completo fila por fila, para poder consultarlo después de
limpiar la base. Cada tabla lleva el ID de la conciliación para relacionarlas entre sí.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from django.db.models import Q
from django.utils import timezone
from openpyxl import Workbook

from ..models import (ArchivoCargado, Conciliacion, CorreccionManual, MovimientoCartola, PagoBordero, Pendiente,
                      ResultadoAbono, VentaDolar, VentaTransbank)
from ..motor import categorias as cat
from .excel import Hoja
from .excel_usd import DOLARES


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


def tablas(conciliaciones) -> list[Tabla]:
    """Tablas del respaldo. `conciliaciones` es una lista de Conciliacion con `p_desde` y `p_hasta`
    (servicio.seleccionar)."""
    ids = [c.pk for c in conciliaciones]
    totales = ("Abono Transbank", "Abono en cartola", "Diferencial")  # en la moneda de cada conciliación
    resumen = Tabla("Conciliaciones",
                    ["ID", "Conciliación", "Estado", "Moneda", "Período desde", "Período hasta", "Creada",
                     "Procesada", "Creada por", *totales, "Ventas", "Con falla"],
                    montos=totales, dolares=totales, fechas=("Período desde", "Período hasta"),
                    filas_en_dolares={i for i, c in enumerate(conciliaciones) if c.moneda == Conciliacion.USD})
    for c in conciliaciones:
        total = (c.resumen or {}).get("total", {})
        resumen.filas.append([
            c.pk, c.etiqueta, c.get_estado_display(), c.get_moneda_display(), c.p_desde, c.p_hasta,
            _local(c.creada_en), _local(c.procesada_en), c.creada_por.get_username() if c.creada_por else "",
            total.get("abono_tbk"), total.get("abono_cartola"), total.get("diferencial"), total.get("n_ventas"),
            total.get("n_falla"),
        ])

    archivos = Tabla("Archivos",
                     ["Conciliación ID", "Archivo", "Tipo", "Medio", "Banco", "Moneda", "Cuenta", "Fecha abono",
                      "Desde", "Hasta", "Filas", "Total abono", "SHA-256", "Error de lectura", "Subido"],
                     montos=("Total abono",), fechas=("Fecha abono", "Desde", "Hasta"))
    for a in ArchivoCargado.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "tipo", "nombre"):
        archivos.filas.append([
            a.conciliacion_id, a.nombre, a.get_tipo_display(), a.etiqueta_medio, a.banco, a.moneda, a.cuenta,
            a.fecha_abono, a.desde, a.hasta, a.filas, a.total_abono, a.sha256, a.error, _local(a.subido_en),
        ])

    ventas = Tabla("Ventas Transbank",
                   ["Conciliación ID", "Medio", "Fecha venta", "Tipo movimiento", "Código comercio", "Local",
                    "Monto original", "Monto vuelto", "Monto válido para abono", "Comisión", "IVA comisión",
                    "Total abono", "Tipo venta", "Cuota", "Tarjeta", "Código autorización", "Boleta", "Categoría",
                    "Monto bordero", "Diferencia", "Código sugerido", "Nota", "Mensaje"],
                   montos=("Monto original", "Monto vuelto", "Monto válido para abono", "Comisión", "IVA comisión",
                           "Total abono", "Monto bordero", "Diferencia"),
                   fechas=("Fecha venta",))
    for v in VentaTransbank.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "medio",
                                                                             "fecha_venta", "fila"):
        ventas.filas.append([
            v.conciliacion_id, _medio(v.medio), v.fecha_venta, v.tipo_movimiento, v.codigo_comercio, v.local,
            v.monto_original, v.monto_vuelto, v.monto_abono_valido, v.comision, v.iva_comision, v.total_abono,
            v.tipo_venta, v.cuota, v.tarjeta, v.codigo_autorizacion, v.boleta, _categoria(v.categoria),
            v.monto_bordero, v.diferencia, v.codigo_sugerido, v.nota, v.mensaje,
        ])

    abonos = Tabla("Abonos",
                   ["Conciliación ID", "Medio", "Fecha abono", "Total abono", "Categoría", "Fecha cartola",
                    "Descripción cartola", "Monto cartola", "Diferencia", "Mensaje"],
                   montos=("Total abono", "Monto cartola", "Diferencia"), fechas=("Fecha abono", "Fecha cartola"))
    for r in ResultadoAbono.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "medio",
                                                                             "fecha_abono"):
        abonos.filas.append([
            r.conciliacion_id, _medio(r.medio), r.fecha_abono, r.total_abono, _categoria(r.categoria),
            r.cartola_fecha, r.cartola_descripcion, r.cartola_monto, r.diferencia, r.mensaje,
        ])

    # Conciliaciones en dólares: sus ventas cruzadas con el ERP y la cartera, y la verificación de cada abono en la
    # cartola US$ (que solo se guarda en el resumen de la conciliación).
    ventas_usd = Tabla("Ventas US$",
                       ["Conciliación ID", "Tarjeta", "Fecha venta", "Hora", "Código autorización",
                        "Monto Transbank US$", "Comisión US$", "Documento ERP", "Valor ERP $", "Cartera US$",
                        "Diferencia US$", "Resultado", "Mensaje"],
                       montos=("Valor ERP $",), fechas=("Fecha venta",),
                       dolares=("Monto Transbank US$", "Comisión US$", "Cartera US$", "Diferencia US$"))
    for v in VentaDolar.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "tarjeta",
                                                                         "fecha_venta", "hora", "fila"):
        ventas_usd.filas.append([
            v.conciliacion_id, v.get_tarjeta_display(), v.fecha_venta, v.hora, v.codigo_autorizacion,
            v.monto_original, v.comision, v.documento, v.valor_erp, v.monto_cartera, v.diferencia,
            v.get_categoria_display(), v.mensaje,
        ])

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

    cartola = Tabla("Cartola",
                    ["Conciliación ID", "Fecha", "Descripción", "Canal", "N° documento", "Cargo", "Abono", "Saldo",
                     "Abono Transbank", "Conciliado", "Medio probable"],
                    montos=("Cargo", "Abono", "Saldo"), fechas=("Fecha",))
    for m in MovimientoCartola.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "fecha", "id"):
        cartola.filas.append([
            m.conciliacion_id, m.fecha, m.descripcion, m.canal, m.nro_docto, m.cargo, m.abono, m.saldo,
            _si(m.es_transbank), _si(m.conciliado), m.medio_probable,
        ])

    pendientes = Tabla("Pendientes",
                       ["Conciliación ID", "Medio", "Fecha", "Hora", "Cod. Deb.", "Documento", "Valor", "Cuenta",
                        "Reserva", "Hab.", "Abierto", "Cerrado en conciliación ID", "Mensaje", "Revisado",
                        "Observación"],
                       montos=("Valor",), fechas=("Fecha",))
    for p in (Pendiente.objects.filter(origen_id__in=ids).select_related("pago")
              .order_by("origen_id", "pago__fecha", "pago__hora")):
        pendientes.filas.append([
            p.origen_id, _medio(p.medio), p.pago.fecha, p.pago.hora, p.pago.cod_deb, p.pago.documento,
            p.pago.valor, p.pago.cuenta, p.pago.reserva, p.pago.hab, _si(p.abierto), p.cierre_id, p.mensaje,
            _si(p.revisado), p.observacion,
        ])

    pagos = Tabla("Pagos bordero",
                  ["Fecha", "Hora", "Hab.", "Reserva", "Cuenta", "Cod. Deb.", "Descripción", "Factura", "Valor",
                   "Documento", "Usuario", "Designación", "Inválido", "Conciliado en conciliación ID"],
                  montos=("Valor",), fechas=("Fecha",))
    for p in (PagoBordero.objects.filter(Q(archivos__conciliacion_id__in=ids) | Q(conciliacion_id__in=ids))
              .distinct().order_by("fecha", "hora")):
        pagos.filas.append([
            p.fecha, p.hora, p.hab, p.reserva, p.cuenta, p.cod_deb, p.descripcion, p.factura, p.valor, p.documento,
            p.usuario, p.designacion, _si(p.invalido), p.conciliacion_id,
        ])

    correcciones = Tabla("Correcciones manuales",
                         ["Conciliación ID", "Medio", "Fecha venta", "Código", "Cuota", "Monto venta", "Local",
                          "Categoría original", "Documento original", "Monto bordero original",
                          "Cod. Deb. original", "Documento editado", "Monto editado", "Cod. Deb. editado",
                          "Fecha bordero editada", "Aceptada sin corregir", "Comentario", "Creada", "Modificada"],
                         montos=("Monto venta", "Monto bordero original", "Monto editado"),
                         fechas=("Fecha venta", "Fecha bordero editada"))
    for c in CorreccionManual.objects.filter(conciliacion_id__in=ids).order_by("conciliacion_id", "fecha_venta"):
        correcciones.filas.append([
            c.conciliacion_id, _medio(c.medio), c.fecha_venta, c.codigo_autorizacion, c.cuota_num or "",
            c.monto_original, c.local, _categoria(c.categoria_original), c.documento_original,
            c.monto_bordero_original, c.cod_deb_original, c.documento, c.monto, c.cod_deb, c.fecha_bordero,
            _si(c.aceptada), c.comentario, _local(c.creada), _local(c.modificada),
        ])

    return [resumen, archivos, ventas, abonos, ventas_usd, abonos_usd, cartola, pendientes, correcciones, pagos]


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
