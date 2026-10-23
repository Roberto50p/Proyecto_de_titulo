from conciliacion.models import PagoBordero, Pendiente
from conciliacion.servicio import procesar


def test_bordero_traslapado_no_duplica(crear_conciliacion):
    procesar(crear_conciliacion(2026, 8, ["BORDERO 04-09 A 07-09.xlsx"]))
    total = PagoBordero.objects.count()
    procesar(crear_conciliacion(2026, 9, ["BORDERO 04-09 A 07-09.xlsx"]))
    assert PagoBordero.objects.count() == total == 228


def test_pendiente_se_cierra_mes_siguiente(crear_conciliacion):
    agosto = procesar(crear_conciliacion(2026, 8, ["BORDERO 04-09 A 07-09.xlsx"]))
    assert agosto.pendientes.filter(abierto=True).count() == 227

    septiembre = procesar(crear_conciliacion())
    venta = septiembre.ventas.get(codigo_autorizacion="003098")
    assert venta.categoria == "OK" and "cierra pendiente de Agosto 2026" in venta.nota
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
