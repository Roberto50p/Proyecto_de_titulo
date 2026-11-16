from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import servicio
from .forms import ParametrosForm, RevisionForm
from .models import (MEDIO_CHOICES, ArchivoCargado, Conciliacion, EquivalenciaMedio, ParametrosSistema,
                     VentaTransbank)
from .motor import categorias as cat
from .reportes import excel, pdf
from .reportes.datos import armar

VISTAS = ["resumen", cat.DEBITO, cat.CREDITO, cat.PREPAGO]


@login_required
def inicio(request):
    """Página de inicio: "Nueva conciliación" abre un diálogo para elegir dólares o pesos."""
    return render(request, "conciliacion/inicio.html")


@login_required
def clp(request):
    """Carga de una conciliación en pesos: "Cargar" crea (o reutiliza) un borrador con los archivos y lleva a su tabla."""
    if request.method == "POST":
        if not request.FILES.getlist("archivos"):
            messages.error(request, "Selecciona al menos un archivo.")
            return redirect("conciliacion:clp")
        conc = _borrador(request)
        _guardar_subidos(request, conc)
        return redirect("conciliacion:archivos", conc.pk)
    return render(request, "conciliacion/conciliacionclp.html")


@login_required
def lista(request):
    return render(request, "conciliacion/lista.html", {"conciliaciones": Conciliacion.objects.prefetch_related("archivos")})


# ------------------------------------------------------------------ asistente


@login_required
@require_POST
def nueva(request):
    """Crea una conciliación sin fecha; si ya hay un borrador vacío que nunca se procesó, se reutiliza para no
    acumularlos (una conciliación procesada y vaciada conserva su historia y no se reutiliza)."""
    return redirect("conciliacion:archivos", _borrador(request).pk)


def _borrador(request) -> Conciliacion:
    conc = next((c for c in Conciliacion.objects.filter(estado=Conciliacion.BORRADOR, archivos__isnull=True)
                 if not c.parametros and not c.observaciones), None)
    return conc or Conciliacion.objects.create(creada_por=request.user)


def _guardar_subidos(request, conc) -> None:
    """Guarda y lee los archivos subidos en `request.FILES["archivos"]`, avisando con mensajes."""
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


def _aviso_reabierta(request, conc):
    messages.warning(request, f"{conc.etiqueta} volvió a borrador: conciliala de nuevo para ver el resultado con "
                              "los archivos actuales. Tus observaciones se conservan.")


def _con_duplicados(conc, choques: dict | None = None) -> list[ArchivoCargado]:
    """Archivos de la conciliación; cada uno con `ya_conciliado`: los archivos de otras conciliaciones que lo repiten."""
    choques = servicio.conflictos(conc) if choques is None else choques
    archivos = list(conc.archivos.all())
    for a in archivos:
        a.ya_conciliado = choques.get(a.id, [])
    return archivos


def _acciones_archivos(request, conc) -> None:
    """POST de la página de archivos: quitar, reemplazar, quitar todos o subir."""
    procesada = conc.estado == Conciliacion.PROCESADA
    if "eliminar" in request.POST:
        ac = get_object_or_404(ArchivoCargado, pk=request.POST["eliminar"], conciliacion=conc)
        servicio.quitar_archivo(ac)
        if procesada:
            _aviso_reabierta(request, conc)
        messages.info(request, f"Se quitó {ac.nombre}.")
    elif "reemplazar" in request.POST:
        ac = get_object_or_404(ArchivoCargado, pk=request.POST["reemplazar"], conciliacion=conc)
        for otra in servicio.reemplazar(ac):
            messages.warning(request, f"Se quitó {ac.nombre} de {otra.etiqueta}, que volvió a borrador: "
                                      "vuelve a conciliarla. Sus observaciones se conservan.")
    elif "quitar_todos" in request.POST:
        servicio.quitar_todos(conc)
        if procesada:
            _aviso_reabierta(request, conc)
        messages.info(request, "Se quitaron todos los archivos. Sube los nuevos para conciliar de nuevo.")
    else:
        _guardar_subidos(request, conc)


@login_required
def archivos(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    if request.method == "POST":
        _acciones_archivos(request, conc)
        return redirect("conciliacion:archivos", conc.pk)
    return render(request, "conciliacion/conciliacionclp.html", {"conc": conc, "archivos": _con_duplicados(conc)})


@login_required
def revision(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    choques = servicio.conflictos(conc)  # lee los Transbank una sola vez por página
    return render(request, "conciliacion/nueva_revision.html", {
        "conc": conc, "archivos": _con_duplicados(conc, choques), "errores": servicio.validar(conc, choques),
        "avisos": servicio.advertencias(conc),
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
    messages.success(request, f"{conc.etiqueta} procesada.")
    return redirect("conciliacion:detalle", conc.pk)


# ------------------------------------------------------------------ resultado


@login_required
def detalle(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    if conc.estado != Conciliacion.PROCESADA:
        return redirect("conciliacion:revision", conc.pk)
    return render(request, "conciliacion/resultado.html", _contexto_resultado(request, conc))


def _contexto_resultado(request, conc) -> dict:
    datos = armar(conc)
    vista = request.GET.get("vista", "resumen")
    vista = vista if vista in VISTAS else "resumen"
    filtro_cat = request.GET.get("categoria", "")
    filtro_local = request.GET.get("local", "")

    # Sin filtro de categoría se muestran dos tablas: fallas (las que cuenta la pestaña) y avisos aparte.
    registros, fallas, avisos, categorias, locales = [], [], [], [], []
    capitulo = datos["capitulos"].get(vista)
    if capitulo:
        todos = capitulo["fallas"] + capitulo["avisos"] + capitulo["conciliados"]
        categorias = [(k, cat.ETIQUETA[k], sum(1 for v in todos if v.categoria == k))
                      for k in cat.ORDEN_CATEGORIAS if any(v.categoria == k for v in todos)]
        locales = sorted({v.local for v in todos})
        del_local = (lambda vs: [v for v in vs if v.local == filtro_local]) if filtro_local else list
        if filtro_cat:
            registros = del_local([v for v in todos if v.categoria == filtro_cat])
        else:
            fallas, avisos = del_local(capitulo["fallas"]), del_local(capitulo["avisos"])

    pestanas = [{"clave": "resumen", "nombre": "Resumen", "n": None}]
    for m in cat.MEDIOS:
        pestanas.append({"clave": m, "nombre": cat.ETIQUETA_MEDIO[m],
                         "n": datos["capitulos"][m]["resumen"].get("n_falla", 0)})

    return {
        "conc": conc, "d": datos, "vista": vista, "capitulo": capitulo, "registros": registros,
        "fallas": fallas, "avisos": avisos,
        "categorias": categorias, "locales": locales, "filtro_cat": filtro_cat, "filtro_local": filtro_local,
        "pestanas": pestanas,
        "fallas_todas": sorted((v for m in cat.MEDIOS for v in datos["capitulos"][m]["fallas"]),
                               key=lambda v: (cat.GRAVEDAD[v.tipo], cat.MEDIOS.index(v.medio), v.fecha_venta)),
    }


def _nombre_reporte(extension: str) -> str:
    """Los reportes llevan la fecha en que se generan (DD-MM-AAAA; '/' no es válido en nombres de archivo)."""
    return f"conciliacion_{timezone.localdate():%d-%m-%Y}.{extension}"


@login_required
def descargar_pdf(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk, estado=Conciliacion.PROCESADA)
    respuesta = HttpResponse(pdf.generar(conc), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre_reporte("pdf")}"'
    return respuesta


@login_required
def descargar_excel(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk, estado=Conciliacion.PROCESADA)
    respuesta = HttpResponse(excel.generar(conc),
                             content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre_reporte("xlsx")}"'
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
@require_POST
def limpiar_base(request):
    """Borra las conciliaciones y sus datos (solo superusuario, confirmando con la palabra LIMPIAR)."""
    if not request.user.is_superuser:
        messages.error(request, "Solo un administrador puede limpiar la base de datos.")
    elif request.POST.get("confirmacion", "").strip().upper() != "LIMPIAR":
        messages.warning(request, "No se limpió la base: debes escribir LIMPIAR para confirmar.")
    else:
        n = servicio.limpiar_base()
        messages.success(request, f"Base de datos limpia: se borraron {n} conciliaciones con sus archivos, pagos "
                                  "del bordero y pendientes. Los parámetros se conservan.")
    return redirect("conciliacion:inicio")


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
