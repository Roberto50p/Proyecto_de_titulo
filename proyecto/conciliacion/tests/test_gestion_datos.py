import os
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from conciliacion.models import (ArchivoCargado, CoberturaBordero, Conciliacion, MovimientoCartola, PagoBordero,
                                 Pendiente, VentaDolar, VentaTransbank)
from conciliacion.servicio import seleccionar


def _con_abonos(*dias):
    conc = Conciliacion.objects.create()
    for i, dia in enumerate(dias):
        ArchivoCargado.objects.create(conciliacion=conc, tipo=ArchivoCargado.TRANSBANK, archivo=f"tbk{i}.xlsx",
                                      nombre=f"tbk{i}.xlsx", sha256=f"{conc.pk}-{i}", fecha_abono=dia)
    return conc


@pytest.fixture
def administrador(client, db, media_temporal):
    client.force_login(User.objects.create_superuser("jefe", password="clave-segura-123"))
    return client


@pytest.mark.django_db
def test_filtro_incluye_solo_periodos_completos_dentro_del_rango():
    agosto = _con_abonos(date(2026, 8, 30), date(2026, 9, 1))  # cruza el inicio del rango
    septiembre = _con_abonos(date(2026, 9, 1), date(2026, 9, 30))  # justo en los extremos
    octubre = _con_abonos(date(2026, 10, 1))
    sin_abonos = _con_abonos(date(2026, 12, 1))
    ArchivoCargado.objects.filter(conciliacion=sin_abonos).update(error="ilegible")  # solo un archivo con error
    hoy = timezone.localdate(sin_abonos.creada_en)  # sin abonos válidos cuenta el día en que se creó

    def ids(desde=None, hasta=None):
        return {c.pk for c in seleccionar(desde, hasta)}

    assert ids(date(2026, 9, 1), date(2026, 9, 30)) == {septiembre.pk}
    assert ids(hasta=date(2026, 9, 30)) == {agosto.pk, septiembre.pk}
    assert ids(desde=date(2026, 10, 1), hasta=date(2026, 10, 1)) == {octubre.pk}
    assert ids(desde=hoy, hasta=hoy) == {sin_abonos.pk}
    assert ids() == {agosto.pk, septiembre.pk, octubre.pk, sin_abonos.pk}


def test_filtro_rechaza_desde_posterior_a_tope(administrador):
    _con_abonos(date(2026, 9, 1))
    r = administrador.get(reverse("conciliacion:datos"), {"desde": "2026-10-01", "hasta": "2026-09-01"})
    assert "no puede ser posterior" in r.content.decode()
    assert r.context["conciliaciones"] == []


def test_eliminar_exige_exportar_la_misma_seleccion(administrador):
    septiembre = _con_abonos(date(2026, 9, 10))
    octubre = _con_abonos(date(2026, 10, 10))
    url_eliminar = reverse("conciliacion:eliminar_datos")

    administrador.post(url_eliminar, {"hasta": "2026-09-30", "confirmacion": "ELIMINAR"})
    assert Conciliacion.objects.count() == 2  # sin exportar

    administrador.post(reverse("conciliacion:exportar_datos"), {"hasta": "2026-09-30"})
    administrador.post(url_eliminar, {"hasta": "2026-10-31", "confirmacion": "ELIMINAR"})
    assert Conciliacion.objects.count() == 2  # el filtro abarca más de lo exportado

    administrador.post(url_eliminar, {"hasta": "2026-09-30", "confirmacion": "otra cosa"})
    assert Conciliacion.objects.count() == 2  # sin confirmar

    administrador.post(url_eliminar, {"hasta": "2026-09-30", "confirmacion": "eliminar"})
    assert list(Conciliacion.objects.values_list("pk", flat=True)) == [octubre.pk]
    assert not Conciliacion.objects.filter(pk=septiembre.pk).exists()

    administrador.post(url_eliminar, {"hasta": "2026-09-30", "confirmacion": "ELIMINAR"})
    assert Conciliacion.objects.filter(pk=octubre.pk).exists()


def test_analista_no_puede_exportar_ni_eliminar(client, db):
    _con_abonos(date(2026, 9, 10))
    client.force_login(User.objects.create_user("analista", password="clave-segura-123"))
    assert client.get(reverse("conciliacion:datos")).status_code == 302
    r = client.post(reverse("conciliacion:exportar_datos"))
    assert r.status_code == 302 and "datos_exportados" not in client.session
    client.post(reverse("conciliacion:eliminar_datos"), {"confirmacion": "ELIMINAR"})
    assert Conciliacion.objects.exists()


def test_exportar_y_eliminar_conciliacion_real(administrador, septiembre_procesado):
    otra = _con_abonos(date(2026, 12, 1))
    hasta = septiembre_procesado.archivos.filter(tipo=ArchivoCargado.TRANSBANK).latest("fecha_abono").fecha_abono
    rutas = [a.archivo.path for a in septiembre_procesado.archivos.all()]
    ventas = septiembre_procesado.ventas.count()
    pendientes = septiembre_procesado.pendientes.count()

    r = administrador.post(reverse("conciliacion:exportar_datos"), {"hasta": hasta.isoformat()})
    assert r["Content-Disposition"].startswith('attachment; filename="respaldo_conciliaciones_')
    libro = load_workbook(BytesIO(r.content))
    assert libro.sheetnames == ["Conciliaciones", "Archivos", "Ventas Transbank", "Abonos", "Ventas US$",
                                "Abonos US$", "Cartola", "Pendientes", "Correcciones manuales", "Pagos bordero"]
    assert libro["Ventas Transbank"].max_row == ventas + 1
    assert libro["Pendientes"].max_row == pendientes + 1
    codigos = {fila[15] for fila in libro["Ventas Transbank"].iter_rows(min_row=2, values_only=True)}
    assert "007626" in codigos  # el código conserva sus ceros

    administrador.post(reverse("conciliacion:eliminar_datos"), {"hasta": hasta.isoformat(), "confirmacion": "ELIMINAR"})
    assert list(Conciliacion.objects.all()) == [otra]
    for modelo in (VentaTransbank, Pendiente, PagoBordero, CoberturaBordero, MovimientoCartola):
        assert not modelo.objects.exists()
    assert ArchivoCargado.objects.filter(conciliacion=otra).count() == 1
    assert rutas and not any(os.path.exists(ruta) for ruta in rutas)


def test_respalda_y_elimina_conciliacion_en_dolares(administrador):
    conc = Conciliacion.objects.create(moneda=Conciliacion.USD, estado=Conciliacion.PROCESADA, resumen={
        "total": {"abono_tbk": 194.37},
        "abonos": [{"monto": "194.37", "fecha_abono": "2025-12-03", "en_cartola": True, "cartola_fecha": "2025-12-04",
                    "cartola_descripcion": "Abono Transbank", "mensaje": "Llegó a la cartola."}]})
    abono = ArchivoCargado.objects.create(conciliacion=conc, tipo=ArchivoCargado.ABONO_USD, archivo="usd.xlsx",
                                          nombre="usd.xlsx", sha256="usd", fecha_abono=date(2025, 12, 3))
    VentaDolar.objects.create(conciliacion=conc, archivo=abono, tarjeta="AX", fecha_venta=date(2025, 11, 26),
                              codigo_autorizacion="115111", monto_original=Decimal("194.37"),
                              categoria=VentaDolar.OK)
    filtro = {"desde": "2025-12-01", "hasta": "2025-12-31"}  # el período es el día del abono US$, no la creación

    r = administrador.post(reverse("conciliacion:exportar_datos"), filtro)
    libro = load_workbook(BytesIO(r.content))
    ventas = list(libro["Ventas US$"].iter_rows(min_row=2, values_only=True))
    assert len(ventas) == 1 and ventas[0][4] == "115111" and ventas[0][5] == 194.37  # con centavos
    assert list(libro["Abonos US$"].iter_rows(min_row=2, values_only=True))[0][2] == 194.37

    administrador.post(reverse("conciliacion:eliminar_datos"), filtro | {"confirmacion": "ELIMINAR"})
    assert not Conciliacion.objects.exists() and not VentaDolar.objects.exists()
