"""Archivos Transbank que ya se conciliaron en otra conciliación: se detectan, bloquean y se pueden reemplazar."""

from datetime import date

import pandas as pd
import pytest

from conciliacion.lectores.transbank import leer_transbank
from conciliacion.models import ArchivoCargado, Conciliacion, VentaTransbank
from conciliacion.servicio import conflictos, procesar, reemplazar, validar

CREDITOS = "CREDITOS TBK 08-09.xlsx"


def _venta_de(datos, nombre):
    """Primera venta con código del archivo (preferentemente en cuotas)."""
    ventas = leer_transbank(datos / nombre).ventas
    ventas = ventas[(ventas.tipo_movimiento.str.lower() == "venta") & (ventas.codigo_norm != "")]
    con_cuota = ventas[ventas.cuota_num.notna()]
    return (con_cuota if not con_cuota.empty else ventas).iloc[0]


def _conciliacion_con_venta(fila, cuota_num, fecha_venta=None):
    """Otra conciliación (procesada) con un archivo Transbank de otro día que ya trae esa venta."""
    otra = Conciliacion.objects.create(estado=Conciliacion.PROCESADA)
    archivo = ArchivoCargado.objects.create(
        conciliacion=otra, tipo=ArchivoCargado.TRANSBANK, nombre="abono anterior.xlsx", sha256="otro",
        moneda="Pesos chilenos", fecha_abono=date(2026, 9, 1), por_medio={fila.medio: {}}, archivo="x.xlsx")
    VentaTransbank.objects.create(
        conciliacion=otra, archivo=archivo, medio=fila.medio, fecha_venta=fecha_venta or fila.fecha_venta,
        monto_original=fila.monto_original, codigo_autorizacion=fila.codigo_autorizacion,
        codigo_norm=fila.codigo_norm, cuota_num=cuota_num)
    return archivo


def _cuota(fila):
    return None if pd.isna(fila.cuota_num) else int(fila.cuota_num)


def test_mismos_transbank_en_otra_conciliacion_bloquean(septiembre_procesado, crear_conciliacion):
    nueva = crear_conciliacion()
    choques = conflictos(nueva)
    transbank = nueva.archivos.filter(tipo=ArchivoCargado.TRANSBANK)
    assert set(choques) == {a.id for a in transbank}
    assert all(o.conciliacion == septiembre_procesado for otros in choques.values() for o in otros)
    assert any(f"ya se concilió en Conciliación N° {septiembre_procesado.pk}" in e for e in validar(nueva))


def test_cartola_y_bordero_repetidos_no_bloquean(septiembre_procesado, crear_conciliacion):
    nueva = crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx", "cartola.xlsx"])
    assert conflictos(nueva) == {}


def test_venta_repetida_por_codigo(crear_conciliacion, datos_reales):
    fila = _venta_de(datos_reales, CREDITOS)
    anterior = _conciliacion_con_venta(fila, _cuota(fila))
    nueva = crear_conciliacion([CREDITOS])
    assert conflictos(nueva) == {nueva.archivos.get().id: [anterior]}


def test_otra_cuota_no_es_duplicado(crear_conciliacion, datos_reales):
    fila = _venta_de(datos_reales, CREDITOS)
    _conciliacion_con_venta(fila, (_cuota(fila) or 0) + 1)
    nueva = crear_conciliacion([CREDITOS])
    assert conflictos(nueva) == {}


def test_mismo_codigo_en_otra_venta_no_es_duplicado(crear_conciliacion, datos_reales):
    """Los códigos de autorización se repiten con el tiempo: otra fecha de venta es otra venta."""
    fila = _venta_de(datos_reales, CREDITOS)
    _conciliacion_con_venta(fila, _cuota(fila), fecha_venta=date(2026, 5, 2))
    nueva = crear_conciliacion([CREDITOS])
    assert conflictos(nueva) == {}


def test_borrador_abandonado_no_bloquea(crear_conciliacion):
    crear_conciliacion()  # se subieron los archivos pero nunca se concilió
    nueva = crear_conciliacion()
    assert conflictos(nueva) == {}


def test_revision_lee_cada_transbank_una_vez(cliente, crear_conciliacion, monkeypatch):
    from django.urls import reverse

    from conciliacion import servicio

    nueva = crear_conciliacion()
    lecturas = []
    original = servicio.leer_transbank
    monkeypatch.setattr(servicio, "leer_transbank", lambda ruta: lecturas.append(ruta) or original(ruta))
    cliente.get(reverse("conciliacion:revision", args=[nueva.pk]))
    assert len(lecturas) == 3


def test_transbank_con_error_en_otra_conciliacion_no_cuenta(septiembre_procesado, crear_conciliacion):
    septiembre_procesado.archivos.filter(tipo=ArchivoCargado.TRANSBANK).update(error="dañado")
    VentaTransbank.objects.all().delete()
    nueva = crear_conciliacion()
    assert conflictos(nueva) == {}


def test_reemplazar_quita_de_la_anterior(septiembre_procesado, crear_conciliacion):
    anterior = septiembre_procesado
    venta = anterior.ventas.filter(medio="DEBITO", categoria="OK").first()
    venta.observacion = "Revisado con el banco"
    venta.save()
    ok_debito = anterior.ventas.filter(medio="DEBITO", categoria="OK").count()

    nueva = crear_conciliacion()
    debito = nueva.archivos.get(medio="DEBITO")
    assert reemplazar(debito) == [anterior]

    anterior.refresh_from_db()
    assert anterior.estado == Conciliacion.BORRADOR
    assert not anterior.archivos.filter(medio="DEBITO").exists()
    assert any(v[1] == "Revisado con el banco" for v in anterior.observaciones["ventas"].values())
    assert debito.id not in conflictos(nueva)

    procesar(nueva)
    assert nueva.ventas.filter(medio="DEBITO", categoria="OK").count() == ok_debito


# ---- En pantalla: enlace a la otra conciliación y botón Reemplazar

@pytest.fixture
def cliente(client, db, media_temporal):
    from django.contrib.auth.models import User

    client.force_login(User.objects.create_user("analista", password="clave-segura-123"))
    return client


def test_archivos_muestra_enlace_y_boton_reemplazar(cliente, septiembre_procesado, crear_conciliacion):
    from django.urls import reverse

    nueva = crear_conciliacion()
    html = cliente.get(reverse("conciliacion:archivos", args=[nueva.pk])).content.decode()
    assert reverse("conciliacion:detalle", args=[septiembre_procesado.pk]) in html
    assert "Ya conciliado en <a" in html and f">Conciliación N° {septiembre_procesado.pk}</a>" in html
    assert html.count('name="reemplazar"') == 3


def test_boton_reemplazar(cliente, septiembre_procesado, crear_conciliacion):
    from django.urls import reverse

    nueva = crear_conciliacion()
    debito = nueva.archivos.get(medio="DEBITO")
    r = cliente.post(reverse("conciliacion:archivos", args=[nueva.pk]), {"reemplazar": debito.pk}, follow=True)
    assert r.redirect_chain[-1][0] == reverse("conciliacion:archivos", args=[nueva.pk])
    assert f"Conciliación N° {septiembre_procesado.pk}, que volvió a borrador" in r.content.decode()
    septiembre_procesado.refresh_from_db()
    assert septiembre_procesado.estado == Conciliacion.BORRADOR
    assert debito.id not in conflictos(nueva)


def test_revision_bloquea_con_duplicado(cliente, septiembre_procesado, crear_conciliacion):
    from django.urls import reverse

    nueva = crear_conciliacion()
    html = cliente.get(reverse("conciliacion:revision", args=[nueva.pk])).content.decode()
    assert 'disabled' in html.split('name="procesar"')[1].split(">")[0]
    assert reverse("conciliacion:detalle", args=[septiembre_procesado.pk]) in html
