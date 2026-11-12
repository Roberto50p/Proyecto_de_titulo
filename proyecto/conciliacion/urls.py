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
    # Interfaz nueva en construcción; convive con la actual hasta reemplazarla.
    path("nuevo/", views.nuevo_inicio, name="nuevo_inicio"),
    path("nuevo/historial/", views.nuevo_lista, name="nuevo_lista"),
    path("nuevo/<int:pk>/", views.nuevo_archivos, name="nuevo_archivos"),
    path("nuevo/<int:pk>/revision/", views.nuevo_revision, name="nuevo_revision"),
    path("nuevo/<int:pk>/resultado/", views.nuevo_detalle, name="nuevo_detalle"),
]
