"""Modificar una conciliación ya procesada: cambiar archivos o rehacerla completa con archivos distintos."""

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from conciliacion.models import CoberturaBordero, Conciliacion, PagoBordero

from .conftest import ARCHIVOS_SEPTIEMBRE

BORDERO_SEPT = "BORDERO 04-09 A 07-09.xlsx"
BORDERO_OCT = "BORDERO DEBITO Y CREDITO OCTUBRE 2026.XLS"


@pytest.fixture
def cliente(client, db, media_temporal):
    client.force_login(User.objects.create_user("analista", password="clave-segura-123"))
    return client


def subir(carpeta, *nombres):
    return {"archivos": [SimpleUploadedFile(n, (carpeta / n).read_bytes()) for n in nombres]}


def url(nombre, conc):
    return reverse(f"conciliacion:{nombre}", args=[conc.pk])


@pytest.fixture
def septiembre(cliente, datos_reales):
    cliente.post(reverse("conciliacion:nueva"), {"anio": 2026, "mes": 9})
    conc = Conciliacion.objects.get()
    cliente.post(url("archivos", conc), subir(datos_reales, *ARCHIVOS_SEPTIEMBRE))
    cliente.post(url("procesar", conc))
    conc.refresh_from_db()
    assert conc.estado == Conciliacion.PROCESADA
    return conc


def test_cambiar_bordero_no_deja_pagos_ni_cobertura_del_anterior(cliente, septiembre, datos_octubre):
    assert septiembre.ventas.get(codigo_autorizacion="003098").categoria == "OK"
    bordero = septiembre.archivos.get(nombre=BORDERO_SEPT)
    cliente.post(url("archivos", septiembre), {"eliminar": bordero.pk})
    cliente.post(url("archivos", septiembre), subir(datos_octubre, BORDERO_OCT))
    cliente.post(url("procesar", septiembre))

    venta = septiembre.ventas.get(codigo_autorizacion="003098")
    # El bordero de septiembre ya no está: la venta no puede seguir cruzando con un pago suyo.
    assert venta.pago is None and venta.categoria == "FUERA_PERIODO"
    assert not PagoBordero.objects.filter(fecha__month=9).exists()
    assert not CoberturaBordero.objects.filter(desde__month=9).exists()


def test_agregar_archivo_a_conciliacion_procesada_la_deja_en_borrador(cliente, septiembre, datos_octubre):
    cliente.post(url("archivos", septiembre), subir(datos_octubre, "Cartola_1.xlsx"))
    septiembre.refresh_from_db()
    assert septiembre.estado == Conciliacion.BORRADOR
    assert cliente.get(url("detalle", septiembre)).status_code == 302


def test_cambiar_archivos_conserva_observaciones(cliente, septiembre, datos_reales):
    venta = septiembre.ventas.get(codigo_autorizacion="007626")
    cliente.post(reverse("conciliacion:revisar_venta", args=[venta.pk]),
                 {"revisado": "on", "observacion": "Se cobró propina aparte"})
    abono = septiembre.abonos.get(medio="DEBITO")
    abono.revisado, abono.observacion = True, "Confirmado con el banco"
    abono.save()

    debito = septiembre.archivos.get(medio="DEBITO")
    cliente.post(url("archivos", septiembre), {"eliminar": debito.pk})
    cliente.post(url("archivos", septiembre), subir(datos_reales, "DEBITOS TBK 08-09.xlsx"))
    cliente.post(url("procesar", septiembre))

    venta = septiembre.ventas.get(codigo_autorizacion="007626")
    assert (venta.revisado, venta.observacion) == (True, "Se cobró propina aparte")
    abono = septiembre.abonos.get(medio="DEBITO")
    assert (abono.revisado, abono.observacion) == (True, "Confirmado con el banco")


def test_conciliar_de_nuevo_con_otros_archivos(cliente, septiembre, datos_reales):
    total = septiembre.resumen["total"]
    r = cliente.post(url("archivos", septiembre), {"quitar_todos": "1"})
    assert r.status_code == 302
    septiembre.refresh_from_db()
    assert septiembre.estado == Conciliacion.BORRADOR and not septiembre.archivos.exists()
    assert not PagoBordero.objects.exists() and not CoberturaBordero.objects.exists()

    # Otra carga para el mismo mes: sin el archivo de prepago.
    cliente.post(url("archivos", septiembre), subir(datos_reales, *ARCHIVOS_SEPTIEMBRE[:4]))
    cliente.post(url("procesar", septiembre))
    septiembre.refresh_from_db()
    assert septiembre.estado == Conciliacion.PROCESADA
    assert septiembre.resumen["medios"]["PREPAGO"]["abono_tbk"] == 0
    assert septiembre.resumen["total"]["abono_tbk"] == total["abono_tbk"] - 861_527
    assert Conciliacion.objects.count() == 1
