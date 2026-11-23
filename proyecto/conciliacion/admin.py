from django.contrib import admin

from .models import (
    ArchivoCargado,
    Conciliacion,
    EquivalenciaMedio,
    PagoBordero,
    ParametrosSistema,
    Pendiente,
    ResultadoAbono,
    VentaTransbank,
)


@admin.register(Conciliacion)
class ConciliacionAdmin(admin.ModelAdmin):
    list_display = ["etiqueta", "estado", "creada_por", "procesada_en"]


@admin.register(ArchivoCargado)
class ArchivoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "conciliacion", "tipo", "medio", "fecha_abono", "error"]
    list_filter = ["tipo", "medio"]


@admin.register(VentaTransbank)
class VentaAdmin(admin.ModelAdmin):
    list_display = ["codigo_autorizacion", "medio", "fecha_venta", "monto_original", "categoria", "conciliacion"]
    list_filter = ["medio", "categoria", "conciliacion"]
    search_fields = ["codigo_autorizacion"]


@admin.register(PagoBordero)
class PagoAdmin(admin.ModelAdmin):
    list_display = ["documento", "cod_deb", "fecha", "valor", "conciliacion"]
    list_filter = ["cod_deb"]
    search_fields = ["documento"]


admin.site.register([ResultadoAbono, Pendiente, ParametrosSistema, EquivalenciaMedio])
