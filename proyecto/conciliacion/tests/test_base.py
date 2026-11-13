def test_inicio_requiere_login(client):
    respuesta = client.get("/")
    assert respuesta.status_code == 302
    assert respuesta.url == "/login/?next=/"


def test_login_muestra_formulario(client, db):
    respuesta = client.get("/login/")
    assert respuesta.status_code == 200
    assert "Ingresar" in respuesta.content.decode()


def test_conciliaciones_sin_mes_se_pueden_repetir(db):
    from conciliacion.models import Conciliacion

    a = Conciliacion.objects.create()
    b = Conciliacion.objects.create()
    assert a.etiqueta == "Conciliación sin abonos cargados"
    assert list(Conciliacion.objects.all()) == [b, a]


def test_etiqueta_por_periodo_de_abono(db):
    from datetime import date

    from conciliacion.models import ArchivoCargado, Conciliacion

    c = Conciliacion.objects.create()
    tbk = dict(conciliacion=c, tipo=ArchivoCargado.TRANSBANK, archivo="x.xlsx")
    ArchivoCargado.objects.create(nombre="a", sha256="a", fecha_abono=date(2026, 11, 3), **tbk)
    assert c.etiqueta == "Conciliación del 03/11/2026"
    ArchivoCargado.objects.create(nombre="b", sha256="b", fecha_abono=date(2026, 11, 5), **tbk)
    ArchivoCargado.objects.create(nombre="c", sha256="c", fecha_abono=date(2026, 11, 9), error="malo", **tbk)
    ArchivoCargado.objects.create(nombre="d", sha256="d", tipo=ArchivoCargado.CARTOLA, conciliacion=c,
                                  archivo="y.xlsx", desde=date(2026, 10, 1), hasta=date(2026, 11, 30))
    assert c.etiqueta == "Conciliación del 03/11/2026 al 05/11/2026"


def test_inicio_y_archivos(client, db):
    from django.contrib.auth.models import User
    from django.urls import reverse

    from conciliacion.models import Conciliacion

    client.force_login(User.objects.create_user("u"))
    assert "Nueva conciliación" in client.get(reverse("conciliacion:inicio")).content.decode()
    assert "Cargar" in client.get(reverse("conciliacion:clp")).content.decode()
    c = Conciliacion.objects.create()
    html = client.get(reverse("conciliacion:archivos", args=[c.pk])).content.decode()
    assert "file-check.svg" in html and "Continuar revisión" in html
    html = client.get(reverse("conciliacion:revision", args=[c.pk])).content.decode()
    assert "Revisión de lectura" in html and "banner.webp" in html


def test_etiqueta_repetida_agrega_fecha_de_creacion(db):
    from datetime import date

    from conciliacion.models import ArchivoCargado, Conciliacion

    a, b = Conciliacion.objects.create(), Conciliacion.objects.create()
    for c, h in ((a, "a"), (b, "b")):
        ArchivoCargado.objects.create(conciliacion=c, tipo=ArchivoCargado.TRANSBANK, archivo="x.xlsx", nombre=h,
                                      sha256=h, fecha_abono=date(2026, 9, 8))
    assert a.etiqueta.startswith("Conciliación del 08/09/2026 (creada el ")
    ArchivoCargado.objects.create(conciliacion=b, tipo=ArchivoCargado.TRANSBANK, archivo="x.xlsx", nombre="c",
                                  sha256="c", fecha_abono=date(2026, 9, 9))
    assert a.etiqueta == "Conciliación del 08/09/2026"


def test_historial(client, db):
    from django.contrib.auth.models import User
    from django.urls import reverse

    from conciliacion.models import Conciliacion

    client.force_login(User.objects.create_user("u"))
    c = Conciliacion.objects.create()
    html = client.get(reverse("conciliacion:lista")).content.decode()
    assert "Historial de conciliaciones" in html and c.etiqueta in html
    assert reverse("conciliacion:archivos", args=[c.pk]) in html


def test_resultado_sin_procesar_lleva_a_revision(client, db):
    from django.contrib.auth.models import User
    from django.urls import reverse

    from conciliacion.models import Conciliacion

    client.force_login(User.objects.create_user("u"))
    c = Conciliacion.objects.create()
    r = client.get(reverse("conciliacion:detalle", args=[c.pk]))
    assert r.url == reverse("conciliacion:revision", args=[c.pk])
    r = client.post(reverse("conciliacion:procesar", args=[c.pk]))
    assert r.url == reverse("conciliacion:revision", args=[c.pk])


def test_todas_las_paginas_usan_la_barra_y_el_banner(client, db):
    from django.contrib.auth.models import User
    from django.urls import reverse

    from conciliacion.models import Conciliacion

    client.force_login(User.objects.create_user("u"))
    c = Conciliacion.objects.create()
    urls = [reverse("conciliacion:inicio"), reverse("conciliacion:lista"), reverse("conciliacion:pendientes"),
            reverse("conciliacion:parametros"), reverse("conciliacion:archivos", args=[c.pk]),
            reverse("conciliacion:revision", args=[c.pk])]
    for url in urls:
        html = client.get(url).content.decode()
        assert "n-lateral" in html and "banner.webp" in html, url
