from django.urls import path

from . import views

app_name = "conciliacion"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("conciliaciones/", views.lista, name="lista"),
    path("conciliaciones/nueva/", views.lista, name="nueva"),
    path("pendientes/", views.lista, name="pendientes"),
    path("parametros/", views.lista, name="parametros"),
]
