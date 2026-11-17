import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from conciliacion.models import ArchivoCargado, Conciliacion

from .conftest import ARCHIVOS_SEPTIEMBRE


@pytest.fixture
def cliente(client, db, media_temporal):
    client.force_login(User.objects.create_user("analista", password="clave-segura-123"))
    return client


def subir(datos, nombre):
    return SimpleUploadedFile(nombre, (datos / nombre).read_bytes())


def nueva(cliente):
    return cliente.post(reverse("conciliacion:nueva"))


def test_flujo_completo(cliente, datos_reales):
    r = nueva(cliente)
    conc = Conciliacion.objects.get()
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
    hoy = timezone.localdate().strftime("%d-%m-%Y")
    assert f'filename="conciliacion_{hoy}.xlsx"' in xls["Content-Disposition"]
    assert f'filename="conciliacion_{hoy}.pdf"' in pdf["Content-Disposition"]


def test_nueva_dos_veces_no_crea_borradores_vacios(cliente):
    nueva(cliente)
    r = nueva(cliente)
    assert Conciliacion.objects.count() == 1
    assert r.status_code == 302 and r.url == reverse("conciliacion:archivos", args=[Conciliacion.objects.get().pk])


def test_nueva_se_puede_repetir_cuando_la_anterior_tiene_archivos(cliente, septiembre_procesado):
    nueva(cliente)
    assert Conciliacion.objects.count() == 2


def test_archivos_no_enlaza_a_nueva_por_get(cliente):
    nueva(cliente)
    conc = Conciliacion.objects.get()
    html = cliente.get(reverse("conciliacion:archivos", args=[conc.pk])).content.decode()
    assert f'href="{reverse("conciliacion:nueva")}"' not in html


def test_nueva_no_reutiliza_una_conciliacion_ya_procesada_y_vaciada(cliente, septiembre_procesado):
    from conciliacion.servicio import quitar_todos

    quitar_todos(septiembre_procesado)
    r = nueva(cliente)
    assert Conciliacion.objects.count() == 2
    assert r.url != reverse("conciliacion:archivos", args=[septiembre_procesado.pk])


def test_lista_no_pide_mes(cliente):
    html = cliente.get(reverse("conciliacion:lista")).content.decode()
    assert "Mes de abono" not in html
    assert f'href="{reverse("conciliacion:inicio")}"' in html


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


@pytest.mark.parametrize("nombre", ["nueva", "lista", "parametros"])
def test_requiere_login(client, db, nombre):
    r = client.get(reverse(f"conciliacion:{nombre}"))
    assert r.status_code == 302 and r.url.startswith("/login/")


def test_requiere_login_detalle(client, db):
    conc = Conciliacion.objects.create()
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


def test_corregir_vuelve_a_la_misma_fila(cliente, septiembre_procesado):
    v = septiembre_procesado.ventas.get(codigo_autorizacion="007626")
    html = cliente.get(reverse("conciliacion:detalle", args=[septiembre_procesado.pk]) + "?vista=DEBITO").content.decode()
    assert f'id="v{v.pk}"' in html and f'id="c{v.pk}"' in html  # fila y su recuadro (el guardado vuelve a #v)


def test_credito_fallas_y_avisos_en_una_tabla(cliente, septiembre_procesado):
    """Crédito: 5 fallas y 30 avisos (ventas del 03/09 sin bordero y cuotas) en la misma tabla, fallas primero."""
    url = reverse("conciliacion:detalle", args=[septiembre_procesado.pk])
    html = cliente.get(url + "?vista=CREDITO").content.decode()
    assert 'aria-label="35 registros"' in html
    assert 'Por revisar <span class="contador">35</span>' in html and "bloque-avisos" not in html
    assert html.count('<tr id="v') == 35
    tipos = [c.split('"')[0] for c in html.split('<span class="etiqueta tipo-')[1:]]
    assert tipos.index("Aviso") >= 5 and "Operación" not in tipos[tipos.index("Aviso"):]  # fallas antes que avisos
    filtrado = cliente.get(url + "?vista=CREDITO&categoria=FUERA_PERIODO").content.decode()
    assert filtrado.count('<tr id="v') == 28


def test_advierte_ventas_de_credito_sin_bordero(cliente, septiembre_procesado):
    html = cliente.get(reverse("conciliacion:revision", args=[septiembre_procesado.pk])).content.decode()
    assert "CREDITOS TBK 08-09.xlsx: 31 ventas del 03/09/2026 sin bordero que cubra esa fecha" in html
    assert "DEBITOS TBK 08-09.xlsx:" not in html.split("sin bordero")[0].rsplit("</li>", 1)[-1]
