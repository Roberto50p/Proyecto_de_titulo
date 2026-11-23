import calendar
from datetime import date
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from . import servicio
from .forms import CorreccionForm, FiltroDatosForm, ParametrosForm
from .models import (MEDIO_CHOICES, ArchivoCargado, Conciliacion, EquivalenciaMedio, ParametrosSistema, Pendiente,
                     VentaDolar, VentaTransbank)
from .motor import categorias as cat
from .motor.parametros import cod_deb_de_tarjeta
from .reportes import excel, pdf, respaldo, excel_usd
from .reportes.datos import armar

VISTAS = ["resumen", cat.DEBITO, cat.CREDITO, cat.PREPAGO]


@login_required
def inicio(request):
    """Página de inicio: "Nueva conciliación" abre un diálogo para elegir dólares o pesos."""
    return render(request, "conciliacion/inicio.html")


def _nueva_carga(request, moneda: str, vista: str):
    """"Cargar" crea (o reutiliza) un borrador en esa moneda con los archivos y lleva a su tabla."""
    if request.method == "POST":
        if not request.FILES.getlist("archivos"):
            messages.error(request, "Selecciona al menos un archivo.")
            return redirect(vista)
        conc = _borrador(request, moneda)
        _guardar_subidos(request, conc)
        return redirect("conciliacion:archivos", conc.pk)
    return render(request, "conciliacion/conciliacionclp.html", {"moneda": moneda})


@login_required
def clp(request):
    return _nueva_carga(request, Conciliacion.CLP, "conciliacion:clp")


@login_required
def usd(request):
    """Conciliación en dólares: abono Transbank US$, ERP, carteras de las tarjetas y cartola US$."""
    return _nueva_carga(request, Conciliacion.USD, "conciliacion:usd")


MONEDAS = ["CLP", "USD"]


def _de_moneda(moneda: str):
    """Ids de conciliaciones con archivos en esa moneda (ArchivoCargado.moneda: "Pesos chilenos", "Dólares"; el
    bordero no la informa). Una conciliación con archivos en ambas monedas aparece en las dos."""
    pesos = ArchivoCargado.objects.filter(moneda__istartswith="pesos")
    archivos = pesos if moneda == "CLP" else ArchivoCargado.objects.exclude(moneda="").exclude(moneda__istartswith="pesos")
    return archivos.values("conciliacion_id")


def _filtro_moneda(request) -> str:
    """Siempre hay una moneda elegida (botones tipo radio); CLP por defecto."""
    moneda = request.GET.get("moneda", "")
    return moneda if moneda in MONEDAS else Conciliacion.CLP


@login_required
def lista(request):
    conciliaciones = Conciliacion.objects.prefetch_related("archivos")
    moneda_filtro = _filtro_moneda(request)
    # Un borrador sin archivos no tiene moneda en sus archivos: se muestra según la moneda con que se creó.
    conciliaciones = conciliaciones.filter(Q(pk__in=_de_moneda(moneda_filtro))
                                           | Q(archivos__isnull=True, moneda=moneda_filtro)).distinct()
    return render(request, "conciliacion/lista.html", {
        "conciliaciones": conciliaciones, "monedas": MONEDAS, "moneda_filtro": moneda_filtro,
    })


# ------------------------------------------------------------------ asistente


@login_required
@require_POST
def nueva(request):
    """Crea una conciliación sin fecha; si ya hay un borrador vacío que nunca se procesó, se reutiliza para no
    acumularlos (una conciliación procesada y vaciada conserva su historia y no se reutiliza)."""
    return redirect("conciliacion:archivos", _borrador(request).pk)


def _borrador(request, moneda: str = Conciliacion.CLP) -> Conciliacion:
    conc = next((c for c in Conciliacion.objects.filter(estado=Conciliacion.BORRADOR, archivos__isnull=True,
                                                        moneda=moneda)
                 if not c.parametros and not c.correcciones.exists()), None)
    return conc or Conciliacion.objects.create(creada_por=request.user, moneda=moneda)


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
                              "los archivos actuales. Tus correcciones se conservan.")


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
                                      "vuelve a conciliarla. Sus correcciones se conservan.")
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
    return redirect(_volver_seguro(request, reverse("conciliacion:detalle", args=[conc.pk])))


# ------------------------------------------------------------------ resultado


@login_required
def detalle(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk)
    if conc.estado != Conciliacion.PROCESADA:
        return redirect("conciliacion:revision", conc.pk)
    if conc.moneda == Conciliacion.USD:
        filtro = request.GET.get("tarjeta", "")
        ventas = conc.ventas_usd.all()
        return render(request, "conciliacion/resultado_usd.html", {
            "conc": conc, "tarjetas": [(t, n, conc.resumen["tarjetas"][t]) for t, n in VentaDolar.TARJETAS
                                       if t in conc.resumen["tarjetas"]],
            "filtro": filtro, "fallas": [v for v in ventas if v.es_falla and filtro in ("", v.tarjeta)],
            "conciliadas": [v for v in ventas if not v.es_falla and filtro in ("", v.tarjeta)],
        })
    return render(request, "conciliacion/resultado.html", _contexto_resultado(request, conc))


def _contexto_resultado(request, conc) -> dict:
    datos = armar(conc)
    vista = request.GET.get("vista", "resumen")
    vista = vista if vista in VISTAS else "resumen"
    filtro_cat = request.GET.get("categoria", "")
    filtro_local = request.GET.get("local", "")

    # Sin filtro de categoría, una sola tabla "por revisar": primero las fallas y después los avisos.
    registros, por_revisar, corregidas, categorias, locales = [], [], [], [], []
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
            por_revisar = del_local(capitulo["fallas"] + capitulo["avisos"])
            corregidas = del_local([v for v in capitulo["conciliados"] if v.categoria == cat.CORREGIDO])
        # Recuadro de corrección en cada venta anómala o ya corregida.
        cod_debs = servicio.parametros_actuales().equivalencias
        for v in registros + por_revisar + corregidas:
            if v.categoria in cat.POR_RESOLVER or v.correccion:
                v.form = form_correccion(v, cod_debs=cod_debs)

    pestanas = [{"clave": "resumen", "nombre": "Resumen", "n": None}]
    for m in cat.MEDIOS:
        pestanas.append({"clave": m, "nombre": cat.ETIQUETA_MEDIO[m],
                         "n": len(datos["capitulos"][m]["fallas"]) + len(datos["capitulos"][m]["avisos"])})

    return {
        "conc": conc, "d": datos, "vista": vista, "capitulo": capitulo, "registros": registros,
        "por_revisar": por_revisar, "corregidas": corregidas,
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
    # shortcut: el PDF existe solo en pesos; en dólares se descarga el Excel. Agregar pdf_usd si se necesita.
    conc = get_object_or_404(Conciliacion, pk=pk, estado=Conciliacion.PROCESADA, moneda=Conciliacion.CLP)
    respuesta = HttpResponse(pdf.generar(conc), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre_reporte("pdf")}"'
    return respuesta


@login_required
def descargar_excel(request, pk):
    conc = get_object_or_404(Conciliacion, pk=pk, estado=Conciliacion.PROCESADA)
    generar = excel_usd.generar if conc.moneda == Conciliacion.USD else excel.generar
    respuesta = HttpResponse(generar(conc),
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


def form_correccion(venta, data=None, cod_debs=None) -> CorreccionForm:
    """Formulario del recuadro: con la corrección guardada, o con el dato sugerido para corregir."""
    c = getattr(venta, "correccion", None)
    pago = venta.pago
    if c:
        inicial = {"documento": c.documento, "monto": c.monto, "cod_deb": c.cod_deb,
                   "fecha_bordero": c.fecha_bordero, "aceptada": c.aceptada, "comentario": c.comentario}
    else:  # el documento correcto es el código de Transbank; el resto, lo que tenga el bordero
        inicial = {"documento": venta.codigo_autorizacion, "monto": venta.monto_original,
                   "cod_deb": pago.cod_deb if pago else cod_deb_de_tarjeta(venta.tarjeta),
                   "fecha_bordero": pago.fecha if pago else venta.fecha_venta}
    return CorreccionForm(data, initial=inicial, categoria=c.categoria_original if c else venta.categoria,
                          medio=venta.medio, cod_debs=cod_debs or servicio.parametros_actuales().equivalencias)


@login_required
@require_POST
def corregir_venta(request, pk):
    venta = get_object_or_404(VentaTransbank.objects.select_related("pago", "conciliacion"), pk=pk)
    venta.correccion = venta.conciliacion.correcciones.filter(
        **dict(zip(["medio", "codigo_norm", "cuota_num", "fecha_venta", "monto_original"],
                   servicio.clave_venta(venta)))).first()
    volver = _volver_seguro(request, reverse("conciliacion:detalle", args=[venta.conciliacion_id]))
    fila, recuadro = f"{volver}#v{venta.pk}", f"{volver}#c{venta.pk}"  # al guardar se cierra; si falla, sigue abierto
    if request.POST.get("accion") == "quitar":
        if venta.correccion:
            venta.correccion.delete()
            messages.info(request, f"Se quitó la corrección de {venta.codigo_autorizacion}. "
                                   "Vuelve a conciliar para verlo reflejado.")
        return redirect(fila)
    if not venta.correccion and venta.categoria not in cat.POR_RESOLVER:
        messages.error(request, f"La venta {venta.codigo_autorizacion} no tiene anomalías que corregir.")
        return redirect(volver)
    form = form_correccion(venta, request.POST)
    if form.is_valid():
        servicio.guardar_correccion(venta, {k: form.cleaned_data[k] for k in
                                            ("documento", "monto", "cod_deb", "fecha_bordero", "aceptada",
                                             "comentario")})
        messages.success(request, f"Corrección de {venta.codigo_autorizacion} guardada. Presiona \"Volver a "
                                  "conciliar\" para verificarla.")
        return redirect(fila)
    errores = "; ".join(f"{form.fields[k].label if k in form.fields else ''}: {' '.join(e)}"
                        for k, e in form.errors.items())
    messages.error(request, f"No se guardó la corrección de {venta.codigo_autorizacion}. {errores}")
    return redirect(recuadro)


@login_required
@require_POST
def limpiar_base(request):
    """Borra las conciliaciones y sus datos (solo superusuario, con un respaldo vigente de toda la base y confirmando
    con la palabra LIMPIAR)."""
    if not request.user.is_superuser:
        messages.error(request, "Solo un administrador puede limpiar la base de datos.")
        return redirect("conciliacion:datos")
    _, todas = _seleccion({})
    if todas and _exportacion_vigente(request, todas) is None:
        messages.error(request, "No se limpió la base: primero exporta toda la base (sin filtro de fechas) con "
                                "\"Exportar y limpiar\". Si exportaste antes de los últimos cambios, exporta de nuevo.")
    elif request.POST.get("confirmacion", "").strip().upper() != "LIMPIAR":
        messages.warning(request, "No se limpió la base: debes escribir LIMPIAR para confirmar.")
        return redirect(reverse("conciliacion:datos") + "?limpiar=1")  # vuelve a abrir el diálogo
    else:
        n = servicio.limpiar_base()
        request.session.pop(EXPORTADO, None)
        messages.success(request, f"Base de datos limpia: se borraron {n} conciliaciones con sus archivos, pagos "
                                  "del bordero y correcciones. Los parámetros se conservan.")
    return redirect("conciliacion:datos")


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


# ------------------------------------------------------------------ gestión de datos

# Sesión: qué conciliaciones se exportaron por última vez y la huella de su contenido. Solo esas se pueden eliminar,
# y solo si no cambiaron desde entonces.
EXPORTADO = "datos_exportados"
PLAZOS_TOPE = [(3, "Más de 3 meses"), (6, "Más de 6 meses"), (12, "Más de 1 año")]


def _meses_atras(fecha: date, meses: int) -> date:
    anio, mes = divmod(fecha.year * 12 + fecha.month - 1 - meses, 12)
    return date(anio, mes + 1, min(fecha.day, calendar.monthrange(anio, mes + 1)[1]))


def _solo_administrador(request) -> bool:
    if request.user.is_superuser:
        return True
    messages.error(request, "Solo un administrador puede exportar y limpiar datos.")
    return False


def _seleccion(datos) -> tuple[FiltroDatosForm, list[Conciliacion]]:
    """Filtro de fechas y las conciliaciones que abarca (ninguna si el filtro es inválido)."""
    form = FiltroDatosForm(datos)
    if not form.is_valid():
        return form, []
    conciliaciones = (servicio.seleccionar(form.cleaned_data["desde"], form.cleaned_data["hasta"])
                      .select_related("creada_por").prefetch_related("archivos"))
    return form, list(conciliaciones)


def _exportacion_vigente(request, conciliaciones) -> dict | None:
    """La última exportación de la sesión, si abarca exactamente estas conciliaciones y sus datos no cambiaron desde
    entonces. Si se procesaron, se agregaron archivos o correcciones, etc., el Excel descargado ya no contiene lo que
    se borraría: hay que exportar de nuevo."""
    exportado = request.session.get(EXPORTADO)
    if not conciliaciones or not exportado or exportado["ids"] != [c.pk for c in conciliaciones]:
        return None
    return exportado if exportado.get("huella") == respaldo.huella(respaldo.tablas(conciliaciones)) else None


def _volver_a_datos(datos, **extra) -> str:
    filtros = {k: datos.get(k) for k in ("desde", "hasta") if datos.get(k)}
    consulta = urlencode({**filtros, **extra})
    return reverse("conciliacion:datos") + (f"?{consulta}" if consulta else "")


def _conciliaciones(n: int) -> str:
    return f"{n} conciliación" if n == 1 else f"{n} conciliaciones"


@login_required
def datos(request):
    """Gestión de datos: filtra conciliaciones por fecha, las exporta a Excel y luego las elimina."""
    if not _solo_administrador(request):
        return redirect("conciliacion:inicio")
    form, conciliaciones = _seleccion(request.GET)
    ids = [c.pk for c in conciliaciones]
    exportado = _exportacion_vigente(request, conciliaciones)
    _, todas = _seleccion({})
    # "Limpiar toda la base" exige un respaldo vigente de todas las conciliaciones (sin filtro).
    if ids == [c.pk for c in todas]:
        respaldada = not todas or exportado is not None
    else:
        respaldada = _exportacion_vigente(request, todas) is not None
    hoy = timezone.localdate()
    return render(request, "conciliacion/datos.html", {
        "form": form,
        "conciliaciones": conciliaciones,
        "totales": {
            "archivos": ArchivoCargado.objects.filter(conciliacion_id__in=ids).count(),
            "ventas": VentaTransbank.objects.filter(conciliacion_id__in=ids).count(),
            "ventas_usd": VentaDolar.objects.filter(conciliacion_id__in=ids).count(),
            "pendientes": Pendiente.objects.filter(origen_id__in=ids).count(),
        },
        "plazos": [(etiqueta, _meses_atras(hoy, meses).isoformat()) for meses, etiqueta in PLAZOS_TOPE],
        "exportado": exportado,
        "abrir_eliminar": exportado is not None and request.GET.get("paso") == "eliminar",
        "base": {"conciliaciones": len(todas), "archivos": ArchivoCargado.objects.count(),
                 "ventas": VentaTransbank.objects.count(), "ventas_usd": VentaDolar.objects.count(),
                 "respaldada": respaldada},
        "abrir_limpiar": request.GET.get("limpiar") == "1",
    })


@login_required
@require_POST
def exportar_datos(request):
    """Descarga en Excel las conciliaciones del filtro y deja anotado en la sesión qué se exportó y la huella de su
    contenido, para permitir eliminarlo después solo si no cambió."""
    if not _solo_administrador(request):
        return redirect("conciliacion:inicio")
    form, conciliaciones = _seleccion(request.POST)
    if not conciliaciones:
        messages.warning(request, "No hay datos que exportar con ese filtro." if form.is_valid()
                         else "Revisa las fechas del filtro.")
        return redirect(_volver_a_datos(request.POST))
    lista = respaldo.tablas(conciliaciones)
    contenido = respaldo.excel(lista)
    request.session[EXPORTADO] = {"ids": [c.pk for c in conciliaciones], "huella": respaldo.huella(lista),
                                  "en": f"{timezone.localtime():%d/%m/%Y %H:%M}"}
    respuesta = HttpResponse(contenido,
                             content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{respaldo.nombre_archivo()}"'
    return respuesta


@login_required
@require_POST
def eliminar_datos(request):
    """Elimina las conciliaciones del filtro, solo si son exactamente las que se exportaron, no cambiaron desde la
    exportación y se confirma con la palabra ELIMINAR."""
    if not _solo_administrador(request):
        return redirect("conciliacion:inicio")
    _, conciliaciones = _seleccion(request.POST)
    ids = [c.pk for c in conciliaciones]
    exportado = _exportacion_vigente(request, conciliaciones)
    if not ids:
        messages.warning(request, "No hay datos que eliminar con ese filtro.")
    elif exportado is None:
        messages.error(request, "Primero exporta estos datos: solo se eliminan los datos recién exportados (si "
                                "cambiaste el filtro o hubo cambios en las conciliaciones, exporta de nuevo).")
    elif request.POST.get("confirmacion", "").strip().upper() != "ELIMINAR":
        messages.warning(request, "No se eliminó nada: escribe ELIMINAR para confirmar.")
        return redirect(_volver_a_datos(request.POST, paso="eliminar"))
    else:
        b = servicio.eliminar_conciliaciones(ids)
        del request.session[EXPORTADO]
        messages.success(request, f"Se eliminó de la base: {_conciliaciones(b['conciliaciones'])} con "
                                  f"{b['archivos']} archivos, {b['ventas']} ventas en pesos, {b['ventas_usd']} "
                                  f"ventas en dólares, {b['pendientes']} pendientes y {b['pagos']} pagos del "
                                  f"bordero. El respaldo queda en el Excel exportado el {exportado['en']}.")
    return redirect(_volver_a_datos(request.POST))
