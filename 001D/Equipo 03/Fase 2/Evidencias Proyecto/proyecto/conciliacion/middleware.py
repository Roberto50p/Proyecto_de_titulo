"""Páginas de error propias donde Django no usa una plantilla."""

from django.shortcuts import render


class PaginaMetodoNoPermitido:
    """Las vistas con @require_POST (guardar, conciliar, eliminar, cerrar sesión...) responden 405 con el cuerpo vacío
    si se abren escribiendo la dirección en el navegador: el usuario ve una página en blanco. Aquí se reemplaza esa
    respuesta vacía por la página 405.html, sin tocar las vistas."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        respuesta = self.get_response(request)
        if respuesta.status_code == 405 and not respuesta.streaming and not respuesta.content:
            pagina = render(request, "405.html", status=405)
            pagina["Allow"] = respuesta.get("Allow", "")
            return pagina
        return respuesta
