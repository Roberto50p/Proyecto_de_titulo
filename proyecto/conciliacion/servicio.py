"""Servicio que lee los archivos de una conciliación, ejecuta el motor y guarda el resultado."""

import hashlib
from collections import Counter, defaultdict

import pandas as pd
from django.db import transaction
from django.utils import timezone

from .lectores.bordero import leer_bordero
from .lectores.cartola import leer_cartola
from .lectores.comunes import ArchivoNoReconocido, clave
from .lectores.deteccion import detectar
from .lectores.transbank import leer_transbank
from .models import (
    ArchivoCargado,
    Conciliacion,
    CoberturaBordero,
    EquivalenciaMedio,
    MovimientoCartola,
    PagoBordero,
    ParametrosSistema,
    Pendiente,
    ResultadoAbono,
    VentaTransbank,
)
from .motor import categorias as cat
from .motor.abonos import conciliar_abonos, cuadratura_archivo, cuadratura_por_medio
from .motor.cruce import conciliar_ventas, pagos_tarjeta
from .motor.mensajes import fecha as fmt_fecha
from .motor.mensajes import mensaje, pesos
from .motor.parametros import Parametros, leer_reglas_medio


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
    ruta = ac.archivo.path
    ac.error, ac.medio, ac.por_medio, ac.banco = "", "", {}, ""
    try:
        ac.tipo = detectar(ruta)
        if ac.tipo == ArchivoCargado.TRANSBANK:
            a = leer_transbank(ruta)
            ac.medio, ac.por_medio, ac.moneda, ac.cuenta = a.medio or "", a.resumen_por_medio, a.moneda, a.cuenta
            ac.fecha_abono, ac.desde, ac.hasta = a.fecha_abono, a.ventas.fecha_venta.min(), a.ventas.fecha_venta.max()
            ac.filas, ac.total_abono, ac.resumen = len(a.ventas), a.resumen["total_abono"], a.resumen
            if not ac.moneda_extranjera:
                ac.error = _error_transbank(a)
        elif ac.tipo == ArchivoCargado.BORDERO:
            b = leer_bordero(ruta)
            ac.desde, ac.hasta, ac.filas = b.desde, b.hasta, len(b.movimientos)
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


def validar(conc: Conciliacion) -> list[str]:
    """Errores que impiden conciliar."""
    errores = []
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
    for a in transbank:
        if (a.fecha_abono.year, a.fecha_abono.month) != (conc.anio, conc.mes):
            errores.append(f"{a.nombre}: la fecha de abono {fmt_fecha(a.fecha_abono)} no pertenece a "
                           f"{conc.etiqueta}.")
    # Un archivo con todos los medios cuenta para cada medio que trae.
    repetidos = Counter((medio, a.fecha_abono) for a in transbank for medio in a.por_medio)
    for (medio, dia), n in repetidos.items():
        if n > 1:
            errores.append(f"Hay {n} archivos Transbank de {cat.ETIQUETA_MEDIO[medio]} con abono del {fmt_fecha(dia)}; "
                           "quita el repetido (un archivo con todos los medios incluye cada medio).")
    return errores


def advertencias(conc: Conciliacion) -> list[str]:
    """Situaciones que no impiden conciliar pero conviene saber."""
    avisos = []
    if ParametrosSistema.cargar().omitir_moneda_extranjera:
        avisos += [f"{a.nombre}: está en {a.moneda or 'moneda no informada'}; se omite (esta versión concilia en "
                   "pesos)." for a in conc.archivos.all() if not a.error and a.moneda_extranjera]
    archivos = utilizables(conc)
    borderos = [(a.desde, a.hasta) for a in archivos if a.tipo == ArchivoCargado.BORDERO]
    borderos += [(c.desde, c.hasta) for c in CoberturaBordero.objects.all()]
    for a in archivos:
        if a.tipo == ArchivoCargado.TRANSBANK and a.desde and borderos:
            if not any(d <= a.desde <= h for d, h in borderos):
                avisos.append(f"{a.nombre}: hay ventas desde el {fmt_fecha(a.desde)} que ningún bordero cargado "
                              "cubre; quedarán como 'Fuera del período del bordero'.")
    cartolas = [(a.desde, a.hasta) for a in archivos if a.tipo == ArchivoCargado.CARTOLA]
    for a in archivos:
        if a.tipo == ArchivoCargado.TRANSBANK and a.fecha_abono and cartolas:
            if not any(d <= a.fecha_abono <= h for d, h in cartolas):
                avisos.append(f"{a.nombre}: la cartola no cubre el abono del {fmt_fecha(a.fecha_abono)}.")
    return avisos


# ---------------------------------------------------------------- procesamiento


def _clave_venta(categoria, codigo, fecha_venta) -> str:
    return f"{categoria}|{codigo}|{fecha_venta.isoformat()}"


def _clave_abono(medio, fecha_abono) -> str:
    # Sin el archivo: la observación se mantiene aunque se reemplace el archivo Transbank del mismo día.
    return f"{medio}|{fecha_abono.isoformat()}"


def _guardar_observaciones(conc: Conciliacion) -> None:
    """Lleva a conc.observaciones lo revisado/observado del resultado actual, sin perder lo guardado antes para
    filas que hoy no están (por ejemplo, ventas de un archivo que se quitó y se volverá a subir)."""
    guardadas = conc.observaciones or {}
    filas = [
        ("ventas", conc.ventas.all(), lambda v: _clave_venta(v.categoria, v.codigo_autorizacion, v.fecha_venta)),
        ("abonos", conc.abonos.all(), lambda r: _clave_abono(r.medio, r.fecha_abono)),
        ("pendientes", conc.pendientes.all(), lambda p: str(p.pago_id)),
    ]
    for grupo, registros, clave_de in filas:
        grupo_guardado = guardadas.setdefault(grupo, {})
        for r in registros:
            if r.revisado or r.observacion:
                grupo_guardado[clave_de(r)] = [r.revisado, r.observacion]
            else:
                grupo_guardado.pop(clave_de(r), None)
    conc.observaciones = guardadas


def _observacion(conc: Conciliacion, grupo: str, clave_registro: str) -> dict:
    revisado, observacion = conc.observaciones.get(grupo, {}).get(clave_registro, (False, ""))
    return {"revisado": revisado, "observacion": observacion}


def _deshacer(conc: Conciliacion) -> None:
    """Revierte el resultado anterior de la conciliación; sus observaciones quedan en conc.observaciones.

    Los pendientes que ya cerró un mes posterior se mantienen: su historia pertenece a ese mes.
    """
    _guardar_observaciones(conc)
    Pendiente.objects.filter(cierre=conc).update(abierto=True, cierre=None)
    conc.pendientes.filter(cierre__isnull=True).delete()
    PagoBordero.objects.filter(conciliacion=conc).update(conciliacion=None)
    conc.ventas.all().delete()
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
    o dejado como pendientes: esa historia pertenece a ese mes.
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
    """Deja la conciliación sin archivos para volver a conciliar el mismo mes con otros."""
    with transaction.atomic():
        for ac in list(conc.archivos.all()):
            quitar_archivo(ac)


def _registrar_bordero(ac: ArchivoCargado, params: Parametros) -> list[int]:
    """Guarda los pagos con tarjeta del bordero sin duplicarlos.

    Un pago se identifica por fecha, hora, cuenta y Cod. Deb.; si el hotel corrigió el documento o el valor en
    FrontOffice y vuelve a exportar, se actualiza el mismo pago en vez de crear otro.
    """
    b = leer_bordero(ac.archivo.path)
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

    # Transbank: ventas de todos los archivos del mes.
    ventas_obj = []
    for ac in archivos:
        if ac.tipo != ArchivoCargado.TRANSBANK:
            continue
        a = leer_transbank(ac.archivo.path)
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

    if not ventas_df.empty:
        resultado = conciliar_ventas(ventas_df, pagos, cobertura, params)
        for r in resultado.to_dict("records"):
            v = ventas_obj[r["venta_id"]]
            v.categoria, v.mensaje, v.nota = r["categoria"], r["mensaje"], r["nota"]
            v.codigo_sugerido = "" if pd.isna(r["codigo_sugerido"]) else r["codigo_sugerido"]
            if not pd.isna(r["pago_id"]):
                v.pago = pagos_por_id[int(r["pago_id"])]
                v.monto_bordero, v.diferencia = int(r["monto_bordero"]), int(r["diferencia"])
    _cuotas_anteriores(conc, ventas_obj)
    for v in ventas_obj:
        guardada = _observacion(conc, "ventas", _clave_venta(v.categoria, v.codigo_autorizacion, v.fecha_venta))
        v.revisado, v.observacion = guardada["revisado"], guardada["observacion"]
    VentaTransbank.objects.bulk_create(ventas_obj)

    # Pagos usados quedan conciliados en este mes; si eran pendientes, se cierran.
    usados = [v.pago_id for v in ventas_obj if v.pago_id]
    PagoBordero.objects.filter(id__in=usados).update(conciliacion=conc)
    Pendiente.objects.filter(pago_id__in=usados, abierto=True).update(abierto=False, cierre=conc)

    # Abonos contra cartola.
    cartolas = [leer_cartola(ac.archivo.path) for ac in archivos if ac.tipo == ArchivoCargado.CARTOLA]
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
        **_observacion(conc, "abonos", _clave_abono(r["medio"], r["fecha_abono"])),
    ) for r in resultados_abono])

    # Pagos del bordero de este mes que siguen sin abono → pendientes.
    sin_abono = PagoBordero.objects.filter(id__in=pagos_del_mes, conciliacion__isnull=True, invalido=False,
                                           pendiente__isnull=True)
    Pendiente.objects.bulk_create([Pendiente(
        pago=p, medio=_medio_de_pago(p.cod_deb, params), origen=conc,
        mensaje=mensaje(cat.SIN_ABONO, cod_deb=p.cod_deb, fecha_bordero=fmt_fecha(p.fecha),
                        monto_bordero=pesos(abs(p.valor)), documento=p.documento or "(vacío)"),
        **_observacion(conc, "pendientes", str(p.id)),
    ) for p in sin_abono])

    conc.parametros = params.a_dict()
    conc.resumen = calcular_resumen(conc, params, pagos_del_mes)
    conc.estado = Conciliacion.PROCESADA
    conc.procesada_en = timezone.now()
    conc.save()
    return conc


def _cuotas_anteriores(conc: Conciliacion, ventas: list[VentaTransbank]) -> None:
    """Cuota k>1 cuya venta original ya se concilió en otro mes → queda conciliada con nota."""
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
    for p in conc.pendientes.select_related("pago"):
        matriz[cat.SIN_ABONO][p.medio]["n"] += 1
        matriz[cat.SIN_ABONO][p.medio]["monto"] += abs(p.pago.valor)
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
        "n_pendientes": conc.pendientes.count(),
        "n_pendientes_cerrados": Pendiente.objects.filter(cierre=conc).count(),
        "n_invalidos_bordero": PagoBordero.objects.filter(id__in=pagos_del_mes, invalido=True).count(),
        "cartola_sin_archivo": {"n": len(sin_archivo), "monto": sum(m.abono for m in sin_archivo)},
    }


def cartola_sin_archivo(conc: Conciliacion) -> list[MovimientoCartola]:
    """Abonos Transbank que llegaron al banco en el mes pero cuyo archivo Transbank no se cargó."""
    return list(conc.movimientos_cartola.filter(es_transbank=True, conciliado=False, fecha__year=conc.anio,
                                                fecha__month=conc.mes).order_by("fecha"))
