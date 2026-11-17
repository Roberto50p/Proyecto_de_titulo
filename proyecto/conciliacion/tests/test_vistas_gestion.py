import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from datetime import date

from conciliacion.models import ArchivoCargado, Conciliacion, EquivalenciaMedio, PagoBordero, Pendiente
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


def test_pendientes_abiertos(cliente, septiembre_procesado):
    html = cliente.get(reverse("conciliacion:pendientes")).content.decode()
    pendiente = Pendiente.objects.filter(abierto=True).select_related("pago").order_by("pago__fecha", "pago__hora", "pk").first()
    assert "123 pendientes abiertos" in html
    assert pendiente.pago.documento in html and septiembre_procesado.etiqueta in html
    assert "Conciliación de origen" in html


def test_pendientes_paginados_de_a_30(cliente, septiembre_procesado):
    url = reverse("conciliacion:pendientes")
    html = cliente.get(url).content.decode()
    assert html.count('class="paginacion"') == 2  # arriba y abajo de la tabla
    assert html.count('<tr class="fila-medio-') == 30 and "Página 1 de 5" in html
    ultima = cliente.get(url, {"page": 5}).content.decode()
    assert ultima.count('<tr class="fila-medio-') == 3 and "Página 5 de 5" in ultima
    assert "Página 5 de 5" in cliente.get(url, {"page": "999"}).content.decode()  # fuera de rango: última
    medio = Pendiente.objects.filter(abierto=True).values_list("medio", flat=True).first()
    filtrado = cliente.get(url, {"medio": medio}).content.decode()
    # el filtro se mantiene (la moneda siempre va: CLP por defecto)
    assert f"medio={medio}&amp;moneda=CLP&amp;page=" in filtrado or 'class="paginacion"' not in filtrado


def test_filtro_moneda_en_historial_y_pendientes(cliente):
    """La moneda sale de ArchivoCargado.moneda ("Pesos chilenos" / "Dólares"); el bordero no la informa."""
    def conciliacion(moneda, dia, documento):
        c = Conciliacion.objects.create()
        ArchivoCargado.objects.create(conciliacion=c, tipo="transbank", nombre=f"{documento}.xlsx", sha256=documento,
                                      moneda=moneda, fecha_abono=date(2026, 9, dia), archivo="x.xlsx")
        pago = PagoBordero.objects.create(cod_deb="VI", valor=1000, documento=documento, fecha=date(2026, 9, dia))
        Pendiente.objects.create(pago=pago, medio="CREDITO", origen=c)
        return c

    clp, usd = conciliacion("Pesos chilenos", 1, "DOC-CLP"), conciliacion("Dólares", 2, "DOC-USD")
    por_defecto = cliente.get(reverse("conciliacion:pendientes")).content.decode()
    assert "DOC-CLP" in por_defecto and "DOC-USD" not in por_defecto  # sin elegir: CLP
    assert 'value="CLP" class="boton moneda" aria-pressed="true"' in por_defecto
    # En USD el grupo "Medio de pago" muestra las tarjetas; el medio en pesos se descarta al cambiar.
    en_usd = cliente.get(reverse("conciliacion:pendientes"), {"moneda": "USD", "medio": "DEBITO"}).content.decode()
    assert all(f">{t}</button>" in en_usd for t in ("Amex", "Diners", "Mastercard", "Visa"))
    assert ">Débito</button>" not in en_usd and ">Débito</button>" in por_defecto
    assert 'name="medio" value=""' in en_usd  # el hidden quedó vacío
    for nombre, texto in (("conciliacion:lista", "etiqueta"), ("conciliacion:pendientes", "documento")):
        valor = {"etiqueta": lambda c: c.etiqueta, "documento": lambda c: c.pendientes.get().pago.documento}[texto]
        url = reverse(nombre)
        solo_clp = cliente.get(url, {"moneda": "CLP"}).content.decode()
        solo_usd = cliente.get(url, {"moneda": "USD"}).content.decode()
        assert valor(clp) in solo_clp and valor(usd) not in solo_clp
        assert valor(usd) in solo_usd and valor(clp) not in solo_usd

    # Archivos en ambas monedas: la conciliación aparece en CLP y en USD.
    ArchivoCargado.objects.create(conciliacion=clp, tipo="cartola", nombre="cartola-usd.xlsx", sha256="mixto",
                                  moneda="Dólares", archivo="x.xlsx")
    for moneda in ("CLP", "USD"):
        assert clp.etiqueta in cliente.get(reverse("conciliacion:lista"), {"moneda": moneda}).content.decode()


def test_comentar_pendiente(cliente, septiembre_procesado):
    p = Pendiente.objects.first()
    r = cliente.post(reverse("conciliacion:revisar_pendiente", args=[p.pk]),
                     {"observacion": "Transbank lo abona el lunes", "revisado": "on"})
    assert r.status_code == 302
    p.refresh_from_db()
    assert p.observacion == "Transbank lo abona el lunes" and p.revisado


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


def test_corregir_venta_desde_el_recuadro(cliente, septiembre_procesado):
    conc = septiembre_procesado
    v = conc.ventas.get(codigo_autorizacion="007626")
    volver = reverse("conciliacion:detalle", args=[conc.pk]) + "?vista=DEBITO&categoria=DIF_MONTO"
    html = cliente.get(volver).content.decode()
    assert f'data-recuadro="c{v.pk}"' in html and "Resolver" in html and "Volver a conciliar" in html
    r = cliente.post(reverse("conciliacion:corregir_venta", args=[v.pk]),
                     {"accion": "guardar", "aceptada": "on", "comentario": "Propina cobrada aparte", "volver": volver})
    assert r.status_code == 302 and r.url == f"{volver}#v{v.pk}"  # vuelve a la fila, con el recuadro cerrado
    assert conc.correcciones.get().comentario == "Propina cobrada aparte"
    html = cliente.get(volver).content.decode()
    assert "Propina cobrada aparte" in html and "falta volver a conciliar" in html and "Quitar corrección" in html
    assert "Editar" not in html
    # Volver a conciliar desde la misma vista la verifica.
    cliente.post(reverse("conciliacion:procesar", args=[conc.pk]), {"volver": volver})
    assert conc.ventas.get(codigo_autorizacion="007626").categoria == "CORREGIDO"


def test_corregir_sin_comentario_al_aceptar_no_guarda(cliente, septiembre_procesado):
    v = septiembre_procesado.ventas.get(codigo_autorizacion="007626")
    r = cliente.post(reverse("conciliacion:corregir_venta", args=[v.pk]), {"accion": "guardar", "aceptada": "on"})
    assert not septiembre_procesado.correcciones.exists()
    assert r.url.endswith(f"#c{v.pk}")  # si no se guardó, el recuadro vuelve abierto


def test_corregir_venta_no_redirige_fuera(cliente, septiembre_procesado):
    v = septiembre_procesado.ventas.first()
    r = cliente.post(reverse("conciliacion:corregir_venta", args=[v.pk]),
                     {"accion": "quitar", "volver": "https://example.com/"})
    assert r.url == reverse("conciliacion:detalle", args=[septiembre_procesado.pk]) + f"#v{v.pk}"


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
