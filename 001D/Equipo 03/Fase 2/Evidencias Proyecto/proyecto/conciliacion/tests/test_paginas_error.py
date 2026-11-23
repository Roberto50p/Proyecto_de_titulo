"""Cada error muestra la página propia del sistema y nunca la página técnica de Django (pytest corre con DEBUG
apagado, como el sistema por defecto)."""

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

PAGINA_DJANGO = ("Traceback", "Django tried these URL patterns", "Using the URLconf", "Request Method:")


def es_propia(r, codigo, titulo):
    html = r.content.decode()
    assert r.status_code == codigo
    assert titulo in html and f"Error {codigo}" in html
    assert "app.css" in html  # usa el diseño del sistema
    assert not any(t in html for t in PAGINA_DJANGO)
    return html


@pytest.fixture
def conectado(db):
    c = Client()
    c.force_login(User.objects.create_user("analista_errores"))
    return c


def test_url_inexistente_sin_sesion(client, db):
    """CP-03: escribir una dirección a mano (por ejemplo /historial) sin haber iniciado sesión."""
    html = es_propia(client.get("/historial/"), 404, "Página no encontrada")
    assert reverse("login") in html and "Iniciar sesión" in html


def test_pantalla_real_sin_sesion_sigue_pidiendo_login(client, db):
    r = client.get(reverse("conciliacion:lista"))
    assert r.status_code == 302 and r.url.startswith(reverse("login"))


def test_url_inexistente_con_sesion(conectado):
    html = es_propia(conectado.get("/historial/"), 404, "Página no encontrada")
    assert "Ir al inicio" in html


def test_registro_inexistente(conectado):
    """Una conciliación que no existe (o que se eliminó en Gestión de datos)."""
    es_propia(conectado.get(reverse("conciliacion:detalle", args=[999999])), 404, "Página no encontrada")
    es_propia(conectado.get(reverse("conciliacion:pdf", args=[999999])), 404, "Página no encontrada")


@pytest.mark.parametrize("ruta", ["conciliacion:limpiar_base", "conciliacion:exportar_datos",
                                  "conciliacion:eliminar_datos", "logout"])
def test_accion_post_abierta_a_mano(conectado, ruta):
    """Acciones que solo funcionan desde su botón: antes mostraban una página en blanco."""
    r = conectado.get(reverse(ruta))
    es_propia(r, 405, "Acción no permitida")
    assert "POST" in r["Allow"]


def test_accion_post_de_una_venta_abierta_a_mano(conectado):
    es_propia(conectado.get(reverse("conciliacion:corregir_venta", args=[1])), 405, "Acción no permitida")


def test_formulario_caducado(db):
    """Formulario enviado sin un token CSRF válido (página abierta mucho tiempo o sesión cambiada)."""
    c = Client(enforce_csrf_checks=True)
    es_propia(c.post(reverse("login"), {"username": "x", "password": "y"}), 403, "La página caducó")


def test_solicitud_no_valida(client, db):
    """Host no permitido: Django responde 400."""
    es_propia(client.get("/", HTTP_HOST="sitio-falso.example"), 400, "Solicitud no válida")


def test_error_interno(conectado, monkeypatch):
    """Cualquier excepción en una vista (por ejemplo, una base sin migrar) muestra la página 500."""
    import conciliacion.views as vistas

    def falla(*args, **kwargs):
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(vistas, "render", falla)
    conectado.raise_request_exception = False
    es_propia(conectado.get(reverse("conciliacion:lista")), 500, "Ocurrió un error inesperado")


def test_acceso_denegado(rf, db):
    from django.views.defaults import permission_denied

    r = permission_denied(rf.get("/"), PermissionDenied())
    assert r.status_code == 403 and "Acceso denegado" in r.content.decode()


def test_estilos_disponibles_con_debug_apagado(client, db):
    """Con DEBUG apagado el CSS se sigue sirviendo en local (si no, las páginas se verían sin diseño)."""
    r = client.get("/static/conciliacion/app.css")
    assert r.status_code == 200 and b"n-error-acciones" in b"".join(r.streaming_content)
