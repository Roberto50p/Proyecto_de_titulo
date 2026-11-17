from conciliacion.models import PagoBordero, Pendiente
from datetime import date

from conciliacion.servicio import procesar, validar


def test_conciliacion_diaria_sin_pendientes(septiembre_procesado):
    # Manda Transbank: los pagos del bordero sin venta no se guardan como pendientes.
    assert not Pendiente.objects.exists()
    assert septiembre_procesado.ventas.count() == 141


def test_bordero_traslapado_no_duplica(crear_conciliacion):
    procesar(crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx"]))
    total = PagoBordero.objects.count()
    procesar(crear_conciliacion(["BORDERO 04-09 A 07-09.xlsx"]))
    assert PagoBordero.objects.count() == total == 228


def _corregir(venta, **datos):
    from conciliacion.servicio import guardar_correccion

    base = {"documento": "", "monto": None, "cod_deb": "", "fecha_bordero": None, "aceptada": False, "comentario": ""}
    return guardar_correccion(venta, base | datos)


def _por_resolver(conc):
    from conciliacion.reportes.datos import armar

    return armar(conc)["por_resolver"]


def test_reprocesar_no_duplica(septiembre_procesado):
    procesar(septiembre_procesado)
    assert septiembre_procesado.ventas.count() == 141
    assert PagoBordero.objects.filter(conciliacion=septiembre_procesado).count() == 104


def test_correccion_que_calza_queda_verificada(septiembre_procesado):
    conc = septiembre_procesado
    v = conc.ventas.select_related("pago").get(codigo_autorizacion="007626")
    assert v.categoria == "DIF_MONTO"
    antes = _por_resolver(conc)
    c = _corregir(v, documento=v.codigo_autorizacion, monto=v.monto_original, cod_deb=v.pago.cod_deb,
                  fecha_bordero=v.pago.fecha, comentario="Monto corregido en FrontOffice")
    assert (c.categoria_original, c.monto_bordero_original) == ("DIF_MONTO", v.monto_bordero)  # copia del original
    procesar(conc)
    v = conc.ventas.get(codigo_autorizacion="007626")
    assert v.categoria == "CORREGIDO" and v.pago is None and "Monto corregido en FrontOffice" in v.mensaje
    assert _por_resolver(conc) == {"n": antes["n"] - 1, "monto": antes["monto"] - v.monto_abono_valido}


def test_correccion_que_no_calza_sigue_anomala(septiembre_procesado):
    conc = septiembre_procesado
    v = conc.ventas.select_related("pago").get(codigo_autorizacion="007626")
    _corregir(v, documento=v.codigo_autorizacion, monto=v.monto_original + 5000, cod_deb=v.pago.cod_deb)
    procesar(conc)
    v = conc.ventas.get(codigo_autorizacion="007626")
    assert v.categoria == "DIF_MONTO" and "no calza" in v.nota


def test_corregir_digitacion_con_el_codigo_de_transbank(septiembre_procesado):
    conc = septiembre_procesado
    v = conc.ventas.select_related("pago").get(codigo_autorizacion="F0FUAZ")
    assert v.categoria == "DIGITACION"
    _corregir(v, documento="F0FUAZ", monto=v.monto_bordero, cod_deb=v.pago.cod_deb, fecha_bordero=v.pago.fecha)
    procesar(conc)
    assert conc.ventas.get(codigo_autorizacion="F0FUAZ").categoria == "CORREGIDO"


def test_aceptar_sin_corregir_exige_comentario(db):
    from conciliacion.forms import CorreccionForm

    equivalencias = {"RCO": {"DEBITO", "PREPAGO"}, "V$": {"CREDITO"}}

    def form(categoria, medio="CREDITO", initial=None, **datos):
        return CorreccionForm(datos, initial=initial, categoria=categoria, medio=medio, cod_debs=equivalencias)

    assert not form("DIF_MONTO", aceptada="on").is_valid()
    assert form("DIF_MONTO", aceptada="on", comentario="Propina").is_valid()
    assert not form("MEDIO_DISTINTO").is_valid()  # solo se acepta: el comentario es obligatorio
    f = form("MEDIO_DISTINTO", comentario="Fue crédito")
    assert f.is_valid() and f.cleaned_data["aceptada"] is True
    assert not form("SIN_BORDERO", aceptada="on", comentario="x").is_valid()  # no se acepta: faltan los datos
    assert not form("SIN_BORDERO", documento="123", monto="1000", cod_deb="V$").is_valid()  # falta el comentario
    assert form("SIN_BORDERO", documento="123", monto="1000", cod_deb="V$", comentario="Voucher 55").is_valid()
    assert not form("SIN_BORDERO", documento="123", monto="1000", cod_deb="RCO",
                    comentario="x").is_valid()  # RCO no es crédito


def test_cada_categoria_edita_solo_lo_que_esta_mal(db):
    from datetime import date

    from conciliacion.forms import CorreccionForm

    bordero = {"documento": "00219I", "monto": 13000, "cod_deb": "V$", "fecha_bordero": date(2026, 10, 29)}

    def form(categoria, medio="CREDITO", **datos):
        return CorreccionForm(datos or None, initial=bordero, categoria=categoria, medio=medio,
                              cod_debs={"RCO": {"DEBITO", "PREPAGO"}, "V$": {"CREDITO"}, "MC$": {"CREDITO"}})

    editables = lambda f: [k for k in f.fields if k != "comentario"]  # noqa: E731
    assert editables(form("DIGITACION")) == ["documento"]
    assert editables(form("DIF_MONTO")) == ["monto", "aceptada"]
    assert editables(form("SIN_BORDERO")) == ["documento", "monto", "cod_deb"]  # la fecha nunca se edita
    assert editables(form("MEDIO_DISTINTO")) == []
    # En crédito no se ofrece RCO; en débito solo RCO (sin opción vacía).
    assert [k for k, _ in form("SIN_BORDERO").fields["cod_deb"].choices] == ["", "MC$", "V$"]
    assert form("SIN_BORDERO", medio="DEBITO").fields["cod_deb"].choices == [("RCO", "RCO · Redcompra")]
    # Lo que no se muestra se toma del bordero, aunque el navegador mande otro valor.
    f = form("DIGITACION", documento="2191X", monto="1")
    assert f.is_valid()
    assert (f.cleaned_data["documento"], f.cleaned_data["monto"], f.cleaned_data["cod_deb"]) == ("2191X", 13000, "V$")
    f = form("SIN_BORDERO", documento="1", monto="5", cod_deb="V$", comentario="Voucher", fecha_bordero="2020-01-01")
    assert f.is_valid() and f.cleaned_data["fecha_bordero"] == date(2026, 10, 29)  # la del bordero/venta, no la enviada


def test_marca_de_la_tarjeta():
    from conciliacion.motor.parametros import cod_deb_de_tarjeta

    assert cod_deb_de_tarjeta("4929 13** **** 8005") == "V$"
    assert cod_deb_de_tarjeta("5229 48** **** 4096") == "MC$"
    assert cod_deb_de_tarjeta("2221 00** **** 1111") == "MC$"
    assert cod_deb_de_tarjeta("3712 34** **** 1005") == "AME$"
    assert cod_deb_de_tarjeta("3600 12** **** 0001") == "D$"
    assert cod_deb_de_tarjeta("**** **** **** 8005") == cod_deb_de_tarjeta("") == ""


def test_aceptada_queda_corregida_y_se_puede_quitar(septiembre_procesado):
    conc = septiembre_procesado
    v = conc.ventas.get(codigo_autorizacion="007626")
    c = _corregir(v, aceptada=True, comentario="Propina cobrada aparte")
    procesar(conc)
    assert conc.ventas.get(codigo_autorizacion="007626").categoria == "CORREGIDO"
    c.delete()
    procesar(conc)
    assert conc.ventas.get(codigo_autorizacion="007626").categoria == "DIF_MONTO"


# ---- Correcciones de la revisión final

def test_abonos_de_cartola_sin_archivo(septiembre_procesado):
    from conciliacion.servicio import cartola_sin_archivo

    lineas = cartola_sin_archivo(septiembre_procesado)
    # Solo los días de abono cargados (08/09), no el mes completo.
    assert all(m.fecha == date(2026, 9, 8) for m in lineas)
    sin_archivo = septiembre_procesado.resumen["cartola_sin_archivo"]
    # Antes (mes completo) eran 16 líneas por $26.036.232; el 08 y 09/09 no hay abonos Transbank sin archivo.
    assert sin_archivo == {"n": len(lineas), "monto": 0} and lineas == []


def test_acepta_abono_de_cualquier_fecha(crear_conciliacion):
    assert validar(crear_conciliacion()) == []


def test_matriz_cuadra_con_ventas_transbank(septiembre_procesado):
    from conciliacion.motor import categorias as cat

    r = septiembre_procesado.resumen
    ventas = {k for k in cat.ORDEN_CATEGORIAS if k not in (cat.SIN_ABONO, cat.ABONO_CARTOLA, cat.DATO_INVALIDO)}
    for medio in cat.MEDIOS:
        suma = sum(r["matriz"][k][medio]["monto"] for k in ventas)
        assert suma == r["medios"][medio]["ventas"]


def test_documento_corregido_en_bordero_no_crea_pendiente_falso(septiembre_procesado, crear_conciliacion,
                                                                datos_reales, tmp_path):
    from django.core.files import File
    from openpyxl import load_workbook

    from conciliacion.models import ArchivoCargado
    from conciliacion.servicio import leer_archivo, sha256_de

    libro = load_workbook(datos_reales / "BORDERO 04-09 A 07-09.xlsx")
    hoja = libro.active
    for fila in hoja.iter_rows():
        for celda in fila:
            if celda.value == "0FOFUAZ":
                celda.value = "F0FUAZ"
    corregido = tmp_path / "bordero corregido.xlsx"
    libro.save(corregido)

    octubre = crear_conciliacion([])
    with open(corregido, "rb") as f:
        archivo = File(f, name=corregido.name)
        ac = ArchivoCargado(conciliacion=octubre, nombre=corregido.name, sha256=sha256_de(archivo))
        ac.archivo.save(corregido.name, archivo, save=False)
        ac.save()
    leer_archivo(ac)
    procesar(octubre)
    assert PagoBordero.objects.count() == 228
    pago = PagoBordero.objects.get(documento="F0FUAZ")
    assert pago.conciliacion == septiembre_procesado
    assert not octubre.pendientes.exists()


def test_cartola_sin_archivo_solo_dias_de_abono(db):
    from conciliacion.models import ArchivoCargado, Conciliacion, MovimientoCartola
    from conciliacion.servicio import cartola_sin_archivo

    conc = Conciliacion.objects.create(parametros={"dias_holgura": 1})
    ArchivoCargado.objects.create(conciliacion=conc, tipo=ArchivoCargado.TRANSBANK, nombre="tbk.xlsx", sha256="a",
                                  moneda="Pesos chilenos", fecha_abono=date(2026, 9, 8), archivo="tbk.xlsx")
    for dia in (7, 8, 9, 10):
        MovimientoCartola.objects.create(conciliacion=conc, fecha=date(2026, 9, dia), abono=1000, es_transbank=True)
    # El 09/09 (día siguiente) es de la próxima conciliación diaria: no se marca aquí.
    assert [m.fecha.day for m in cartola_sin_archivo(conc)] == [8]


def test_cartola_sin_archivo_omite_lineas_conciliadas_en_otra(db):
    from conciliacion.models import ArchivoCargado, Conciliacion, MovimientoCartola
    from conciliacion.servicio import cartola_sin_archivo

    otra = Conciliacion.objects.create()
    MovimientoCartola.objects.create(conciliacion=otra, fecha=date(2026, 9, 8), descripcion="ABONO TBK", abono=500,
                                     es_transbank=True, conciliado=True)
    conc = Conciliacion.objects.create()
    ArchivoCargado.objects.create(conciliacion=conc, tipo=ArchivoCargado.TRANSBANK, nombre="tbk.xlsx", sha256="a",
                                  moneda="Pesos chilenos", fecha_abono=date(2026, 9, 8), archivo="tbk.xlsx")
    for monto in (500, 700):
        MovimientoCartola.objects.create(conciliacion=conc, fecha=date(2026, 9, 8), descripcion="ABONO TBK",
                                         abono=monto, es_transbank=True)
    assert [m.abono for m in cartola_sin_archivo(conc)] == [700]


def test_cuadratura_pendiente_mientras_haya_anomalias(septiembre_procesado):
    from conciliacion.motor import categorias as cat
    from conciliacion.reportes.datos import armar, texto_cuadratura

    d = armar(septiembre_procesado)
    anomalas = septiembre_procesado.ventas.filter(es_venta=True, categoria__in=cat.POR_RESOLVER)
    assert d["por_resolver"] == {"n": anomalas.count(), "monto": sum(v.monto_abono_valido for v in anomalas)}
    assert d["por_resolver"]["n"] > 0 and not d["cuadratura_ok"]
    assert d["texto_cuadratura"].startswith("Cuadratura pendiente")
    assert texto_cuadratura(True, {"n": 0, "monto": 0}).startswith("Cuadratura correcta")
    assert texto_cuadratura(False, {"n": 0, "monto": 0}).startswith("La suma de las categorías no coincide")
