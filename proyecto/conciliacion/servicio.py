"""Servicio que lee los archivos de una conciliación, ejecuta el motor y guarda el resultado."""

import hashlib
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from functools import lru_cache
from decimal import Decimal

import pandas as pd
from django.db import transaction
from django.db.models import Max, Min, Q
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from .lectores.bordero import leer_bordero
from .lectores.cartola import leer_cartola
from .lectores.comunes import ArchivoNoReconocido, a_decimal, clave, normalizar_codigo
from .lectores.deteccion import detectar
from .lectores.dolar import leer_abono_dolar, leer_cartera, leer_erp
from .lectores.transbank import leer_transbank
from .models import (
    ArchivoCargado,
    Conciliacion,
    CoberturaBordero,
    CorreccionManual,
    EquivalenciaMedio,
    MovimientoCartola,
    PagoBordero,
    ParametrosSistema,
    Pendiente,
    ResultadoAbono,
    VentaDolar,
    VentaTransbank,
)
from .motor import categorias as cat
from .motor import dolar as usd
from .motor.abonos import conciliar_abonos, cuadratura_archivo, cuadratura_por_medio
from .motor.cruce import conciliar_ventas, pagos_tarjeta
from .motor.mensajes import fecha as fmt_fecha
from .motor.mensajes import mensaje, pesos
from .motor.parametros import Parametros, leer_reglas_medio


TIPOS_DOLAR = (ArchivoCargado.ABONO_USD, ArchivoCargado.ERP, ArchivoCargado.EMISOR)


def parametros_actuales() -> Parametros:
    p = ParametrosSistema.cargar()
    equivalencias = defaultdict(set)
    for e in EquivalenciaMedio.objects.all():
        equivalencias[e.cod_deb].add(e.medio)
    return Parametros(
        tolerancia_clp=p.tolerancia_clp,
        umbral_similitud=p.umbral_similitud,
        dias_holgura=p.dias_holgura,
        ventana_dias=p.ventana_dias,
        patrones_cartola=tuple(x.strip() for x in p.patrones_cartola.split(",") if x.strip()),
        equivalencias={k: frozenset(v) for k, v in equivalencias.items()},
        reglas_medio_cartola=leer_reglas_medio(p.reglas_medio_cartola),
        omitir_moneda_extranjera=p.omitir_moneda_extranjera,
    )


def sha256_de(archivo) -> str:
    h = hashlib.sha256()
    for trozo in archivo.chunks():
        h.update(trozo)
    archivo.seek(0)
    return h.hexdigest()


@contextmanager
def ruta_local(ac: ArchivoCargado):
    try:
        ruta = ac.archivo.path
    except NotImplementedError:  # el almacenamiento no tiene rutas locales
        ruta = None
    if ruta:
        yield ruta
        return
    sufijo = os.path.splitext(ac.archivo.name)[1]
    with tempfile.NamedTemporaryFile(suffix=sufijo, delete=False) as tmp, ac.archivo.open("rb") as origen:
        shutil.copyfileobj(origen, tmp)
    try:
        yield tmp.name
    finally:
        os.remove(tmp.name)


# ---------------------------------------------------------------- lectura y validación


def _error_transbank(a) -> str:
    """Problemas del contenido de un archivo Transbank en pesos ('' si está bien)."""
    if a.fecha_abono != a.fecha_abono_hasta:
        return "El archivo abarca varios días de abono; descarga un reporte por día desde Transbank."
    if dif := cuadratura_archivo(a.resumen):
        return (f"El resumen del archivo no cuadra: Total abono {pesos(a.resumen['total_abono'])} "
                f"no coincide con ventas menos comisiones (diferencia {pesos(dif)}).")
    if dif := cuadratura_por_medio(a.resumen, a.resumen_por_medio):
        return (f"El archivo trae todos los medios de pago, pero el detalle por medio no suma el Total abono "
                f"(diferencia {pesos(dif)}). Descarga desde Transbank un archivo por medio de pago.")
    return ""


def leer_archivo(ac: ArchivoCargado) -> None:
    """Detecta el tipo del archivo y guarda sus metadatos (o el error de lectura).

    La moneda no se valida aquí: depende del parámetro "Omitir archivos en moneda extranjera" (ver validar).
    """
    ac.error, ac.medio, ac.por_medio, ac.banco = "", "", {}, ""
    try:
        with ruta_local(ac) as ruta:
            ac.tipo = detectar(ruta)
            if ac.tipo == ArchivoCargado.TRANSBANK:
                a = leer_transbank(ruta)
                ac.medio, ac.por_medio, ac.moneda, ac.cuenta = a.medio or "", a.resumen_por_medio, a.moneda, a.cuenta
                ac.fecha_abono, ac.desde = a.fecha_abono, a.ventas.fecha_venta.min()
                ac.hasta = a.ventas.fecha_venta.max()
                ac.filas, ac.total_abono, ac.resumen = len(a.ventas), a.resumen["total_abono"], a.resumen
                if not ac.moneda_extranjera:
                    ac.error = _error_transbank(a)
            elif ac.tipo == ArchivoCargado.BORDERO:
                b = leer_bordero(ruta)
                ac.desde, ac.hasta, ac.filas = b.desde, b.hasta, len(b.movimientos)
            elif ac.tipo == ArchivoCargado.ABONO_USD:
                a = leer_abono_dolar(ruta)
                ac.moneda, ac.cuenta, ac.fecha_abono, ac.filas = a.moneda, a.cuenta, a.fecha_abono, len(a.ventas)
                if not a.ventas.empty:
                    ac.desde, ac.hasta = a.ventas.fecha_venta.min(), a.ventas.fecha_venta.max()
                # Montos en float solo para mostrar; al conciliar se relee el archivo con centavos exactos.
                ac.resumen = {k: float(v) for k, v in a.resumen.items()} | {
                    "tarjetas": sorted(set(a.ventas.tarjeta)) if not a.ventas.empty else []}
            elif ac.tipo == ArchivoCargado.EMISOR:
                c = leer_cartera(ruta)
                ac.banco, ac.filas, ac.resumen = f"{usd.TARJETAS[c.marca]} US$", len(c.documentos), {"marca": c.marca}
            elif ac.tipo == ArchivoCargado.ERP:
                e = leer_erp(ruta)
                fechas = e.fecha.dropna()
                ac.filas = len(e)
                if not fechas.empty:
                    ac.desde, ac.hasta = fechas.min(), fechas.max()
            else:
                c = leer_cartola(ruta)
                ac.banco, ac.cuenta, ac.moneda = c.banco, c.cuenta, c.moneda
                ac.desde, ac.hasta, ac.filas = c.desde, c.hasta, len(c.movimientos)
    except ArchivoNoReconocido as exc:
        ac.tipo, ac.error = ArchivoCargado.DESCONOCIDO, str(exc)
    except Exception as exc:  # archivo con el formato esperado pero dañado
        ac.tipo, ac.error = ArchivoCargado.DESCONOCIDO, f"No se pudo leer el archivo: {exc}"
    ac.save()


def utilizables(conc: Conciliacion) -> list[ArchivoCargado]:
    """Archivos que entran a la conciliación: sin error de lectura y en pesos."""
    return [a for a in conc.archivos.all() if not a.error and not a.moneda_extranjera]


def validar(conc: Conciliacion, choques: dict | None = None) -> list[str]:
    """Errores que impiden conciliar. `choques` son los conflictos(conc) ya calculados, para no releer los archivos."""
    if conc.moneda == Conciliacion.USD:
        return _validar_dolar(conc)
    errores = [f"{a.nombre}: es un archivo de la conciliación en dólares; quítalo." for a in conc.archivos.all()
               if a.tipo in TIPOS_DOLAR]
    archivos = list(conc.archivos.all())
    for a in archivos:
        if a.error:
            errores.append(f"{a.nombre}: {a.error}")
    if not ParametrosSistema.cargar().omitir_moneda_extranjera:
        for a in archivos:
            if not a.error and a.moneda_extranjera:
                errores.append(f"{a.nombre}: moneda no soportada ({a.moneda or 'no informada'}). Esta versión concilia "
                               "en pesos: quita el archivo o activa 'Omitir archivos en moneda extranjera' en Parámetros.")
    validos = utilizables(conc)
    tipos = {a.tipo for a in validos}
    for tipo, nombre in [(ArchivoCargado.BORDERO, "el bordero"), (ArchivoCargado.CARTOLA, "la cartola"),
                         (ArchivoCargado.TRANSBANK, "al menos un archivo Transbank")]:
        if tipo not in tipos:
            errores.append(f"Falta {nombre}.")
    transbank = [a for a in validos if a.tipo == ArchivoCargado.TRANSBANK and a.fecha_abono]
    for ac_id, otros in (conflictos(conc) if choques is None else choques).items():
        nombre = next(a.nombre for a in validos if a.id == ac_id)
        for otro in otros:
            errores.append(f"{nombre}: ya se concilió en {otro.conciliacion.etiqueta} ({otro.nombre}).")
    # Un archivo con todos los medios cuenta para cada medio que trae.
    repetidos = Counter((medio, a.fecha_abono) for a in transbank for medio in a.por_medio)
    for (medio, dia), n in repetidos.items():
        if n > 1:
            errores.append(f"Hay {n} archivos Transbank de {cat.ETIQUETA_MEDIO[medio]} con abono del {fmt_fecha(dia)}; "
                           "quita el repetido (un archivo con todos los medios incluye cada medio).")
    return errores


@lru_cache(maxsize=16)
def _ventas_tbk(ruta: str, _version: tuple):
    """Ventas de un archivo Transbank, leídas una sola vez por página. `_version` (fecha de modificación y tamaño)
    evita usar una lectura vieja si se reemplaza un archivo con el mismo nombre."""
    return leer_transbank(ruta).ventas


def ventas_de(ac: ArchivoCargado):
    st = os.stat(ac.archivo.path)
    return _ventas_tbk(ac.archivo.path, (st.st_mtime_ns, st.st_size))


def _ventas_sin_bordero(a: ArchivoCargado, borderos: list[tuple]) -> list[str]:
    """Avisos por cada día de venta del archivo Transbank que ningún bordero cubre (el crédito se abona días después
    de la venta, así que su archivo suele traer ventas anteriores al bordero). Las cuotas 2 y 3 se excluyen: su venta
    es de meses anteriores y se siguen como cuota."""
    ventas = ventas_de(a)
    por_dia = Counter()
    for f in ventas.to_dict("records"):
        cuota = f["cuota_num"]
        if f["tipo_movimiento"].lower() != "venta" or (not pd.isna(cuota) and int(cuota) > 1):
            continue
        dia = pd.Timestamp(f["fecha_venta"]).date()
        if not any(d <= dia <= h for d, h in borderos):
            por_dia[dia] += 1
    return [f"{a.nombre}: {n} venta{'s' if n > 1 else ''} del {fmt_fecha(dia)} sin bordero que cubra esa fecha; "
            "las que no se registraron en el bordero los días siguientes quedarán como 'Fuera del período del "
            "bordero'. Carga también el bordero de ese día para compararlas."
            for dia, n in sorted(por_dia.items())]


def advertencias(conc: Conciliacion) -> list[str]:
    """Situaciones que no impiden conciliar pero conviene saber."""
    if conc.moneda == Conciliacion.USD:
        return _advertencias_dolar(conc)
    avisos = []
    if ParametrosSistema.cargar().omitir_moneda_extranjera:
        avisos += [f"{a.nombre}: está en {a.moneda or 'moneda no informada'}; se omite (esta versión concilia en "
                   "pesos)." for a in conc.archivos.all() if not a.error and a.moneda_extranjera]
    archivos = utilizables(conc)
    borderos = [(a.desde, a.hasta) for a in archivos if a.tipo == ArchivoCargado.BORDERO]
    borderos += [(c.desde, c.hasta) for c in CoberturaBordero.objects.all()]
    for a in archivos:
        if a.tipo == ArchivoCargado.TRANSBANK and borderos:
            avisos += _ventas_sin_bordero(a, borderos)
    cartolas = [(a.desde, a.hasta) for a in archivos if a.tipo == ArchivoCargado.CARTOLA]
    for a in archivos:
        if a.tipo == ArchivoCargado.TRANSBANK and a.fecha_abono and cartolas:
            if not any(d <= a.fecha_abono <= h for d, h in cartolas):
                avisos.append(f"{a.nombre}: la cartola no cubre el abono del {fmt_fecha(a.fecha_abono)}.")
    return avisos


# ---------------------------------------------------------------- archivos ya conciliados


def _clave_venta_unica(medio, codigo_norm, cuota_num, fecha_venta, monto_original) -> tuple:
    """Identifica una venta entre conciliaciones: código de autorización + medio + N° de cuota (las cuotas comparten
    código) + fecha y monto de la venta (los códigos de autorización se repiten con el tiempo)."""
    cuota = 0 if cuota_num is None or pd.isna(cuota_num) else int(cuota_num)
    return medio, codigo_norm, cuota, pd.Timestamp(fecha_venta).date(), int(monto_original)


def _claves_ventas(ac: ArchivoCargado) -> set[tuple]:
    ventas = ventas_de(ac)
    return {_clave_venta_unica(f["medio"], f["codigo_norm"], f["cuota_num"], f["fecha_venta"], f["monto_original"])
            for f in ventas.to_dict("records") if f["tipo_movimiento"].lower() == "venta" and f["codigo_norm"]}


def conflictos(conc: Conciliacion) -> dict[int, list[ArchivoCargado]]:
    """Archivos Transbank de esta conciliación que ya se conciliaron en otra: id del archivo -> archivos de las otras
    conciliaciones ya procesadas que lo repiten (mismo archivo, mismo medio y día de abono, o la misma venta). Los
    borradores no cuentan (gana la que se procese primero), ni el bordero ni la cartola: se pueden repetir sin
    duplicar nada."""
    propios = [a for a in utilizables(conc) if a.tipo == ArchivoCargado.TRANSBANK]
    if not propios:
        return {}
    otros = [a for a in ArchivoCargado.objects.filter(tipo=ArchivoCargado.TRANSBANK,
                                                       conciliacion__estado=Conciliacion.PROCESADA)
             .exclude(conciliacion=conc).select_related("conciliacion") if not a.error and not a.moneda_extranjera]
    claves = {a.id: _claves_ventas(a) for a in propios}
    codigos = {k[1] for ks in claves.values() for k in ks}
    ya_conciliadas = defaultdict(set)
    for v in (VentaTransbank.objects.exclude(conciliacion=conc)
              .filter(es_venta=True, codigo_norm__in=codigos, conciliacion__estado=Conciliacion.PROCESADA)
              .select_related("archivo__conciliacion")):
        clave_v = _clave_venta_unica(v.medio, v.codigo_norm, v.cuota_num, v.fecha_venta, v.monto_original)
        ya_conciliadas[clave_v].add(v.archivo)

    resultado = {}
    for a in propios:
        choques = {o for o in otros if o.sha256 == a.sha256
                   or (o.fecha_abono == a.fecha_abono and set(o.por_medio) & set(a.por_medio))}
        for k in claves[a.id]:
            choques |= {o for o in ya_conciliadas.get(k, ()) if not o.error and not o.moneda_extranjera}
        if choques:
            resultado[a.id] = sorted(choques, key=lambda o: (o.conciliacion_id, o.nombre))
    return resultado


@transaction.atomic
def reemplazar(ac: ArchivoCargado) -> list[Conciliacion]:
    """Quita de las otras conciliaciones los archivos que repiten a `ac` (vuelven a borrador conservando sus
    observaciones) y devuelve las conciliaciones afectadas."""
    afectadas = []
    for otro in conflictos(ac.conciliacion).get(ac.id, []):
        otro = ArchivoCargado.objects.select_related("conciliacion").get(pk=otro.pk)  # estado al día
        quitar_archivo(otro)
        if otro.conciliacion not in afectadas:
            afectadas.append(otro.conciliacion)
    return afectadas


# ---------------------------------------------------------------- procesamiento


def _deshacer(conc: Conciliacion) -> None:
    """Revierte el resultado anterior de la conciliación. Las correcciones manuales no se tocan: se vuelven a
    aplicar al conciliar de nuevo.

    Los pendientes que ya cerró una conciliación posterior se mantienen: su historia pertenece a esa conciliación.
    """
    Pendiente.objects.filter(cierre=conc).update(abierto=True, cierre=None)
    conc.pendientes.filter(cierre__isnull=True).delete()
    PagoBordero.objects.filter(conciliacion=conc).update(conciliacion=None)
    conc.ventas.all().delete()
    conc.ventas_usd.all().delete()
    conc.abonos.all().delete()
    conc.movimientos_cartola.all().delete()


def reabrir(conc: Conciliacion) -> None:
    """Deja una conciliación procesada otra vez en borrador (al agregar o quitar archivos)."""
    with transaction.atomic():
        _deshacer(conc)
        conc.estado, conc.resumen, conc.procesada_en = Conciliacion.BORRADOR, {}, None
        conc.save()


@transaction.atomic
def quitar_archivo(ac: ArchivoCargado) -> None:
    """Quita un archivo de la conciliación; si estaba procesada vuelve a borrador.

    Un bordero se lleva su cobertura y los pagos que solo venían en él, salvo que otra conciliación los haya usado
    o dejado como pendientes: esa historia pertenece a esa conciliación.
    """
    conc = ac.conciliacion
    if conc.estado == Conciliacion.PROCESADA:
        reabrir(conc)
    if ac.tipo == ArchivoCargado.BORDERO:
        CoberturaBordero.objects.filter(archivo=ac).delete()
        ids = list(ac.pagos.values_list("id", flat=True))
        ac.pagos.clear()
        PagoBordero.objects.filter(id__in=ids, archivos__isnull=True, conciliacion__isnull=True,
                                   pendiente__isnull=True).delete()
    ac.archivo.delete(save=False)
    ac.delete()


def quitar_todos(conc: Conciliacion) -> None:
    """Deja la conciliación sin archivos para volver a conciliarla con otros."""
    with transaction.atomic():
        for ac in list(conc.archivos.all()):
            quitar_archivo(ac)


def limpiar_base() -> int:
    """Borra todas las conciliaciones y lo que cuelga de ellas (archivos, ventas, abonos, cartola, pendientes, pagos y
    cobertura del bordero). Conserva parámetros, equivalencias y usuarios. Devuelve cuántas conciliaciones borró."""
    archivos = [ac.archivo for ac in ArchivoCargado.objects.all()]
    with transaction.atomic():
        n = Conciliacion.objects.count()
        Pendiente.objects.all().delete()
        Conciliacion.objects.all().delete()  # en cascada: archivos, ventas, abonos y movimientos de cartola
        PagoBordero.objects.all().delete()
        CoberturaBordero.objects.all().delete()
    for f in archivos:  # los archivos físicos se borran solo si la base quedó limpia
        f.delete(save=False)
    return n


def seleccionar(desde=None, hasta=None):
    """Conciliaciones cuyo período cae completo entre `desde` y `hasta` (ambos opcionales e inclusivos), anotadas con
    `p_desde` y `p_hasta`. El período son los días de abono de sus archivos Transbank (en pesos o US$), como en su
    nombre; si no tiene abonos cargados se usa el día en que se creó."""
    validos = Q(archivos__tipo__in=ArchivoCargado.ABONOS, archivos__error="", archivos__fecha_abono__isnull=False)
    creada = TruncDate("creada_en")
    conciliaciones = Conciliacion.objects.annotate(
        p_desde=Coalesce(Min("archivos__fecha_abono", filter=validos), creada),
        p_hasta=Coalesce(Max("archivos__fecha_abono", filter=validos), creada),
    )
    if desde:
        conciliaciones = conciliaciones.filter(p_desde__gte=desde)
    if hasta:
        conciliaciones = conciliaciones.filter(p_hasta__lte=hasta)
    return conciliaciones.order_by("p_desde", "pk")


def eliminar_conciliaciones(ids) -> dict:
    """Borra las conciliaciones indicadas y lo que depende solo de ellas: archivos (también el archivo guardado),
    ventas (en pesos y en dólares), abonos, movimientos de cartola, los pendientes que originaron, la cobertura de sus
    borderos y los pagos del bordero que ninguna otra conciliación usa o tiene pendientes. Los pendientes de otras
    conciliaciones que una borrada cerró siguen cerrados. Devuelve cuánto se borró de cada cosa."""
    conciliaciones = Conciliacion.objects.filter(pk__in=list(ids))
    archivos = list(ArchivoCargado.objects.filter(conciliacion__in=conciliaciones))
    borrado = {
        "conciliaciones": conciliaciones.count(),
        "archivos": len(archivos),
        "ventas": VentaTransbank.objects.filter(conciliacion__in=conciliaciones).count(),
        "ventas_usd": VentaDolar.objects.filter(conciliacion__in=conciliaciones).count(),
        "pendientes": Pendiente.objects.filter(origen__in=conciliaciones).count(),
    }
    with transaction.atomic():
        pagos = set(PagoBordero.objects.filter(Q(archivos__in=archivos) | Q(conciliacion__in=conciliaciones))
                    .values_list("id", flat=True))
        CoberturaBordero.objects.filter(archivo__in=archivos).delete()
        conciliaciones.delete()  # en cascada: archivos, ventas, abonos, movimientos de cartola y sus pendientes
        _, por_modelo = PagoBordero.objects.filter(id__in=pagos, archivos__isnull=True, conciliacion__isnull=True,
                                                   pendiente__isnull=True).delete()
    borrado["pagos"] = por_modelo.get(PagoBordero._meta.label, 0)
    for ac in archivos:  # los archivos guardados se borran solo si la base ya quedó sin ellos
        ac.archivo.delete(save=False)
    return borrado



def _registrar_bordero(ac: ArchivoCargado, params: Parametros) -> list[int]:
    """Guarda los pagos con tarjeta del bordero sin duplicarlos.

    Un pago se identifica por fecha, hora, cuenta y Cod. Deb.; si el hotel corrigió el documento o el valor en
    FrontOffice y vuelve a exportar, se actualiza el mismo pago en vez de crear otro.
    """
    with ruta_local(ac) as ruta:
        b = leer_bordero(ruta)
    CoberturaBordero.objects.get_or_create(desde=b.desde, hasta=b.hasta, archivo=ac)
    ids = []
    for fila in pagos_tarjeta(b.movimientos, params).to_dict("records"):
        corregibles = {"documento": fila["documento"], "documento_norm": fila["documento_norm"],
                       "valor": fila["valor"], "invalido": bool(fila["invalido"])}
        pago, creado = PagoBordero.objects.get_or_create(
            fecha=fila["fecha"], hora=fila["hora"], cuenta=fila["cuenta"], cod_deb=fila["cod_deb"],
            defaults={k: fila[k] for k in ["hab", "reserva", "descripcion", "factura", "usuario", "designacion"]}
            | corregibles,
        )
        if not creado and any(getattr(pago, k) != v for k, v in corregibles.items()):
            for k, v in corregibles.items():
                setattr(pago, k, v)
            pago.save(update_fields=list(corregibles))
        ids.append(pago.id)
    ac.pagos.add(*ids)
    return ids


def _medio_de_pago(cod_deb: str, params: Parametros) -> str:
    medios = params.medios_de(cod_deb)
    return next((m for m in cat.MEDIOS if m in medios), cat.DEBITO)


@transaction.atomic
def procesar(conc: Conciliacion) -> Conciliacion:
    _deshacer(conc)
    if conc.moneda == Conciliacion.USD:
        return _procesar_dolar(conc)
    params = parametros_actuales()
    archivos = utilizables(conc)

    # Bordero: registrar pagos (sin duplicar) y su cobertura.
    pagos_del_mes = set()
    for ac in archivos:
        if ac.tipo == ArchivoCargado.BORDERO:
            pagos_del_mes.update(_registrar_bordero(ac, params))
    cobertura = [(c.desde, c.hasta) for c in CoberturaBordero.objects.all()]

    libres = PagoBordero.objects.filter(conciliacion__isnull=True, invalido=False).select_related("pendiente__origen")
    pagos = pd.DataFrame([{
        "id": p.id, "documento": p.documento, "documento_norm": p.documento_norm, "valor": p.valor,
        "fecha": p.fecha, "cod_deb": p.cod_deb,
        "pendiente_mes": p.pendiente.origen.etiqueta if hasattr(p, "pendiente") and p.pendiente.abierto else None,
    } for p in libres])
    pagos_por_id = {p.id: p for p in libres}

    # Transbank: ventas de todos los archivos de la conciliación.
    ventas_obj = []
    for ac in archivos:
        if ac.tipo != ArchivoCargado.TRANSBANK:
            continue
        with ruta_local(ac) as ruta:
            a = leer_transbank(ruta)
        for fila in a.ventas.to_dict("records"):
            ventas_obj.append(VentaTransbank(
                conciliacion=conc, archivo=ac, fila=fila["fila"], medio=fila["medio"],
                es_venta=fila["tipo_movimiento"].lower() == "venta",
                fecha_venta=fila["fecha_venta"], tipo_movimiento=fila["tipo_movimiento"],
                codigo_comercio=fila["codigo_comercio"], local=fila["local"],
                monto_original=fila["monto_original"], monto_vuelto=fila["monto_vuelto"],
                monto_abono_valido=fila["monto_abono_valido"], comision=fila["comision"],
                iva_comision=fila["iva_comision"], total_abono=fila["total_abono"], tipo_venta=fila["tipo_venta"],
                cuota_num=None if pd.isna(fila["cuota_num"]) else int(fila["cuota_num"]),
                cuota_total=None if pd.isna(fila["cuota_total"]) else int(fila["cuota_total"]),
                tarjeta=fila["tarjeta"], codigo_autorizacion=fila["codigo_autorizacion"],
                codigo_norm=fila["codigo_norm"], boleta=fila["boleta"],
            ))
    ventas_df = pd.DataFrame([{
        "id": i, "codigo_autorizacion": v.codigo_autorizacion, "codigo_norm": v.codigo_norm,
        "monto_original": v.monto_original, "fecha_venta": v.fecha_venta, "medio": v.medio, "local": v.local,
        "cuota_num": v.cuota_num, "cuota_total": v.cuota_total,
    } for i, v in enumerate(ventas_obj) if v.es_venta])

    correcciones = {c.clave: c for c in conc.correcciones.all()}
    corregidos = pagos_corregidos(ventas_obj, correcciones)
    if not corregidos.empty:
        pagos = pd.concat([pagos, corregidos], ignore_index=True) if not pagos.empty else corregidos

    if not ventas_df.empty:
        resultado = conciliar_ventas(ventas_df, pagos, cobertura, params)
        for r in resultado.to_dict("records"):
            v = ventas_obj[r["venta_id"]]
            v.categoria, v.mensaje, v.nota = r["categoria"], r["mensaje"], r["nota"]
            v.codigo_sugerido = "" if pd.isna(r["codigo_sugerido"]) else r["codigo_sugerido"]
            if not pd.isna(r["pago_id"]):
                v.monto_bordero, v.diferencia = int(r["monto_bordero"]), int(r["diferencia"])
                if r["pago_id"] > 0:
                    v.pago = pagos_por_id[int(r["pago_id"])]
                elif v.categoria == cat.OK:  # calzó con el dato que editó el analista
                    c = correcciones[clave_venta(v)]
                    v.categoria = cat.CORREGIDO
                    v.mensaje = mensaje(cat.CORREGIDO, detalle=(
                        f"Corrección manual verificada: documento {c.documento}, {pesos(c.monto)}, {c.cod_deb}."
                        + (f" Comentario: {c.comentario}" if c.comentario else "")))
                else:  # la corrección no calza: sigue siendo anomalía, con lo que dice el motor
                    v.nota = "; ".join(filter(None, [v.nota, "la corrección guardada no calza"]))
    _cuotas_anteriores(conc, ventas_obj)
    _aplicar_aceptadas(ventas_obj, correcciones)
    VentaTransbank.objects.bulk_create(ventas_obj)

    # Pagos usados quedan conciliados en esta conciliación; si eran pendientes, se cierran.
    usados = [v.pago_id for v in ventas_obj if v.pago_id]
    PagoBordero.objects.filter(id__in=usados).update(conciliacion=conc)
    Pendiente.objects.filter(pago_id__in=usados, abierto=True).update(abierto=False, cierre=conc)

    # Abonos contra cartola.
    cartolas = []
    for ac in archivos:
        if ac.tipo == ArchivoCargado.CARTOLA:
            with ruta_local(ac) as ruta:
                cartolas.append(leer_cartola(ruta))
    if cartolas:
        movimientos = pd.concat([c.movimientos for c in cartolas], ignore_index=True)
        rango = (min(c.desde for c in cartolas), max(c.hasta for c in cartolas))
    else:
        movimientos = pd.DataFrame(columns=["fecha", "descripcion", "canal", "nro_docto", "cargo", "abono", "saldo"])
        rango = (None, None)
    patrones = [clave(p) for p in params.patrones_cartola]
    entradas = [{"archivo_id": ac.id, "medio": medio, "fecha_abono": ac.fecha_abono,
                 "total_abono": r["total_abono"]}
                for ac in archivos if ac.tipo == ArchivoCargado.TRANSBANK for medio, r in ac.por_medio.items()]
    if entradas and cartolas:
        resultados_abono = conciliar_abonos(entradas, movimientos, rango, params)
    else:
        resultados_abono = [{**e, "categoria": cat.ABONO_CARTOLA, "cartola_fecha": None, "cartola_descripcion": "",
                             "cartola_monto": None, "cartola_indice": None, "diferencia": None,
                             "mensaje": "No se cargó cartola para verificar este abono."} for e in entradas]
    usadas = {r["cartola_indice"] for r in resultados_abono if r["cartola_indice"] is not None}
    MovimientoCartola.objects.bulk_create([MovimientoCartola(
        conciliacion=conc, fecha=m["fecha"], descripcion=m["descripcion"], canal=m["canal"],
        nro_docto=m["nro_docto"], cargo=m["cargo"], abono=m["abono"], saldo=m["saldo"],
        es_transbank=(es_tbk := m["abono"] > 0 and any(p in clave(m["descripcion"]) for p in patrones)),
        medio_probable=params.medio_probable(m["descripcion"]) if es_tbk else "",
        conciliado=i in usadas,
    ) for i, m in enumerate(movimientos.to_dict("records"))])
    ResultadoAbono.objects.bulk_create([ResultadoAbono(
        conciliacion=conc, archivo_id=r["archivo_id"], medio=r["medio"], fecha_abono=r["fecha_abono"],
        total_abono=r["total_abono"], categoria=r["categoria"], cartola_fecha=r["cartola_fecha"],
        cartola_descripcion=r["cartola_descripcion"], cartola_monto=r["cartola_monto"],
        diferencia=r["diferencia"], mensaje=r["mensaje"],
    ) for r in resultados_abono])

    # Conciliación diaria: manda Transbank. Los pagos del bordero sin venta no se listan (sin pendientes);
    # solo se cuentan las reversas del período de las ventas.
    desde, hasta = periodo_ventas(conc)
    if desde:
        pagos_del_mes = set(PagoBordero.objects.filter(id__in=pagos_del_mes, fecha__range=(desde, hasta))
                            .values_list("id", flat=True))

    conc.parametros = params.a_dict()
    conc.resumen = calcular_resumen(conc, params, pagos_del_mes)
    conc.estado = Conciliacion.PROCESADA
    conc.procesada_en = timezone.now()
    conc.save()
    return conc


def clave_venta(v) -> tuple:
    """Identidad de una venta para sus correcciones (la misma forma que CorreccionManual.clave)."""
    return v.medio, v.codigo_norm, v.cuota_num or 0, v.fecha_venta, v.monto_original


def pagos_corregidos(ventas: list[VentaTransbank], correcciones: dict) -> pd.DataFrame:
    """Un pago del bordero por cada corrección con datos, con id negativo para distinguirlo de los reales.
    Lleva el código de la venta: el cruce lo prefiere frente a los pagos reales con el mismo código."""
    filas = []
    for v in ventas:
        c = correcciones.get(clave_venta(v))
        if c is None or c.aceptada or c.monto is None:
            continue
        filas.append({"id": -c.pk, "documento": c.documento, "documento_norm": normalizar_codigo(c.documento),
                      "valor": -abs(c.monto), "fecha": c.fecha_bordero or v.fecha_venta, "cod_deb": c.cod_deb,
                      "pendiente_mes": None, "corregido": True})
    return pd.DataFrame(filas)


def guardar_correccion(venta: VentaTransbank, datos: dict) -> CorreccionManual:
    """Crea o edita la corrección de una venta anómala. La copia del dato original se toma solo al crearla.
    `datos`: documento, monto, cod_deb, fecha_bordero, aceptada y comentario (ya validados por el formulario)."""
    pago = venta.pago
    original = {
        "codigo_autorizacion": venta.codigo_autorizacion, "local": venta.local,
        "categoria_original": venta.categoria, "mensaje_original": venta.mensaje,
        "documento_original": venta.codigo_sugerido or (pago.documento if pago else ""),
        "monto_bordero_original": venta.monto_bordero, "cod_deb_original": pago.cod_deb if pago else "",
    }
    medio, codigo_norm, cuota_num, fecha_venta, monto_original = clave_venta(venta)
    c, _ = CorreccionManual.objects.update_or_create(
        conciliacion=venta.conciliacion, medio=medio, codigo_norm=codigo_norm, cuota_num=cuota_num,
        fecha_venta=fecha_venta, monto_original=monto_original, defaults=datos, create_defaults=original | datos)
    return c


def _aplicar_aceptadas(ventas: list[VentaTransbank], correcciones: dict) -> None:
    """Anomalía aceptada por el analista sin corregir datos: queda corregida y su comentario es la evidencia."""
    for v in ventas:
        c = correcciones.get(clave_venta(v))
        if c is not None and c.aceptada and v.categoria in cat.POR_RESOLVER:
            v.categoria = cat.CORREGIDO
            v.mensaje = mensaje(cat.CORREGIDO, detalle=f"Aceptada por el analista: {c.comentario}")


def periodo_ventas(conc: Conciliacion) -> tuple:
    """Primera y última fecha de venta Transbank de la conciliación (sin cuotas 2 y 3: son ventas de meses atrás)."""
    r = (conc.ventas.filter(es_venta=True).exclude(cuota_num__gt=1)
         .aggregate(desde=Min("fecha_venta"), hasta=Max("fecha_venta")))
    return r["desde"], r["hasta"]


def _cuotas_anteriores(conc: Conciliacion, ventas: list[VentaTransbank]) -> None:
    """Cuota k>1 cuya venta original ya se concilió en otra conciliación → queda conciliada con nota."""
    for v in ventas:
        if not v.cuota_num or v.cuota_num <= 1 or v.categoria not in (cat.CUOTA, cat.FUERA_PERIODO, cat.SIN_BORDERO):
            continue
        original = (VentaTransbank.objects.exclude(conciliacion=conc)
                    .filter(codigo_norm=v.codigo_norm, pago__isnull=False).select_related("conciliacion").first())
        if original:
            v.categoria = cat.OK
            v.nota = f"Cuota {v.cuota}; venta original conciliada en {original.conciliacion.etiqueta}"
            v.mensaje = mensaje(cat.OK)


def calcular_resumen(conc: Conciliacion, params: Parametros, pagos_del_mes: set) -> dict:
    """Totales por medio de pago y matriz categoría × medio (se guarda en la conciliación)."""
    por_medio = {m: {"ventas": 0, "comision_iva": 0, "abono_tbk": 0, "abono_cartola": 0, "diferencial": 0,
                     "n_ventas": 0, "n_falla": 0, "n_archivos": 0, "cuadratura": 0} for m in cat.MEDIOS}
    matriz = {k: {m: {"n": 0, "monto": 0} for m in cat.MEDIOS} for k in cat.ORDEN_CATEGORIAS}

    for ac in utilizables(conc):
        if ac.tipo != ArchivoCargado.TRANSBANK:
            continue
        for medio, datos in ac.por_medio.items():
            r = por_medio[medio]
            r["ventas"] += datos["total_ventas"]
            r["comision_iva"] += datos["comision"] + datos["iva_comision"]
            r["abono_tbk"] += datos["total_abono"]
            r["n_archivos"] += 1
    valido_por_medio = defaultdict(int)
    for v in conc.ventas.filter(es_venta=True):
        r = por_medio[v.medio]
        r["n_ventas"] += 1
        r["n_falla"] += int(v.es_falla)
        valido_por_medio[v.medio] += v.monto_abono_valido
        matriz[v.categoria][v.medio]["n"] += 1
        # Los montos de la matriz usan lo válido para abono, así suman exactamente "Ventas Transbank".
        matriz[v.categoria][v.medio]["monto"] += v.monto_abono_valido
    for a in conc.abonos.all():
        r = por_medio[a.medio]
        r["abono_cartola"] += a.cartola_monto or 0
        if a.categoria != cat.OK:
            r["n_falla"] += 1
            matriz[a.categoria][a.medio]["n"] += 1
            matriz[a.categoria][a.medio]["monto"] += a.total_abono
    for p in PagoBordero.objects.filter(id__in=pagos_del_mes, invalido=True):
        m = _medio_de_pago(p.cod_deb, params)
        matriz[cat.DATO_INVALIDO][m]["n"] += 1
        matriz[cat.DATO_INVALIDO][m]["monto"] += abs(p.valor)
    for m, r in por_medio.items():
        r["diferencial"] = r["abono_tbk"] - r["abono_cartola"]
        r["cuadratura"] = valido_por_medio[m] - r["ventas"]

    total = {k: sum(r[k] for r in por_medio.values()) for k in por_medio[cat.DEBITO]}
    sin_archivo = cartola_sin_archivo(conc)
    return {
        "medios": por_medio,
        "total": total,
        "matriz": matriz,
        "n_invalidos_bordero": PagoBordero.objects.filter(id__in=pagos_del_mes, invalido=True).count(),
        "cartola_sin_archivo": {"n": len(sin_archivo), "monto": sum(m.abono for m in sin_archivo)},
    }


def _validar_dolar(conc: Conciliacion) -> list[str]:
    """Una conciliación en dólares necesita el abono Transbank US$, el ERP y la cartera de cada tarjeta vendida.
    Ningún archivo se omite por su moneda; los del flujo en pesos (bordero, Transbank 'Abonos por día') no van aquí."""
    archivos = list(conc.archivos.all())
    errores = [f"{a.nombre}: {a.error}" for a in archivos if a.error]
    validos = [a for a in archivos if not a.error]
    errores += [f"{a.nombre}: es un archivo de la conciliación en pesos ({a.get_tipo_display()}); quítalo."
                for a in validos if a.tipo in (ArchivoCargado.BORDERO, ArchivoCargado.TRANSBANK)]
    abonos = [a for a in validos if a.tipo == ArchivoCargado.ABONO_USD]
    for tipo, nombre in [(ArchivoCargado.ABONO_USD, "el abono Transbank US$"), (ArchivoCargado.ERP, "el ERP de tarjetas")]:
        if not any(a.tipo == tipo for a in validos):
            errores.append(f"Falta {nombre}.")
    for dia, n in Counter(a.fecha_abono for a in abonos).items():
        if n > 1:
            errores.append(f"Hay {n} abonos Transbank US$ del {fmt_fecha(dia)}; quita el repetido.")
    carteras = Counter(a.resumen.get("marca") for a in validos if a.tipo == ArchivoCargado.EMISOR)
    for marca, n in carteras.items():
        if n > 1:
            errores.append(f"Hay {n} carteras de {usd.TARJETAS[marca]} US$; quita la repetida.")
    for marca in sorted({t for a in abonos for t in a.resumen.get("tarjetas", [])} - set(carteras)):
        errores.append(f"Falta la cartera de {usd.TARJETAS[marca]} US$ (hay ventas con esa tarjeta).")
    return errores


def _advertencias_dolar(conc: Conciliacion) -> list[str]:
    archivos = utilizables(conc)
    cartolas = [(a.desde, a.hasta) for a in archivos if a.tipo == ArchivoCargado.CARTOLA]
    if not cartolas:
        return ["No se cargó la cartola US$: no se verificará que el abono llegó al banco."]
    return [f"{a.nombre}: la cartola no cubre el abono del {fmt_fecha(a.fecha_abono)}." for a in archivos
            if a.tipo == ArchivoCargado.ABONO_USD and not any(d <= a.fecha_abono <= h for d, h in cartolas)]


def _procesar_dolar(conc: Conciliacion) -> Conciliacion:
    """Cruza las ventas del abono Transbank US$ con el ERP y las carteras, y verifica cada abono en la cartola US$."""
    archivos = utilizables(conc)
    del_tipo = lambda tipo: [ac for ac in archivos if ac.tipo == tipo]  # noqa: E731

    def leer(ac, lector, **kw):  # en R2 el archivo no tiene ruta local
        with ruta_local(ac) as ruta:
            return lector(ruta, **kw)

    abonos = [(ac, leer(ac, leer_abono_dolar)) for ac in del_tipo(ArchivoCargado.ABONO_USD)]
    erp = pd.concat([leer(ac, leer_erp) for ac in del_tipo(ArchivoCargado.ERP)], ignore_index=True)
    carteras = {c.marca: c.documentos for c in (leer(ac, leer_cartera) for ac in del_tipo(ArchivoCargado.EMISOR))}

    ventas = []
    for ac, a in abonos:
        if a.ventas.empty:
            continue
        for v, r in zip(a.ventas.to_dict("records"), usd.conciliar_ventas_dolar(a.ventas, erp, carteras)):
            ventas.append(VentaDolar(conciliacion=conc, archivo=ac, fila=v["fila"], tarjeta=v["tarjeta"],
                                     fecha_venta=v["fecha_venta"], hora=v["hora"],
                                     codigo_autorizacion=v["codigo_autorizacion"],
                                     monto_original=v["monto_original"], comision=v["comision"], **r))
    VentaDolar.objects.bulk_create(ventas)

    cartolas = [leer(ac, leer_cartola, monto=a_decimal) for ac in del_tipo(ArchivoCargado.CARTOLA)]
    if cartolas:
        movimientos = pd.concat([c.movimientos for c in cartolas], ignore_index=True)
        verificados = [usd.verificar_abono(a.resumen["abono"], a.fecha_abono, movimientos) for _, a in abonos]
    else:
        verificados = [{"monto": str(a.resumen["abono"]), "fecha_abono": a.fecha_abono.isoformat(), "en_cartola": None,
                        "cartola_fecha": None, "cartola_descripcion": "",
                        "mensaje": "No se cargó la cartola US$ para verificar este abono."} for _, a in abonos]

    conc.parametros = {"moneda": Conciliacion.USD}  # no vacío: si se vacía, no se reutiliza como borrador nuevo
    conc.resumen = resumen_dolar(ventas, verificados)
    conc.estado = Conciliacion.PROCESADA
    conc.procesada_en = timezone.now()
    conc.save()
    return conc


def resumen_dolar(ventas: list[VentaDolar], abonos: list[dict]) -> dict:
    """Totales por tarjeta y del abono (en float: el JSON no guarda Decimal; los centavos exactos están en VentaDolar).
    `total` usa las mismas claves que en pesos para que el historial lo muestre igual."""
    cero = {"n_ventas": 0, "n_falla": 0, "ventas": Decimal(0), "conciliado": Decimal(0), "cartera": Decimal(0)}
    por_tarjeta = {t: dict(cero) for t in usd.TARJETAS}
    for v in ventas:
        r = por_tarjeta[v.tarjeta]
        r["n_ventas"] += 1
        r["ventas"] += v.monto_original
        if v.es_falla:
            r["n_falla"] += 1
        else:
            r["conciliado"] += v.monto_original
            r["cartera"] += v.monto_cartera or 0
    for r in por_tarjeta.values():
        r["diferencia"] = r["conciliado"] - r["cartera"]
    total = {k: sum(r[k] for r in por_tarjeta.values()) for k in [*cero, "diferencia"]}
    abono_tbk = sum(Decimal(a["monto"]) for a in abonos)
    abono_cartola = sum(Decimal(a["monto"]) for a in abonos if a["en_cartola"])
    total |= {"abono_tbk": abono_tbk, "abono_cartola": abono_cartola, "diferencial": abono_tbk - abono_cartola}
    a_float = lambda d: {k: float(round(v, 2)) if isinstance(v, Decimal) else v for k, v in d.items()}  # noqa: E731
    return {"tarjetas": {t: a_float(r) for t, r in por_tarjeta.items() if r["n_ventas"]}, "total": a_float(total),
            "abonos": abonos, "n_pendientes": 0}


def cartola_sin_archivo(conc: Conciliacion) -> list[MovimientoCartola]:
    """Abonos Transbank que llegaron al banco en los días de abono conciliados pero cuyo archivo Transbank no se
    cargó. Los días siguientes pertenecen a la próxima conciliación diaria, y las líneas que ya calzaron en otra
    conciliación (la misma cartola se reutiliza) no se marcan."""
    dias = [a.fecha_abono for a in utilizables(conc) if a.tipo == ArchivoCargado.TRANSBANK and a.fecha_abono]
    if not dias:
        return []
    lineas = conc.movimientos_cartola.filter(es_transbank=True, conciliado=False, fecha__gte=min(dias),
                                             fecha__lte=max(dias)).order_by("fecha")
    en_otra = set(MovimientoCartola.objects.exclude(conciliacion=conc)
                  .filter(es_transbank=True, conciliado=True, fecha__gte=min(dias), fecha__lte=max(dias))
                  .values_list("fecha", "abono", "descripcion"))
    return [m for m in lineas if (m.fecha, m.abono, m.descripcion) not in en_otra]
