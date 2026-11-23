"""Conciliación en dólares: lectores, motor y servicio (sintético y con los archivos reales de diciembre)."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from django.urls import reverse

from conciliacion.lectores.comunes import a_decimal, a_entero, leer_hoja
from conciliacion.lectores.deteccion import detectar
from conciliacion.models import ArchivoCargado, Conciliacion, VentaDolar
from conciliacion.motor import dolar as usd
from conciliacion.motor.mensajes import dolares

ARCHIVOS_DOLAR = ["ABONO TBK 03122025.xlsx", "TERJETAS ERP.xlsx", "AMEX DOLAR.XLS", "DINERS DOLAR.XLS",
                  "VISA DOLAR.XLS", "MASTERCARD DOLAR.XLS", "cartola (2).xls"]


def test_montos_con_centavos():
    assert a_decimal(426.39) == Decimal("426.39") and a_decimal("1.234,56") == Decimal("1234.56")
    assert a_decimal("US$ 12,5") == Decimal("12.5") and a_decimal(None) == 0
    assert a_entero("16.258.428,00") == 16_258_428 and a_entero(-33440.0) == -33440  # pesos como antes
    assert dolares(Decimal("-1234.5")) == "-US$ 1.234,50" and dolares(None) == "-"


def test_motor_cruza_erp_y_cartera():
    ventas = pd.DataFrame([
        {"tarjeta": "VI", "codigo_autorizacion": "08273D", "codigo_norm": "8273D", "monto_original": Decimal("3"),
         "fecha_venta": date(2025, 11, 30)},
        {"tarjeta": "MC", "codigo_autorizacion": "R04218", "codigo_norm": "R04218", "monto_original": Decimal("12"),
         "fecha_venta": date(2025, 11, 25)},
        {"tarjeta": "MC", "codigo_autorizacion": "999", "codigo_norm": "999", "monto_original": Decimal("5"),
         "fecha_venta": date(2025, 11, 25)},
        {"tarjeta": "AX", "codigo_autorizacion": "111", "codigo_norm": "111", "monto_original": Decimal("7"),
         "fecha_venta": date(2025, 11, 25)},
        {"tarjeta": "AX", "codigo_autorizacion": "222", "codigo_norm": "222", "monto_original": Decimal("8"),
         "fecha_venta": date(2025, 11, 25)},
    ])
    erp = pd.DataFrame([  # el ERP rellena con ceros a la izquierda: "008273D" es el mismo código
        {"codigo_norm": "8273D", "documento": "100", "valor": 2790},
        {"codigo_norm": "R04218", "documento": "200", "valor": 10756},
        {"codigo_norm": "111", "documento": "300", "valor": 6500},
        {"codigo_norm": "222", "documento": "400", "valor": 7000},
    ])
    columnas = ["documento", "otra_moneda", "saldo", "saldo_corregido"]
    carteras = {
        "VI": pd.DataFrame([["100", Decimal("2.98"), Decimal("2790"), None]], columns=columnas),
        "MC": pd.DataFrame([["200", Decimal("11.57"), None, Decimal("10756")]], columns=columnas),
        "AX": pd.DataFrame([["300", Decimal("7"), Decimal("6000"), None]], columns=columnas),
    }
    r = usd.conciliar_ventas_dolar(ventas, erp, carteras)
    assert [x["categoria"] for x in r] == [usd.OK, usd.OK, usd.SIN_ERP, usd.SALDO_DISTINTO, usd.SIN_CARTERA]
    assert r[0]["diferencia"] == Decimal("0.02") and "Saldo de la cartera de Visa" in r[0]["mensaje"]
    assert r[1]["diferencia"] == Decimal("0.43") and "Saldo Corregido" in r[1]["mensaje"]
    assert r[2]["documento"] == "" and r[3]["valor_erp"] == 6500 and r[3]["monto_cartera"] is None


def test_abono_en_cartola():
    movimientos = pd.DataFrame([
        {"fecha": date(2025, 12, 1), "abono": Decimal("30972.29"), "descripcion": "antes"},
        {"fecha": date(2025, 12, 3), "abono": Decimal("30972.29"), "descripcion": "Transbank"},
    ])
    r = usd.verificar_abono(Decimal("30972.29"), date(2025, 12, 3), movimientos)
    assert r["en_cartola"] and r["cartola_fecha"] == "2025-12-03"
    assert not usd.verificar_abono(Decimal("30972.30"), date(2025, 12, 3), movimientos)["en_cartola"]


def test_lectores_y_deteccion_reales(datos_dolar):
    tipos = {n: detectar(datos_dolar / n) for n in ARCHIVOS_DOLAR}
    assert tipos == {"ABONO TBK 03122025.xlsx": "abono_usd", "TERJETAS ERP.xlsx": "erp", "AMEX DOLAR.XLS": "emisor",
                     "DINERS DOLAR.XLS": "emisor", "VISA DOLAR.XLS": "emisor", "MASTERCARD DOLAR.XLS": "emisor",
                     "cartola (2).xls": "cartola"}


@pytest.fixture
def dolar_procesado(db, datos_dolar, media_temporal):
    from conciliacion.servicio import procesar, validar

    from .conftest import _crear

    conc = _crear(datos_dolar, ARCHIVOS_DOLAR, moneda=Conciliacion.USD)
    assert validar(conc) == []
    return procesar(conc)


def test_procesa_dolares_como_el_proceso_anterior(dolar_procesado, datos_dolar):
    conc = dolar_procesado
    abono = conc.archivos.get(tipo=ArchivoCargado.ABONO_USD)
    assert not abono.moneda_extranjera and abono.fecha_abono == date(2025, 12, 3)  # en dólares no se omite
    assert conc.ventas_usd.count() == abono.filas == 110
    # La cartola trae US$ 30.972,22 el 03/12 y Transbank calcula US$ 30.972,29: no calza exacto (tampoco antes).
    abono_cartola = conc.resumen["abonos"][0]
    assert abono_cartola["en_cartola"] is False and "US$ 30.972,22" in abono_cartola["mensaje"]
    assert "diferencia US$ 0,07" in abono_cartola["mensaje"] and conc.resumen["total"]["diferencial"] == 30972.29

    # Mismas ventas "no ubicadas en el ERP" que la salida del proceso anterior.
    salida = datos_dolar / "archivos de salida de proceso"
    no_ubicadas = leer_hoja(salida / "transacciones_no_ubicadas.xlsx").iloc[2:, 0].dropna().astype(str)
    sin_erp = set(conc.ventas_usd.filter(categoria=VentaDolar.SIN_ERP).values_list("codigo_autorizacion", flat=True))
    assert sin_erp == set(no_ubicadas)

    # Mismo documento y diferencia en dólares en las que sí calzaron con la cartera.
    anterior = leer_hoja(salida / "informacion_proceso.xlsx").iloc[2:]
    esperadas = {str(f[0]): (str(f[1]), round(float(f[4]), 2)) for f in anterior.itertuples(index=False)
                 if not pd.isna(f[4]) and f[4] != ""}
    ok = {v.codigo_autorizacion: (v.documento, None if v.diferencia is None else float(v.diferencia))
          for v in conc.ventas_usd.filter(categoria=VentaDolar.OK)}
    distintas = {c: (e, ok.get(c)) for c, e in esperadas.items() if ok.get(c) != e}
    assert esperadas and not distintas


def test_vistas_dolar(client, dolar_procesado):
    from django.contrib.auth.models import User

    client.force_login(User.objects.create_user("analista", password="clave-segura-123"))
    html = client.get(reverse("conciliacion:detalle", args=[dolar_procesado.pk])).content.decode()
    assert "Resumen por tarjeta" in html and "US$" in html
    assert dolar_procesado.etiqueta in client.get(reverse("conciliacion:lista"), {"moneda": "USD"}).content.decode()
    assert dolar_procesado.etiqueta not in client.get(reverse("conciliacion:lista"), {"moneda": "CLP"}).content.decode()
    excel = client.get(reverse("conciliacion:excel", args=[dolar_procesado.pk]))
    assert excel.status_code == 200 and excel.content[:2] == b"PK"
    assert client.get(reverse("conciliacion:pdf", args=[dolar_procesado.pk])).status_code == 404
    assert "Conciliación USD" in client.get(reverse("conciliacion:usd")).content.decode()
    archivos = client.get(reverse("conciliacion:archivos", args=[dolar_procesado.pk])).content.decode()
    assert "Conciliación USD" in archivos and "no se concilia" not in archivos  # en dólares no se omite ninguno
    revision = client.get(reverse("conciliacion:revision", args=[dolar_procesado.pk])).content.decode()
    assert "US$ 30.972,29" in revision and "Mastercard US$" in revision
