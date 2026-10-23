from django.urls import path

from . import views

app_name = "conciliacion"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("conciliaciones/", views.lista, name="lista"),
    path("conciliaciones/nueva/", views.nueva, name="nueva"),
    path("conciliaciones/<int:pk>/archivos/", views.archivos, name="archivos"),
    path("conciliaciones/<int:pk>/revision/", views.revision, name="revision"),
    path("conciliaciones/<int:pk>/procesar/", views.procesar, name="procesar"),
    path("conciliaciones/<int:pk>/", views.detalle, name="detalle"),
    path("conciliaciones/<int:pk>/pdf/", views.descargar_pdf, name="pdf"),
    path("conciliaciones/<int:pk>/excel/", views.descargar_excel, name="excel"),
    path("ventas/<int:pk>/revisar/", views.revisar_venta, name="revisar_venta"),
    path("pendientes/", views.pendientes, name="pendientes"),
    path("pendientes/<int:pk>/revisar/", views.revisar_pendiente, name="revisar_pendiente"),
    path("parametros/", views.parametros, name="parametros"),
]
