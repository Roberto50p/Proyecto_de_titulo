"""Formatos que entregó el hotel en octubre: bordero .XLS (Excel 4.0), cartolas BancoEstado, Transbank con
todos los medios de pago en un archivo y un abono en dólares."""

from datetime import date

import pytest

from conciliacion.lectores.bordero import leer_bordero
from conciliacion.lectores.cartola import leer_cartola
from conciliacion.lectores.deteccion import detectar
from conciliacion.lectores.transbank import leer_transbank
from conciliacion.models import ArchivoCargado, ParametrosSistema
from conciliacion.motor import categorias as cat
from conciliacion.motor.parametros import Parametros, leer_reglas_medio
from conciliacion.servicio import advertencias, procesar, validar

BORDERO = "BORDERO DEBITO Y CREDITO OCTUBRE 2026.XLS"


def test_bordero_excel_4(datos_octubre):
    b = leer_bordero(datos_octubre / BORDERO)
    assert (b.desde, b.hasta) == (date(2026, 10, 1), date(2026, 10, 22))
    m = b.movimientos
    assert len(m) == 10_722 and (m.cod_deb == "RCO").sum() == 936
    assert "CCAÑAS" in set(m.usuario)  # sin página de códigos: se lee como Windows-1252
    fila = m[(m.cod_deb == "RCO") & (m.documento_norm == "27397")].iloc[0]
    assert (fila.valor, fila.fecha, fila.factura) == (-76_560, date(2026, 10, 21), "54214")


def test_cartola_bancoestado(datos_octubre):
    c = leer_cartola(datos_octubre / "Cartola_1.xlsx")
    assert (c.banco, c.cuenta, c.moneda) == ("BancoEstado", "00000523356", "Pesos")
    assert (c.desde, c.hasta) == (date(2026, 10, 20), date(2026, 10, 20))
    assert sorted(c.movimientos.abono) == [404_461, 1_459_396, 6_463_399]
    varios_dias = leer_cartola(datos_octubre / "Cartola_3.xlsx")
    assert (varios_dias.desde, varios_dias.hasta) == (date(2026, 10, 16), date(2026, 10, 19))


def test_transbank_todos_los_medios(datos_octubre):
    a = leer_transbank(datos_octubre / "TBK.xls")
    assert a.medio is None and a.fecha_abono == date(2026, 10, 22)
    assert a.ventas.medio.value_counts().to_dict() == {"DEBITO": 54, "CREDITO": 19, "PREPAGO": 7}
    abonos = {m: r["total_abono"] for m, r in a.resumen_por_medio.items()}
    assert abonos == {"DEBITO": 1_061_455, "CREDITO": 5_833_221, "PREPAGO": 262_347}
    assert sum(abonos.values()) == a.resumen["total_abono"]
    assert sum(r["total_ventas"] for r in a.resumen_por_medio.values()) == a.resumen["total_ventas"]


def test_detecta_formatos_octubre(datos_octubre):
    assert detectar(datos_octubre / BORDERO) == "bordero"
    assert detectar(datos_octubre / "Cartola_9.xlsx") == "cartola"
    assert detectar(datos_octubre / "TBK_5.xls") == "transbank"


def test_dolares_bloquean_salvo_que_se_omitan(octubre_cargado):
    usd = octubre_cargado.archivos.get(nombre="TBK_5.xls")
    assert usd.tipo == ArchivoCargado.TRANSBANK and usd.moneda_extranjera and not usd.error
    assert any(e.startswith("TBK_5.xls: moneda no soportada (Dólares)") for e in validar(octubre_cargado))

    ParametrosSistema.objects.filter(pk=1).update(omitir_moneda_extranjera=True)
    assert validar(octubre_cargado) == []
    assert any(a.startswith("TBK_5.xls: está en Dólares; se omite") for a in advertencias(octubre_cargado))


def test_procesa_octubre_separando_medios(octubre_cargado):
    ParametrosSistema.objects.filter(pk=1).update(omitir_moneda_extranjera=True)
    conc = procesar(octubre_cargado)

    tbk = conc.archivos.get(nombre="TBK.xls")
    abonos = {r.medio: r for r in tbk.resultados_abono.all()}
    assert {m: r.total_abono for m, r in abonos.items()} == {
        cat.DEBITO: 1_061_455, cat.CREDITO: 5_833_221, cat.PREPAGO: 262_347}
    # Las cartolas llegan hasta el 20/10 y el abono es del 22/10.
    assert all(r.categoria == cat.ABONO_CARTOLA and "no cubre el 22/10/2026" in r.mensaje for r in abonos.values())

    assert conc.ventas.filter(archivo__nombre="TBK_5.xls").count() == 0
    assert conc.ventas.filter(es_venta=True).count() == 80
    medios = conc.resumen["medios"]
    assert medios[cat.CREDITO]["abono_tbk"] == 5_833_221 and medios[cat.CREDITO]["ventas"] == 5_930_743
    assert all(medios[m]["cuadratura"] == 0 for m in cat.MEDIOS)

    transbank = conc.movimientos_cartola.filter(es_transbank=True)
    assert transbank.count() == conc.resumen["cartola_sin_archivo"]["n"] == 22
    assert {m.medio_probable for m in transbank if "tarjeta debito" in m.descripcion.lower()} == {"Débito o prepago"}
    assert {m.medio_probable for m in transbank if "pagos varios" in m.descripcion.lower()} == {"Sin determinar"}


def test_reglas_medio_cartola():
    reglas = leer_reglas_medio("pagos varios transbank = Crédito\n\n Transbank = Débito o prepago ")
    assert reglas == (("pagos varios transbank", "Crédito"), ("Transbank", "Débito o prepago"))
    p = Parametros(reglas_medio_cartola=reglas)
    assert p.medio_probable("Pagos varios TRANSBANK rut 96689310-9") == "Crédito"  # gana la primera
    assert p.medio_probable("Abono transbank tarjeta débito") == "Débito o prepago"
    assert p.medio_probable("Transferencia") == "Sin determinar"
    with pytest.raises(ValueError, match="Línea 2"):
        leer_reglas_medio("tc tbk = Crédito\nsin igual")
