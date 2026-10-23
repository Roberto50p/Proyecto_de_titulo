"""Aceptación con los datos reales del abono Transbank del 08-09-2026 (spec §10)."""

from collections import Counter

from conciliacion.servicio import validar


def conteo(conc, medio):
    return dict(Counter(conc.ventas.filter(medio=medio, es_venta=True).values_list("categoria", flat=True)))


def test_archivos_validos(crear_conciliacion):
    assert validar(crear_conciliacion()) == []


def test_resultado_septiembre(septiembre_procesado):
    conc = septiembre_procesado
    assert conteo(conc, "DEBITO") == {"OK": 82, "DIF_MONTO": 1, "DIGITACION": 3, "SIN_BORDERO": 4}
    assert conteo(conc, "CREDITO") == {"CUOTA": 2, "FUERA_PERIODO": 28, "DIF_MONTO": 1, "DIGITACION": 1,
                                       "SIN_BORDERO": 3, "OK": 4}
    # Spec §10 esperaba DIF_MONTO en 823431, pero el bordero tiene dos filas con ese documento y una calza
    # el monto exacto: la regla de menor diferencia la concilia (decisión registrada en el ledger).
    assert conteo(conc, "PREPAGO") == {"OK": 11, "DIGITACION": 1}

    dif = conc.ventas.get(codigo_autorizacion="007626")
    assert (dif.monto_original, dif.monto_bordero, dif.diferencia) == (115_204, 113_700, 1_504)
    assert conc.ventas.get(codigo_autorizacion="F0FUAZ").codigo_sugerido == "0FOFUAZ"
    cuota = conc.ventas.get(codigo_autorizacion="626135")
    assert (cuota.categoria, cuota.cuota) == ("CUOTA", "3/3")
    assert dif.codigo_sugerido == ""


def test_abonos_y_cuadratura(septiembre_procesado):
    conc = septiembre_procesado
    assert list(conc.abonos.values_list("categoria", flat=True)) == ["OK", "OK", "OK"]
    medios = conc.resumen["medios"]
    assert medios["DEBITO"]["abono_tbk"] == medios["DEBITO"]["abono_cartola"] == 5_269_462
    assert medios["CREDITO"]["abono_cartola"] == 2_597_371
    assert medios["PREPAGO"]["abono_cartola"] == 861_527
    assert conc.resumen["total"]["diferencial"] == 0
    assert all(m["cuadratura"] == 0 for m in medios.values())
    assert medios["DEBITO"]["n_falla"] == 8 and medios["CREDITO"]["n_falla"] == 5
    assert medios["PREPAGO"]["n_falla"] == 1


def test_pendientes_del_bordero(septiembre_procesado):
    conc = septiembre_procesado
    assert conc.resumen["n_pendientes"] == 123
    assert conc.resumen["n_invalidos_bordero"] == 1
    assert conc.pendientes.filter(abierto=True).count() == 123
