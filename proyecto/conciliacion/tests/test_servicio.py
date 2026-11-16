from conciliacion.models import PagoBordero, Pendiente
from datetime import date

from conciliacion.servicio import periodo_ventas, procesar, validar


def test_pendientes_solo_del_periodo_de_ventas(septiembre_procesado):
    desde, hasta = periodo_ventas(septiembre_procesado)
    fechas = [p.pago.fecha for p in septiembre_procesado.pendientes.select_related("pago")]
    assert fechas and all(desde <= f <= hasta for f in fechas)


def test_bordero_traslapado_no_duplica(crear_conciliacion):
    procesar(crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx"]))
    total = PagoBordero.objects.count()
    procesar(crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx"]))
    assert PagoBordero.objects.count() == total == 228


def test_pendiente_se_cierra_en_la_conciliacion_siguiente(crear_conciliacion):
    agosto = procesar(crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx"]))
    assert agosto.pendientes.filter(abierto=True).count() == 227

    septiembre = procesar(crear_conciliacion())
    venta = septiembre.ventas.get(codigo_autorizacion="003098")
    assert venta.categoria == "OK" and f"cierra pendiente de {agosto.etiqueta}" in venta.nota
    assert Pendiente.objects.get(pago=venta.pago).cierre == septiembre
    assert septiembre.resumen["n_pendientes_cerrados"] == 104
    # En septiembre no se reabren como pendientes nuevos: ya estaban abiertos desde agosto.
    assert septiembre.pendientes.count() == 0
    assert Pendiente.objects.filter(abierto=True).count() == 123


def test_reprocesar_conserva_observacion(septiembre_procesado):
    conc = septiembre_procesado
    v = conc.ventas.get(codigo_autorizacion="007626")
    v.observacion, v.revisado = "Se cobró propina aparte", True
    v.save()
    procesar(conc)
    v = conc.ventas.get(codigo_autorizacion="007626")
    assert (v.observacion, v.revisado) == ("Se cobró propina aparte", True)
    assert conc.ventas.count() == 141
    assert PagoBordero.objects.filter(conciliacion=conc).count() == 104


# ---- Correcciones de la revisión final

def test_reprocesar_conciliacion_anterior_conserva_pendientes_cerrados(crear_conciliacion):
    agosto = procesar(crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx"]))
    septiembre = procesar(crear_conciliacion())
    cerrado = Pendiente.objects.get(pago__documento_norm="3098")
    cerrado.observacion = "Revisado con Transbank"
    cerrado.save()
    procesar(agosto)
    cerrado = Pendiente.objects.get(pago__documento_norm="3098")
    assert cerrado.cierre == septiembre and cerrado.observacion == "Revisado con Transbank"
    assert Pendiente.objects.filter(cierre=septiembre).count() == 104


def test_reporte_de_una_conciliacion_no_cambia_al_procesar_la_siguiente(crear_conciliacion):
    from conciliacion.reportes.datos import armar

    agosto = procesar(crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx"]))
    assert len(armar(agosto)["pendientes"]) == 227
    procesar(crear_conciliacion())
    assert len(armar(agosto)["pendientes"]) == 227


def test_abonos_de_cartola_sin_archivo(septiembre_procesado):
    from conciliacion.servicio import cartola_sin_archivo

    lineas = cartola_sin_archivo(septiembre_procesado)
    # Solo los días de abono cargados (08/09), no el mes completo.
    assert all(m.fecha == date(2026, 9, 8) for m in lineas)
    sin_archivo = septiembre_procesado.resumen["cartola_sin_archivo"]
    # Antes (mes completo) eran 16 líneas por $26.036.232; el 08 y 09/09 no hay abonos Transbank sin archivo.
    assert sin_archivo == {"n": len(lineas), "monto": 0} and lineas == []


def test_acepta_abono_de_cualquier_fecha(crear_conciliacion):
    assert validar(crear_conciliacion()) == []


def test_matriz_cuadra_con_ventas_transbank(septiembre_procesado):
    from conciliacion.motor import categorias as cat

    r = septiembre_procesado.resumen
    ventas = {k for k in cat.ORDEN_CATEGORIAS if k not in (cat.SIN_ABONO, cat.ABONO_CARTOLA, cat.DATO_INVALIDO)}
    for medio in cat.MEDIOS:
        suma = sum(r["matriz"][k][medio]["monto"] for k in ventas)
        assert suma == r["medios"][medio]["ventas"]


def test_documento_corregido_en_bordero_no_crea_pendiente_falso(septiembre_procesado, crear_conciliacion,
                                                                datos_reales, tmp_path):
    from django.core.files import File
    from openpyxl import load_workbook

    from conciliacion.models import ArchivoCargado
    from conciliacion.servicio import leer_archivo, sha256_de

    libro = load_workbook(datos_reales / "BORDERO 04-09 A 07-09.xlsx")
    hoja = libro.active
    for fila in hoja.iter_rows():
        for celda in fila:
            if celda.value == "0FOFUAZ":
                celda.value = "F0FUAZ"
    corregido = tmp_path / "bordero corregido.xlsx"
    libro.save(corregido)

    octubre = crear_conciliacion([])
    with open(corregido, "rb") as f:
        archivo = File(f, name=corregido.name)
        ac = ArchivoCargado(conciliacion=octubre, nombre=corregido.name, sha256=sha256_de(archivo))
        ac.archivo.save(corregido.name, archivo, save=False)
        ac.save()
    leer_archivo(ac)
    procesar(octubre)
    assert PagoBordero.objects.count() == 228
    pago = PagoBordero.objects.get(documento="F0FUAZ")
    assert pago.conciliacion == septiembre_procesado
    assert not octubre.pendientes.exists()


def test_cartola_sin_archivo_solo_dias_de_abono(db):
    from conciliacion.models import ArchivoCargado, Conciliacion, MovimientoCartola
    from conciliacion.servicio import cartola_sin_archivo

    conc = Conciliacion.objects.create(parametros={"dias_holgura": 1})
    ArchivoCargado.objects.create(conciliacion=conc, tipo=ArchivoCargado.TRANSBANK, nombre="tbk.xlsx", sha256="a",
                                  moneda="Pesos chilenos", fecha_abono=date(2026, 9, 8), archivo="tbk.xlsx")
    for dia in (7, 8, 9, 10):
        MovimientoCartola.objects.create(conciliacion=conc, fecha=date(2026, 9, dia), abono=1000, es_transbank=True)
    # El 09/09 (día siguiente) es de la próxima conciliación diaria: no se marca aquí.
    assert [m.fecha.day for m in cartola_sin_archivo(conc)] == [8]


def test_cartola_sin_archivo_omite_lineas_conciliadas_en_otra(db):
    from conciliacion.models import ArchivoCargado, Conciliacion, MovimientoCartola
    from conciliacion.servicio import cartola_sin_archivo

    otra = Conciliacion.objects.create()
    MovimientoCartola.objects.create(conciliacion=otra, fecha=date(2026, 9, 8), descripcion="ABONO TBK", abono=500,
                                     es_transbank=True, conciliado=True)
    conc = Conciliacion.objects.create()
    ArchivoCargado.objects.create(conciliacion=conc, tipo=ArchivoCargado.TRANSBANK, nombre="tbk.xlsx", sha256="a",
                                  moneda="Pesos chilenos", fecha_abono=date(2026, 9, 8), archivo="tbk.xlsx")
    for monto in (500, 700):
        MovimientoCartola.objects.create(conciliacion=conc, fecha=date(2026, 9, 8), descripcion="ABONO TBK",
                                         abono=monto, es_transbank=True)
    assert [m.abono for m in cartola_sin_archivo(conc)] == [700]
