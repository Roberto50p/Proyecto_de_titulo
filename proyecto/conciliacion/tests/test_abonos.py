from datetime import date

import pandas as pd

from conciliacion.lectores.cartola import leer_cartola
from conciliacion.lectores.transbank import leer_transbank
from conciliacion.motor.abonos import conciliar_abonos, cuadratura_archivo
from conciliacion.motor.parametros import Parametros

P = Parametros()
RANGO = (date(2026, 9, 1), date(2026, 9, 30))


def linea(fecha, abono, descripcion="Pago: Abonos Realizados Por Transbank Al Comercio"):
    return {"fecha": fecha, "descripcion": descripcion, "abono": abono, "cargo": 0}


def abono(archivo_id, medio, fecha, total):
    return {"archivo_id": archivo_id, "medio": medio, "fecha_abono": fecha, "total_abono": total}


def test_tres_abonos_reales(datos_reales):
    cartola = leer_cartola(datos_reales / "cartola.xlsx")
    entradas = []
    for i, nombre in enumerate(["DEBITOS TBK 08-09.xlsx", "CREDITOS TBK 08-09.xlsx", "PREPAGO TBK 08-09.xlsx"]):
        a = leer_transbank(datos_reales / nombre)
        entradas.append(abono(i, a.medio, a.fecha_abono, a.resumen["total_abono"]))
    r = conciliar_abonos(entradas, cartola.movimientos, (cartola.desde, cartola.hasta), P)
    assert [x["categoria"] for x in r] == ["OK", "OK", "OK"]
    assert all(x["diferencia"] == 0 for x in r)
    assert r[1]["cartola_descripcion"].startswith("Pago: Abono Comer. Tc Tbk")


def test_abono_mismo_monto_dos_medios():
    cartola = pd.DataFrame([linea(date(2026, 9, 8), 1000), linea(date(2026, 9, 8), 1000)])
    r = conciliar_abonos([abono(1, "DEBITO", date(2026, 9, 8), 1000), abono(2, "PREPAGO", date(2026, 9, 8), 1000)],
                         cartola, RANGO, P)
    assert [x["categoria"] for x in r] == ["OK", "OK"]


def test_holgura_dia_habil():
    viernes, lunes = date(2026, 9, 4), date(2026, 9, 7)
    cartola = pd.DataFrame([linea(lunes, 5000)])
    r = conciliar_abonos([abono(1, "DEBITO", viernes, 5000)], cartola, RANGO, P)
    assert r[0]["categoria"] == "OK" and r[0]["cartola_fecha"] == lunes


def test_ignora_lineas_que_no_son_transbank():
    cartola = pd.DataFrame([linea(date(2026, 9, 8), 5000, "Pago: Proveedores 0856339009")])
    r = conciliar_abonos([abono(1, "DEBITO", date(2026, 9, 8), 5000)], cartola, RANGO, P)
    assert r[0]["categoria"] == "ABONO_CARTOLA"


def test_cartola_no_cubre():
    cartola = pd.DataFrame([linea(date(2026, 9, 8), 5000)])
    r = conciliar_abonos([abono(1, "DEBITO", date(2026, 10, 2), 5000)], cartola,
                         (date(2026, 9, 1), date(2026, 9, 30)), P)
    assert r[0]["categoria"] == "ABONO_CARTOLA"
    assert "no cubre" in r[0]["mensaje"]


def test_abono_con_diferencia():
    cartola = pd.DataFrame([linea(date(2026, 9, 8), 5500)])
    r = conciliar_abonos([abono(1, "DEBITO", date(2026, 9, 8), 5000)], cartola, RANGO, P)
    assert r[0]["categoria"] == "ABONO_CARTOLA" and r[0]["diferencia"] == -500
    assert r[0]["cartola_monto"] == 5500


def test_cuadratura_archivo_real(datos_reales):
    for nombre in ["DEBITOS TBK 08-09.xlsx", "CREDITOS TBK 08-09.xlsx", "PREPAGO TBK 08-09.xlsx"]:
        assert cuadratura_archivo(leer_transbank(datos_reales / nombre).resumen) == 0
