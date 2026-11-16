import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from conciliacion.models import EquivalenciaMedio, Pendiente
from conciliacion.servicio import parametros_actuales

PARAMETROS = {"tolerancia_clp": 200, "umbral_similitud": 0.8, "dias_holgura": 2, "ventana_dias": 3,
              "patrones_cartola": "transbank, tbk"}


@pytest.fixture
def cliente(client, db, media_temporal):
    client.force_login(User.objects.create_user("analista", password="clave-segura-123"))
    return client


def test_lista_muestra_conciliaciones(cliente, septiembre_procesado):
    html = cliente.get(reverse("conciliacion:lista")).content.decode()
    assert septiembre_procesado.etiqueta in html
    assert reverse("conciliacion:detalle", args=[septiembre_procesado.pk]) in html
    assert "$8.728.360" in html and ">14<" in html


def test_guardar_parametros(cliente):
    r = cliente.post(reverse("conciliacion:parametros"), PARAMETROS)
    assert r.status_code == 302
    p = parametros_actuales()
    assert (p.tolerancia_clp, p.umbral_similitud, p.dias_holgura) == (200, 0.8, 2)


def test_parametros_invalidos(cliente):
    r = cliente.post(reverse("conciliacion:parametros"), {**PARAMETROS, "tolerancia_clp": -5})
    assert r.status_code == 200
    assert "error" in r.content.decode()
    assert parametros_actuales().tolerancia_clp == 100


def test_equivalencias(cliente):
    cliente.post(reverse("conciliacion:parametros"), {"agregar_equivalencia": "1", "cod_deb": "DUS$",
                                                      "medio": "CREDITO"})
    assert "CREDITO" in parametros_actuales().medios_de("DUS$")
    e = EquivalenciaMedio.objects.get(cod_deb="DUS$")
    cliente.post(reverse("conciliacion:parametros"), {"quitar_equivalencia": e.pk})
    assert parametros_actuales().medios_de("DUS$") == frozenset()


def test_revisar_venta_vuelve_al_filtro(cliente, septiembre_procesado):
    v = septiembre_procesado.ventas.get(codigo_autorizacion="007626")
    volver = reverse("conciliacion:detalle", args=[septiembre_procesado.pk]) + "?vista=DEBITO&categoria=DIF_MONTO"
    r = cliente.post(reverse("conciliacion:revisar_venta", args=[v.pk]),
                     {"observacion": "Propina cobrada aparte", "revisado": "on", "volver": volver})
    assert r.status_code == 302 and r.url == volver
    v.refresh_from_db()
    assert v.observacion == "Propina cobrada aparte" and v.revisado
    assert "Propina cobrada aparte" in cliente.get(volver).content.decode()


def test_revisar_venta_no_redirige_fuera(cliente, septiembre_procesado):
    v = septiembre_procesado.ventas.first()
    r = cliente.post(reverse("conciliacion:revisar_venta", args=[v.pk]),
                     {"observacion": "x", "volver": "https://example.com/"})
    assert r.url == reverse("conciliacion:detalle", args=[septiembre_procesado.pk])


def test_limpiar_base_borra_conciliaciones_y_conserva_parametros(client, septiembre_procesado):
    from conciliacion.models import (ArchivoCargado, CoberturaBordero, Conciliacion, MovimientoCartola,
                                     PagoBordero, ParametrosSistema)
    rutas = [ac.archivo.path for ac in ArchivoCargado.objects.all()]
    client.force_login(User.objects.create_superuser("jefe", password="clave-segura-123"))
    assert "Limpiar base de datos" in client.get(reverse("conciliacion:inicio")).content.decode()
    client.post(reverse("conciliacion:limpiar_base"), {"confirmacion": "limpiar"})
    for modelo in (Conciliacion, ArchivoCargado, PagoBordero, Pendiente, CoberturaBordero, MovimientoCartola):
        assert not modelo.objects.exists()
    assert ParametrosSistema.objects.exists() and EquivalenciaMedio.objects.exists()
    import os
    assert rutas and not any(os.path.exists(r) for r in rutas)


def test_limpiar_base_exige_confirmacion_y_superusuario(cliente, septiembre_procesado):
    from conciliacion.models import Conciliacion
    assert "Limpiar base de datos" not in cliente.get(reverse("conciliacion:inicio")).content.decode()
    cliente.post(reverse("conciliacion:limpiar_base"), {"confirmacion": "LIMPIAR"})  # analista sin permiso
    assert Conciliacion.objects.exists()
    cliente.get(reverse("conciliacion:inicio"))
    User.objects.filter(username="analista").update(is_superuser=True)
    cliente.post(reverse("conciliacion:limpiar_base"), {"confirmacion": "otra cosa"})
    assert Conciliacion.objects.exists()
