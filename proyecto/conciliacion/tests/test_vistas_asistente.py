import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from conciliacion.models import ArchivoCargado, Conciliacion

from .conftest import ARCHIVOS_SEPTIEMBRE


@pytest.fixture
def cliente(client, db, media_temporal):
    client.force_login(User.objects.create_user("analista", password="clave-segura-123"))
    return client


def subir(datos, nombre):
    return SimpleUploadedFile(nombre, (datos / nombre).read_bytes())


def nueva(cliente, anio=2026, mes=9, **extra):
    return cliente.post(reverse("conciliacion:nueva"), {"anio": anio, "mes": mes, **extra})


def test_flujo_completo(cliente, datos_reales):
    r = nueva(cliente)
    conc = Conciliacion.objects.get(anio=2026, mes=9)
    assert r.status_code == 302 and r.url == reverse("conciliacion:archivos", args=[conc.pk])

    r = cliente.post(reverse("conciliacion:archivos", args=[conc.pk]),
                     {"archivos": [subir(datos_reales, n) for n in ARCHIVOS_SEPTIEMBRE]})
    assert r.status_code == 302
    assert conc.archivos.count() == 5

    r = cliente.get(reverse("conciliacion:revision", args=[conc.pk]))
    html = r.content.decode()
    assert "Débito" in html and "Crédito" in html and "Prepago" in html
    assert "no reconocido" not in html.lower()
    assert 'name="procesar"' in html and "disabled" not in html.split('name="procesar"')[1].split(">")[0]

    r = cliente.post(reverse("conciliacion:procesar", args=[conc.pk]))
    assert r.status_code == 302 and r.url == reverse("conciliacion:detalle", args=[conc.pk])

    html = cliente.get(r.url).content.decode()
    for texto in ["Débito", "Crédito", "Prepago", "Diferencial", "F0FUAZ"]:
        assert texto in html
    html = cliente.get(r.url + "?vista=CREDITO&categoria=SIN_BORDERO").content.decode()
    assert "227735" in html and "007626" not in html

    pdf = cliente.get(reverse("conciliacion:pdf", args=[conc.pk]))
    assert pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    xls = cliente.get(reverse("conciliacion:excel", args=[conc.pk]))
    assert xls["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "conciliacion_2026_09.xlsx" in xls["Content-Disposition"]


def test_mes_existente_pide_confirmacion(cliente, septiembre_procesado):
    r = nueva(cliente)
    assert r.status_code == 200
    html = r.content.decode()
    assert "ya fue conciliado" in html and 'name="confirmar"' in html
    r = nueva(cliente, confirmar="1")
    assert r.status_code == 302 and r.url == reverse("conciliacion:archivos", args=[septiembre_procesado.pk])


def test_archivo_no_reconocido_bloquea(cliente, tmp_path):
    nueva(cliente)
    conc = Conciliacion.objects.get()
    cliente.post(reverse("conciliacion:archivos", args=[conc.pk]),
                 {"archivos": [SimpleUploadedFile("informe.pdf", b"%PDF-1.4 no es excel")]})
    html = cliente.get(reverse("conciliacion:revision", args=[conc.pk])).content.decode()
    assert "No reconocido" in html
    assert "disabled" in html.split('name="procesar"')[1].split(">")[0]
    r = cliente.post(reverse("conciliacion:procesar", args=[conc.pk]))
    assert r.status_code == 302 and r.url == reverse("conciliacion:revision", args=[conc.pk])
    assert Conciliacion.objects.get().estado == Conciliacion.BORRADOR


def test_abono_fuera_del_mes(cliente, datos_reales):
    nueva(cliente, mes=10)
    conc = Conciliacion.objects.get()
    cliente.post(reverse("conciliacion:archivos", args=[conc.pk]),
                 {"archivos": [subir(datos_reales, "DEBITOS TBK 08-09.xlsx")]})
    html = cliente.get(reverse("conciliacion:revision", args=[conc.pk])).content.decode()
    assert "la fecha de abono 08/09/2026 no pertenece a Octubre 2026" in html


def test_archivo_duplicado(cliente, datos_reales):
    nueva(cliente)
    conc = Conciliacion.objects.get()
    url = reverse("conciliacion:archivos", args=[conc.pk])
    cliente.post(url, {"archivos": [subir(datos_reales, "PREPAGO TBK 08-09.xlsx")]})
    r = cliente.post(url, {"archivos": [subir(datos_reales, "PREPAGO TBK 08-09.xlsx")]}, follow=True)
    assert "Archivo duplicado" in r.content.decode()
    assert ArchivoCargado.objects.count() == 1


def test_faltan_archivos(cliente, datos_reales):
    nueva(cliente)
    conc = Conciliacion.objects.get()
    cliente.post(reverse("conciliacion:archivos", args=[conc.pk]),
                 {"archivos": [subir(datos_reales, "PREPAGO TBK 08-09.xlsx")]})
    html = cliente.get(reverse("conciliacion:revision", args=[conc.pk])).content.decode()
    assert "Falta el bordero." in html and "Falta la cartola." in html


@pytest.mark.parametrize("nombre", ["nueva", "lista", "pendientes", "parametros"])
def test_requiere_login(client, db, nombre):
    r = client.get(reverse(f"conciliacion:{nombre}"))
    assert r.status_code == 302 and r.url.startswith("/login/")


def test_requiere_login_detalle(client, db):
    conc = Conciliacion.objects.create(anio=2026, mes=9)
    for nombre in ["archivos", "revision", "detalle", "pdf", "excel"]:
        r = client.get(reverse(f"conciliacion:{nombre}", args=[conc.pk]))
        assert r.status_code == 302 and r.url.startswith("/login/")


def test_quitar_archivo_de_conciliacion_procesada_la_deja_en_borrador(cliente, septiembre_procesado):
    from conciliacion.models import PagoBordero

    debito = septiembre_procesado.archivos.get(medio="DEBITO")
    cliente.post(reverse("conciliacion:archivos", args=[septiembre_procesado.pk]), {"eliminar": debito.pk})
    septiembre_procesado.refresh_from_db()
    assert septiembre_procesado.estado == Conciliacion.BORRADOR
    assert not PagoBordero.objects.filter(conciliacion=septiembre_procesado).exists()
    r = cliente.get(reverse("conciliacion:detalle", args=[septiembre_procesado.pk]))
    assert r.status_code == 302


def test_mismo_dia_y_medio_dos_veces_bloquea(cliente, datos_reales, tmp_path):
    from openpyxl import load_workbook

    nueva(cliente)
    conc = Conciliacion.objects.get()
    url = reverse("conciliacion:archivos", args=[conc.pk])
    cliente.post(url, {"archivos": [subir(datos_reales, "PREPAGO TBK 08-09.xlsx")]})
    libro = load_workbook(datos_reales / "PREPAGO TBK 08-09.xlsx")
    libro.active["A1"] = "copia descargada otra vez"
    copia = tmp_path / "PREPAGO otra vez.xlsx"
    libro.save(copia)
    cliente.post(url, {"archivos": [SimpleUploadedFile(copia.name, copia.read_bytes())]})
    html = cliente.get(reverse("conciliacion:revision", args=[conc.pk])).content.decode()
    assert "Hay 2 archivos Transbank de Prepago con abono del 08/09/2026" in html


def test_revisar_vuelve_a_la_misma_fila(cliente, septiembre_procesado):
    v = septiembre_procesado.ventas.get(codigo_autorizacion="007626")
    html = cliente.get(reverse("conciliacion:detalle", args=[septiembre_procesado.pk]) + "?vista=DEBITO").content.decode()
    assert f'id="v{v.pk}"' in html and f'#v{v.pk}"' in html
