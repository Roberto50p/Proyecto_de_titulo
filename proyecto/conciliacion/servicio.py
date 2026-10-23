"""Servicio que lee los archivos de una conciliación, ejecuta el motor y guarda el resultado."""

import hashlib
from collections import defaultdict

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
from .motor.abonos import conciliar_abonos, cuadratura_archivo
from .motor.cruce import conciliar_ventas, pagos_tarjeta
from .motor.mensajes import fecha as fmt_fecha
from .motor.mensajes import mensaje, pesos
from .motor.parametros import Parametros


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
    )


def sha256_de(archivo) -> str:
    h = hashlib.sha256()
    for trozo in archivo.chunks():
        h.update(trozo)
    archivo.seek(0)
    return h.hexdigest()


# ---------------------------------------------------------------- lectura y validación


def leer_archivo(ac: ArchivoCargado) -> None:
    """Detecta el tipo del archivo y guarda sus metadatos (o el error de lectura)."""
    ruta = ac.archivo.path
    ac.error = ""
    try:
        ac.tipo = detectar(ruta)
        if ac.tipo == ArchivoCargado.TRANSBANK:
            a = leer_transbank(ruta)
            ac.medio, ac.moneda, ac.cuenta = a.medio, a.moneda, a.cuenta
            ac.fecha_abono, ac.desde, ac.hasta = a.fecha_abono, a.ventas.fecha_venta.min(), a.ventas.fecha_venta.max()
            ac.filas, ac.total_abono, ac.resumen = len(a.ventas), a.resumen["total_abono"], a.resumen
            if clave(a.moneda) != "pesos":
                ac.error = f"Moneda no soportada ({a.moneda}). Esta versión concilia abonos en pesos."
            elif a.fecha_abono != a.fecha_abono_hasta:
                ac.error = "El archivo abarca varios días de abono; descarga un reporte por día desde Transbank."
            elif cuadratura_archivo(a.resumen):
                ac.error = (f"El resumen del archivo no cuadra: Total abono {pesos(a.resumen['total_abono'])} "
                            f"no coincide con ventas menos comisiones (diferencia {pesos(cuadratura_archivo(a.resumen))}).")
        elif ac.tipo == ArchivoCargado.BORDERO:
            b = leer_bordero(ruta)
            ac.desde, ac.hasta, ac.filas = b.desde, b.hasta, len(b.movimientos)
        else:
            c = leer_cartola(ruta)
            ac.cuenta, ac.moneda, ac.desde, ac.hasta, ac.filas = c.cuenta, c.moneda, c.desde, c.hasta, len(c.movimientos)
            if not clave(c.moneda).startswith("pesos"):
                ac.error = f"Moneda no soportada ({c.moneda}). Esta versión concilia la cartola en pesos."
    except ArchivoNoReconocido as exc:
        ac.tipo, ac.error = ArchivoCargado.DESCONOCIDO, str(exc)
    except Exception as exc:  # archivo con el formato esperado pero dañado
        ac.tipo, ac.error = ArchivoCargado.DESCONOCIDO, f"No se pudo leer el archivo: {exc}"
    ac.save()


def validar(conc: Conciliacion) -> list[str]:
    """Errores que impiden conciliar."""
    errores = []
    archivos = list(conc.archivos.all())
    for a in archivos:
        if a.error:
            errores.append(f"{a.nombre}: {a.error}")
    tipos = {a.tipo for a in archivos if not a.error}
    for tipo, nombre in [(ArchivoCargado.BORDERO, "el bordero"), (ArchivoCargado.CARTOLA, "la cartola"),
                         (ArchivoCargado.TRANSBANK, "al menos un archivo Transbank")]:
        if tipo not in tipos:
            errores.append(f"Falta {nombre}.")
    for a in archivos:
        if a.tipo == ArchivoCargado.TRANSBANK and a.fecha_abono and not a.error:
            if (a.fecha_abono.year, a.fecha_abono.month) != (conc.anio, conc.mes):
                errores.append(f"{a.nombre}: la fecha de abono {fmt_fecha(a.fecha_abono)} no pertenece a "
                               f"{conc.etiqueta}.")
    return errores


def advertencias(conc: Conciliacion) -> list[str]:
    """Situaciones que no impiden conciliar pero conviene saber."""
    avisos = []
    archivos = [a for a in conc.archivos.all() if not a.error]
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


def _deshacer(conc: Conciliacion) -> dict:
    """Revierte el resultado anterior de la conciliación y devuelve las observaciones a conservar."""
    guardado = {
        "ventas": {(v.categoria, v.codigo_autorizacion, v.fecha_venta): (v.revisado, v.observacion)
                   for v in conc.ventas.all() if v.revisado or v.observacion},
        "abonos": {r.archivo_id: (r.revisado, r.observacion)
                   for r in conc.abonos.all() if r.revisado or r.observacion},
        "pendientes": {p.pago_id: (p.revisado, p.observacion)
                       for p in conc.pendientes.all() if p.revisado or p.observacion},
    }
    Pendiente.objects.filter(cierre=conc).update(abierto=True, cierre=None)
    conc.pendientes.all().delete()
    PagoBordero.objects.filter(conciliacion=conc).update(conciliacion=None)
    conc.ventas.all().delete()
    conc.abonos.all().delete()
    conc.movimientos_cartola.all().delete()
    return guardado


def _registrar_bordero(ac: ArchivoCargado, params: Parametros) -> list[int]:
    b = leer_bordero(ac.archivo.path)
    CoberturaBordero.objects.get_or_create(desde=b.desde, hasta=b.hasta, archivo=ac)
    ids = []
    for fila in pagos_tarjeta(b.movimientos, params).to_dict("records"):
        pago, _ = PagoBordero.objects.get_or_create(
            documento_norm=fila["documento_norm"], fecha=fila["fecha"], hora=fila["hora"],
            valor=fila["valor"], cuenta=fila["cuenta"], cod_deb=fila["cod_deb"],
            defaults={k: fila[k] for k in ["hab", "reserva", "descripcion", "factura", "documento",
                                           "usuario", "designacion"]} | {"invalido": bool(fila["invalido"]),
                                                                         "archivo": ac},
        )
        ids.append(pago.id)
    return ids


def _medio_de_pago(cod_deb: str, params: Parametros) -> str:
    medios = params.medios_de(cod_deb)
    return next((m for m in cat.MEDIOS if m in medios), cat.DEBITO)


@transaction.atomic
def procesar(conc: Conciliacion) -> Conciliacion:
    guardado = _deshacer(conc)
    params = parametros_actuales()
    archivos = [a for a in conc.archivos.all() if not a.error]

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
        v.revisado, v.observacion = guardado["ventas"].get((v.categoria, v.codigo_autorizacion, v.fecha_venta),
                                                           (False, ""))
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
    MovimientoCartola.objects.bulk_create([MovimientoCartola(
        conciliacion=conc, fecha=m["fecha"], descripcion=m["descripcion"], canal=m["canal"],
        nro_docto=m["nro_docto"], cargo=m["cargo"], abono=m["abono"], saldo=m["saldo"],
        es_transbank=m["abono"] > 0 and any(p in clave(m["descripcion"]) for p in patrones),
    ) for m in movimientos.to_dict("records")])
    entradas = [{"archivo_id": ac.id, "medio": ac.medio, "fecha_abono": ac.fecha_abono,
                 "total_abono": ac.total_abono} for ac in archivos if ac.tipo == ArchivoCargado.TRANSBANK]
    if entradas and cartolas:
        resultados_abono = conciliar_abonos(entradas, movimientos, rango, params)
    else:
        resultados_abono = [{**e, "categoria": cat.ABONO_CARTOLA, "cartola_fecha": None, "cartola_descripcion": "",
                             "cartola_monto": None, "diferencia": None,
                             "mensaje": "No se cargó cartola para verificar este abono."} for e in entradas]
    ResultadoAbono.objects.bulk_create([ResultadoAbono(
        conciliacion=conc, archivo_id=r["archivo_id"], medio=r["medio"], fecha_abono=r["fecha_abono"],
        total_abono=r["total_abono"], categoria=r["categoria"], cartola_fecha=r["cartola_fecha"],
        cartola_descripcion=r["cartola_descripcion"], cartola_monto=r["cartola_monto"],
        diferencia=r["diferencia"], mensaje=r["mensaje"],
        revisado=guardado["abonos"].get(r["archivo_id"], (False, ""))[0],
        observacion=guardado["abonos"].get(r["archivo_id"], (False, ""))[1],
    ) for r in resultados_abono])

    # Pagos del bordero de este mes que siguen sin abono → pendientes.
    sin_abono = PagoBordero.objects.filter(id__in=pagos_del_mes, conciliacion__isnull=True, invalido=False,
                                           pendiente__isnull=True)
    Pendiente.objects.bulk_create([Pendiente(
        pago=p, medio=_medio_de_pago(p.cod_deb, params), origen=conc,
        mensaje=mensaje(cat.SIN_ABONO, cod_deb=p.cod_deb, fecha_bordero=fmt_fecha(p.fecha),
                        monto_bordero=pesos(abs(p.valor)), documento=p.documento or "(vacío)"),
        revisado=guardado["pendientes"].get(p.id, (False, ""))[0],
        observacion=guardado["pendientes"].get(p.id, (False, ""))[1],
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

    for ac in conc.archivos.filter(tipo=ArchivoCargado.TRANSBANK, error=""):
        r = por_medio[ac.medio]
        r["ventas"] += ac.resumen.get("total_ventas", 0)
        r["comision_iva"] += ac.resumen.get("comision", 0) + ac.resumen.get("iva_comision", 0)
        r["abono_tbk"] += ac.total_abono or 0
        r["n_archivos"] += 1
    valido_por_medio = defaultdict(int)
    for v in conc.ventas.filter(es_venta=True):
        r = por_medio[v.medio]
        r["n_ventas"] += 1
        r["n_falla"] += int(v.es_falla)
        valido_por_medio[v.medio] += v.monto_abono_valido
        matriz[v.categoria][v.medio]["n"] += 1
        matriz[v.categoria][v.medio]["monto"] += v.monto_original
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
    return {
        "medios": por_medio,
        "total": total,
        "matriz": matriz,
        "n_pendientes": conc.pendientes.count(),
        "n_pendientes_cerrados": Pendiente.objects.filter(cierre=conc).count(),
        "n_invalidos_bordero": PagoBordero.objects.filter(id__in=pagos_del_mes, invalido=True).count(),
    }
