from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import servicio
from .forms import MesForm
from .models import ArchivoCargado, Conciliacion
from .motor import categorias as cat
from .reportes import excel, pdf
from .reportes.datos import armar

PASOS = ["Mes de abono", "Archivos", "Revisión de lectura", "Resultado"]
VISTAS = ["resumen", cat.DEBITO, cat.CREDITO, cat.PREPAGO, "pendientes"]


def _pasos(actual: int) -> list[dict]:
    return [{"numero": i, "nombre": n, "estado": "actual" if i == actual else "hecho" if i < actual else ""}
            for i, n in enumerate(PASOS, 1)]


@login_required
def inicio(request):
    return redirect("conciliacion:lista")


@login_required
def lista(request):
    return render(request, "conciliacion/lista.html", {"conciliaciones": []})


# ------------------------------------------------------------------ asistente


@login_required
def nueva(request):
    form = MesForm(request.POST or None)
    existente = None
    if request.method == "POST" and form.is_valid():
        anio, mes = form.cleaned_data["anio"], form.cleaned_data["mes"]
        existente = Conciliacion.objects.filter(anio=anio, mes=mes).first()
        if existente is None:
            conc = Conciliacion.objects.create(anio=anio, mes=mes, creada_por=request.user)
            return redirect("conciliacion:archivos", conc.pk)
        if existente.estado == Conciliacion.BORRADOR or request.POST.get("confirmar"):
            return redirect("conciliacion:archivos", existente.pk)
    return render(request, "conciliacion/nueva_mes.html",
                  {"form": form, "existente": existente, "pasos": _pasos(1)})


@login_required
def archivos(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    if request.method == "POST":
        if "eliminar" in request.POST:
            ac = get_object_or_404(ArchivoCargado, pk=request.POST["eliminar"], conciliacion=conc)
            ac.archivo.delete(save=False)
            ac.delete()
            messages.info(request, f"Se quitó {ac.nombre}.")
            return redirect("conciliacion:archivos", conc.pk)
        subidos = request.FILES.getlist("archivos")
        if not subidos:
            messages.error(request, "Selecciona al menos un archivo.")
        for f in subidos:
            huella = servicio.sha256_de(f)
            if conc.archivos.filter(sha256=huella).exists():
                messages.warning(request, f"Archivo duplicado: {f.name} ya estaba cargado; no se agregó de nuevo.")
                continue
            ac = ArchivoCargado(conciliacion=conc, nombre=f.name, sha256=huella)
            ac.archivo.save(f.name, f, save=False)
            ac.save()
            servicio.leer_archivo(ac)
            if ac.error:
                messages.error(request, f"{ac.nombre}: {ac.error}")
            else:
                messages.success(request, f"{ac.nombre}: leído como {ac.get_tipo_display()}"
                                          f"{' ' + ac.get_medio_display() if ac.medio else ''}.")
        return redirect("conciliacion:archivos", conc.pk)
    return render(request, "conciliacion/nueva_archivos.html",
                  {"conc": conc, "archivos": conc.archivos.all(), "pasos": _pasos(2)})


@login_required
def revision(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    return render(request, "conciliacion/nueva_revision.html", {
        "conc": conc, "archivos": conc.archivos.all(), "errores": servicio.validar(conc),
        "avisos": servicio.advertencias(conc), "pasos": _pasos(3),
    })


@login_required
@require_POST
def procesar(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    errores = servicio.validar(conc)
    if errores:
        for e in errores:
            messages.error(request, e)
        return redirect("conciliacion:revision", conc.pk)
    servicio.procesar(conc)
    messages.success(request, f"Conciliación de {conc.etiqueta} procesada.")
    return redirect("conciliacion:detalle", conc.pk)


# ------------------------------------------------------------------ resultado


@login_required
def detalle(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    if conc.estado != Conciliacion.PROCESADA:
        return redirect("conciliacion:revision", conc.pk)
    datos = armar(conc)
    vista = request.GET.get("vista", "resumen")
    vista = vista if vista in VISTAS else "resumen"
    filtro_cat = request.GET.get("categoria", "")
    filtro_local = request.GET.get("local", "")

    registros, categorias, locales = [], [], []
    capitulo = datos["capitulos"].get(vista)
    if capitulo:
        todos = capitulo["fallas"] + capitulo["avisos"] + capitulo["conciliados"]
        categorias = [(k, cat.ETIQUETA[k], sum(1 for v in todos if v.categoria == k))
                      for k in cat.ORDEN_CATEGORIAS if any(v.categoria == k for v in todos)]
        locales = sorted({v.local for v in todos})
        if filtro_cat:
            registros = [v for v in todos if v.categoria == filtro_cat]
        else:
            registros = capitulo["fallas"] + capitulo["avisos"]
        if filtro_local:
            registros = [v for v in registros if v.local == filtro_local]

    pestanas = [{"clave": "resumen", "nombre": "Resumen", "n": None}]
    for m in cat.MEDIOS:
        pestanas.append({"clave": m, "nombre": cat.ETIQUETA_MEDIO[m],
                         "n": datos["capitulos"][m]["resumen"].get("n_falla", 0)})
    pestanas.append({"clave": "pendientes", "nombre": "Pendientes", "n": len(datos["pendientes"])})

    return render(request, "conciliacion/resultado.html", {
        "conc": conc, "d": datos, "vista": vista, "capitulo": capitulo, "registros": registros,
        "categorias": categorias, "locales": locales, "filtro_cat": filtro_cat, "filtro_local": filtro_local,
        "pestanas": pestanas, "pasos": _pasos(4),
        "fallas_todas": sorted((v for m in cat.MEDIOS for v in datos["capitulos"][m]["fallas"]),
                               key=lambda v: (cat.GRAVEDAD[v.tipo], cat.MEDIOS.index(v.medio), v.fecha_venta)),
    })


@login_required
def descargar_pdf(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk, estado=Conciliacion.PROCESADA)
    respuesta = HttpResponse(pdf.generar(conc), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="conciliacion_{conc.anio}_{conc.mes:02d}.pdf"'
    return respuesta


@login_required
def descargar_excel(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk, estado=Conciliacion.PROCESADA)
    respuesta = HttpResponse(excel.generar(conc),
                             content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="conciliacion_{conc.anio}_{conc.mes:02d}.xlsx"'
    return respuesta
