from datetime import date

import pandas as pd
import pytest

from conciliacion.lectores.bordero import leer_bordero
from conciliacion.lectores.cartola import leer_cartola
from conciliacion.lectores.comunes import ArchivoNoReconocido
from conciliacion.lectores.deteccion import detectar


def test_bordero_real(datos_reales):
    b = leer_bordero(datos_reales / "BORDERO 04-09 A 07-09.xlsx")
    assert (b.desde, b.hasta) == (date(2026, 9, 4), date(2026, 9, 7))
    m = b.movimientos
    assert len(m) == 1859
    assert not m.cod_deb.isin(["Cod. Deb.", ""]).any()
    assert (m.cod_deb == "RCO").sum() == 143
    fila = m[m.documento_norm == "3098"].iloc[0]
    assert fila.valor == -57_421 and fila.fecha == date(2026, 9, 7)


def test_cartola_real(datos_reales):
    c = leer_cartola(datos_reales / "cartola.xlsx")
    assert c.cuenta == "00-000-62110-02"
    assert c.moneda.startswith("Pesos")
    del_dia = c.movimientos[c.movimientos.fecha == date(2026, 9, 8)]
    assert {861_527, 5_269_462, 2_597_371} <= set(del_dia.abono)
    assert c.hasta == date(2026, 9, 8)
    assert c.desde <= date(2026, 9, 1)


def test_detecta_tipos(datos_reales):
    assert detectar(datos_reales / "cartola.xlsx") == "cartola"
    assert detectar(datos_reales / "BORDERO 04-09 A 07-09.xlsx") == "bordero"
    assert detectar(datos_reales / "PREPAGO TBK 08-09.xlsx") == "transbank"


def test_detecta_no_reconocido(tmp_path):
    p = tmp_path / "otro.xlsx"
    pd.DataFrame({"x": [1]}).to_excel(p)
    with pytest.raises(ArchivoNoReconocido):
        detectar(p)
    q = tmp_path / "doc.pdf"
    q.write_bytes(b"%PDF-1.4 esto no es excel")
    with pytest.raises(ArchivoNoReconocido):
        detectar(q)
