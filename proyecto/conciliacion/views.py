from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import servicio
from .forms import MesForm, ParametrosForm, RevisionForm
from .models import (MEDIO_CHOICES, ArchivoCargado, Conciliacion, EquivalenciaMedio, ParametrosSistema, Pendiente,
                     VentaTransbank)
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
    return render(request, "conciliacion/lista.html", {"conciliaciones": Conciliacion.objects.all()})


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


def _aviso_reabierta(request, conc):
    messages.warning(request, f"{conc.etiqueta} volvió a borrador: conciliala de nuevo para ver el resultado con "
                              "los archivos actuales. Tus observaciones se conservan.")


@login_required
def archivos(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    if request.method == "POST":
        procesada = conc.estado == Conciliacion.PROCESADA
        if "eliminar" in request.POST:
            ac = get_object_or_404(ArchivoCargado, pk=request.POST["eliminar"], conciliacion=conc)
            servicio.quitar_archivo(ac)
            if procesada:
                _aviso_reabierta(request, conc)
            messages.info(request, f"Se quitó {ac.nombre}.")
            return redirect("conciliacion:archivos", conc.pk)
        if "quitar_todos" in request.POST:
            servicio.quitar_todos(conc)
            if procesada:
                _aviso_reabierta(request, conc)
            messages.info(request, f"Se quitaron todos los archivos de {conc.etiqueta}. Sube los nuevos para "
                                   "conciliarlo de nuevo.")
            return redirect("conciliacion:archivos", conc.pk)
        subidos = request.FILES.getlist("archivos")
        if not subidos:
            messages.error(request, "Selecciona al menos un archivo.")
        leidos = 0
        for f in subidos:
            huella = servicio.sha256_de(f)
            if conc.archivos.filter(sha256=huella).exists():
                messages.warning(request, f"Archivo duplicado: {f.name} ya estaba cargado; no se agregó de nuevo.")
                continue
            if conc.estado == Conciliacion.PROCESADA:
                servicio.reabrir(conc)
                _aviso_reabierta(request, conc)
            ac = ArchivoCargado(conciliacion=conc, nombre=f.name, sha256=huella)
            ac.archivo.save(f.name, f, save=False)
            ac.save()
            servicio.leer_archivo(ac)
            if ac.error:
                messages.error(request, f"{ac.nombre}: {ac.error}")
            else:
                leidos += 1
        if leidos:
            messages.success(request, f"{leidos} archivo{'s' if leidos > 1 else ''} leído{'s' if leidos > 1 else ''} "
                                      "correctamente. Revisa cómo se reconoció cada uno en la tabla.")
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


# ------------------------------------------------------------------ gestión


def _volver_seguro(request, por_defecto: str) -> str:
    destino = request.POST.get("volver", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
        return destino
    return por_defecto


@login_required
@require_POST
def revisar_venta(request, pk):
    venta = get_object_or_404(VentaTransbank, pk=pk)
    form = RevisionForm(request.POST)
    if form.is_valid():
        venta.revisado = form.cleaned_data["revisado"]
        venta.observacion = form.cleaned_data["observacion"]
        venta.save(update_fields=["revisado", "observacion"])
        messages.success(request, f"Observación guardada para {venta.codigo_autorizacion}.")
    return redirect(_volver_seguro(request, reverse("conciliacion:detalle", args=[venta.conciliacion_id])))


@login_required
def pendientes(request):
    abiertos = Pendiente.objects.filter(abierto=True).select_related("pago", "origen")
    medio_filtro = request.GET.get("medio", "")
    if medio_filtro:
        abiertos = abiertos.filter(medio=medio_filtro)
    return render(request, "conciliacion/pendientes.html", {
        "pendientes": abiertos.order_by("pago__fecha", "pago__hora"),
        "total": Pendiente.objects.filter(abierto=True).count(),
        "medios": MEDIO_CHOICES, "medio_filtro": medio_filtro,
    })


@login_required
@require_POST
def revisar_pendiente(request, pk):
    pendiente = get_object_or_404(Pendiente, pk=pk)
    form = RevisionForm(request.POST)
    if form.is_valid():
        pendiente.revisado = form.cleaned_data["revisado"]
        pendiente.observacion = form.cleaned_data["observacion"]
        pendiente.save(update_fields=["revisado", "observacion"])
        messages.success(request, "Observación guardada.")
    return redirect(_volver_seguro(request, reverse("conciliacion:pendientes")))


@login_required
def parametros(request):
    instancia = ParametrosSistema.cargar()
    form = ParametrosForm(instance=instancia)
    if request.method == "POST":
        if "agregar_equivalencia" in request.POST:
            cod_deb = request.POST.get("cod_deb", "").strip().upper()
            medio = request.POST.get("medio", "")
            if cod_deb and medio in dict(MEDIO_CHOICES):
                EquivalenciaMedio.objects.get_or_create(cod_deb=cod_deb, medio=medio)
                messages.success(request, f"{cod_deb} ahora puede ser {dict(MEDIO_CHOICES)[medio]}.")
            else:
                messages.error(request, "Indica el Cod. Deb. y el medio de pago.")
            return redirect("conciliacion:parametros")
        if "quitar_equivalencia" in request.POST:
            EquivalenciaMedio.objects.filter(pk=request.POST["quitar_equivalencia"]).delete()
            messages.info(request, "Equivalencia quitada.")
            return redirect("conciliacion:parametros")
        form = ParametrosForm(request.POST, instance=instancia)
        if form.is_valid():
            form.save()
            messages.success(request, "Parámetros guardados. Se aplican en la próxima conciliación que proceses.")
            return redirect("conciliacion:parametros")
    return render(request, "conciliacion/parametros.html", {
        "form": form, "equivalencias": EquivalenciaMedio.objects.all(), "medios": MEDIO_CHOICES,
    })
