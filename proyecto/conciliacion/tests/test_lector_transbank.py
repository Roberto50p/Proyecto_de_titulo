from datetime import date

import pandas as pd
import pytest

from conciliacion.lectores.comunes import (
    ArchivoNoReconocido,
    normalizar_codigo,
    parse_fecha_dmy,
    parse_fecha_es,
)
from conciliacion.lectores.transbank import leer_transbank


def test_normalizar_codigo():
    assert normalizar_codigo("003098") == "3098"
    assert normalizar_codigo(" 0fofuaz ") == "FOFUAZ"
    assert normalizar_codigo(3098) == "3098"
    assert normalizar_codigo(float("nan")) == ""
    assert normalizar_codigo(None) == ""


def test_parse_fechas():
    assert parse_fecha_es("07 septiembre 2026") == date(2026, 9, 7)
    assert parse_fecha_es("04 julio 2026") == date(2026, 7, 4)
    assert parse_fecha_dmy("04/09/2026") == date(2026, 9, 4)


def test_lee_debito_real(datos_reales):
    a = leer_transbank(datos_reales / "DEBITOS TBK 08-09.xlsx")
    assert (a.medio, a.fecha_abono, a.moneda) == ("DEBITO", date(2026, 9, 8), "Pesos")
    assert a.cuenta == "BANCO DE CHILE 6211002"
    assert a.resumen["total_abono"] == 5_269_462
    assert len(a.ventas) == 90
    assert a.ventas.monto_abono_valido.sum() == a.resumen["total_ventas"] == 5_331_713
    fila = a.ventas.set_index("codigo_autorizacion").loc["003098"]
    assert fila.codigo_norm == "3098" and fila.monto_original == 57_420
    assert fila.local == "Restaurant Bristol"


def test_lee_credito_cuotas(datos_reales):
    v = leer_transbank(datos_reales / "CREDITOS TBK 08-09.xlsx").ventas.set_index("codigo_autorizacion")
    assert (v.loc["659416", "cuota_num"], v.loc["659416", "cuota_total"]) == (1, 3)
    assert v.loc["659416", "monto_original"] == 618_324
    assert v.loc["659416", "monto_abono_valido"] == 206_108
    assert v.loc["626135", "fecha_venta"] == date(2026, 7, 4)
    assert pd.isna(v.loc["531825", "cuota_num"])


def test_prepago_total(datos_reales):
    a = leer_transbank(datos_reales / "PREPAGO TBK 08-09.xlsx")
    assert a.medio == "PREPAGO"
    assert a.resumen["total_abono"] == 861_527


def test_archivo_ajeno(tmp_path):
    p = tmp_path / "x.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(p)
    with pytest.raises(ArchivoNoReconocido):
        leer_transbank(p)
