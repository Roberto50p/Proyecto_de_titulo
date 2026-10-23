from datetime import date

import pandas as pd

from conciliacion.lectores.comunes import normalizar_codigo
from conciliacion.motor.cruce import conciliar_ventas, pagos_tarjeta
from conciliacion.motor.parametros import Parametros

COBERTURA = [(date(2026, 9, 4), date(2026, 9, 7))]
P = Parametros()


def venta(id, codigo, monto, fecha=date(2026, 9, 6), medio="DEBITO", cuota=None):
    num, total = cuota if cuota else (None, None)
    return {"id": id, "codigo_autorizacion": codigo, "codigo_norm": normalizar_codigo(codigo),
            "monto_original": monto, "fecha_venta": fecha, "medio": medio, "local": "Hotel",
            "cuota_num": num, "cuota_total": total}


def pago(id, documento, valor, fecha=date(2026, 9, 6), cod_deb="RCO", pendiente_mes=None):
    return {"id": id, "documento": documento, "documento_norm": normalizar_codigo(documento),
            "valor": valor, "fecha": fecha, "cod_deb": cod_deb, "pendiente_mes": pendiente_mes}


def cruzar(ventas, pagos, cobertura=COBERTURA):
    salida = conciliar_ventas(pd.DataFrame(ventas), pd.DataFrame(pagos), cobertura, P)
    return salida.set_index("venta_id")


def test_ok_con_ceros_y_redondeo():
    r = cruzar([venta(1, "003098", 57420)], [pago(10, "3098", -57421)]).loc[1]
    assert r.categoria == "OK" and r.pago_id == 10 and r.diferencia == -1 and r.monto_bordero == 57421


def test_dif_monto():
    r = cruzar([venta(1, "007626", 115204)], [pago(10, "7626", -113700)]).loc[1]
    assert r.categoria == "DIF_MONTO" and r.diferencia == 1504


def test_digitacion():
    r = cruzar([venta(1, "F0FUAZ", 106999)], [pago(10, "0FOFUAZ", -106999)]).loc[1]
    assert r.categoria == "DIGITACION" and r.codigo_sugerido == "0FOFUAZ" and r.pago_id == 10
    assert "F0FUAZ" in r.mensaje and "0FOFUAZ" in r.mensaje


def test_digitacion_exige_mismo_dia_y_monto():
    otro_dia = cruzar([venta(1, "F0FUAZ", 106999)], [pago(10, "0FOFUAZ", -106999, fecha=date(2026, 9, 5))])
    assert otro_dia.loc[1].categoria == "SIN_BORDERO"
    otro_monto = cruzar([venta(1, "F0FUAZ", 106999)], [pago(10, "0FOFUAZ", -100000)])
    assert otro_monto.loc[1].categoria == "SIN_BORDERO"


def test_digitacion_exige_codigo_parecido():
    r = cruzar([venta(1, "537834", 2700)], [pago(10, "991122", -2700)]).loc[1]
    assert r.categoria == "SIN_BORDERO"


def test_sin_bordero_y_fuera_periodo():
    r = cruzar([venta(1, "425788", 663663), venta(2, "070981", 8690, fecha=date(2026, 9, 3))], [])
    assert r.loc[1].categoria == "SIN_BORDERO"
    assert r.loc[2].categoria == "FUERA_PERIODO"


def test_cuota_fuera_cobertura():
    r = cruzar([venta(1, "659416", 618324, fecha=date(2026, 9, 3), medio="CREDITO", cuota=(1, 3))], [])
    assert r.loc[1].categoria == "CUOTA"
    assert "1/3" in r.loc[1].mensaje


def test_medio_distinto_y_precedencia():
    r = cruzar([venta(1, "531825", 5400, medio="CREDITO")], [pago(10, "531825", -5400, cod_deb="RCO")])
    assert r.loc[1].categoria == "MEDIO_DISTINTO"
    r = cruzar([venta(1, "531825", 5400, medio="CREDITO")], [pago(10, "531825", -9000, cod_deb="RCO")])
    assert r.loc[1].categoria == "DIF_MONTO"


def test_pago_usado_una_vez():
    r = cruzar([venta(1, "6842", 51150), venta(2, "006842", 51150)], [pago(10, "6842", -51150)])
    assert sorted(r.categoria) == ["OK", "SIN_BORDERO"]


def test_codigo_igual_pero_lejos_en_fecha_no_cruza():
    r = cruzar([venta(1, "6842", 51150)], [pago(10, "6842", -51150, fecha=date(2026, 8, 20))])
    assert r.loc[1].categoria == "SIN_BORDERO"


def test_cierra_pendiente():
    r = cruzar([venta(1, "829911", 30000)], [pago(10, "829911", -30000, pendiente_mes="Agosto 2026")]).loc[1]
    assert r.categoria == "OK" and "cierra pendiente de Agosto 2026" in r.nota


def test_dato_invalido():
    r = cruzar([venta(1, "", 5000)], [pago(10, "5000", -5000)]).loc[1]
    assert r.categoria == "DATO_INVALIDO"


def test_toda_venta_clasificada():
    ventas = [venta(i, f"{i:06d}", 1000 * i) for i in range(1, 8)]
    pagos = [pago(100 + i, f"{i}", -1000 * i) for i in range(1, 4)]
    r = cruzar(ventas, pagos)
    assert len(r) == 7 and r.categoria.notna().all()
    assert r.pago_id.dropna().is_unique


def test_pagos_tarjeta_marca_reversas():
    mov = pd.DataFrame([pago(1, "1", -100, cod_deb="RCO"), pago(2, "2", 100, cod_deb="V$"),
                        pago(3, "3", -500, cod_deb="HOA")])
    t = pagos_tarjeta(mov, P).set_index("id")
    assert list(t.index) == [1, 2]
    assert not t.loc[1, "invalido"] and t.loc[2, "invalido"]
