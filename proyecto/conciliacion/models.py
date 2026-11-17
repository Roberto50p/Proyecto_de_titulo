from django.conf import settings
from django.db import models
from django.db.models import Max, Min, Q
from django.utils import timezone

from .lectores.comunes import clave
from .motor import categorias as cat
from .motor.parametros import (NOMBRE_COD_DEB, REGLAS_MEDIO_CARTOLA_INICIALES, cod_deb_de_tarjeta,
                               escribir_reglas_medio)

MEDIO_CHOICES = [(m, cat.ETIQUETA_MEDIO[m]) for m in cat.MEDIOS]
CATEGORIA_CHOICES = [(k, v) for k, v in cat.ETIQUETA.items()]


class ParametrosSistema(models.Model):
    """Parámetros vigentes (una sola fila, id=1)."""

    tolerancia_clp = models.PositiveIntegerField("Tolerancia en pesos", default=100)
    umbral_similitud = models.FloatField("Similitud mínima de códigos", default=0.75)
    dias_holgura = models.PositiveSmallIntegerField("Días hábiles de holgura en cartola", default=1)
    ventana_dias = models.PositiveSmallIntegerField("Días máximos entre venta y registro en bordero", default=3)
    patrones_cartola = models.CharField("Textos que identifican abonos Transbank en la cartola",
                                        max_length=200, default="transbank, tbk")
    reglas_medio_cartola = models.TextField("Medio probable según la descripción de la cartola", blank=True,
                                            default=escribir_reglas_medio(REGLAS_MEDIO_CARTOLA_INICIALES))
    omitir_moneda_extranjera = models.BooleanField("Omitir archivos en moneda extranjera", default=False)

    class Meta:
        verbose_name = "parámetros"
        verbose_name_plural = "parámetros"

    @classmethod
    def cargar(cls) -> "ParametrosSistema":
        return cls.objects.get_or_create(pk=1)[0]


class EquivalenciaMedio(models.Model):
    """Qué medio de pago puede representar cada código de débito del bordero (Cod. Deb.)."""

    cod_deb = models.CharField("Cod. Deb.", max_length=20)
    medio = models.CharField(max_length=10, choices=MEDIO_CHOICES)

    class Meta:
        unique_together = [("cod_deb", "medio")]
        ordering = ["cod_deb", "medio"]

    def __str__(self):
        return f"{self.cod_deb} → {self.get_medio_display()}"


class Conciliacion(models.Model):
    BORRADOR, PROCESADA = "BORRADOR", "PROCESADA"
    ESTADOS = [(BORRADOR, "Borrador"), (PROCESADA, "Procesada")]

    estado = models.CharField(max_length=10, choices=ESTADOS, default=BORRADOR)
    parametros = models.JSONField(default=dict, blank=True)
    resumen = models.JSONField(default=dict, blank=True)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    creada_en = models.DateTimeField(auto_now_add=True)
    procesada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "conciliación"
        verbose_name_plural = "conciliaciones"

    @property
    def etiqueta(self) -> str:
        """Nombre visible según el período de abono de sus archivos Transbank: "Conciliación del 03/11/2026" o
        "Conciliación del 01/11/2026 al 05/11/2026". Si otra conciliación tiene el mismo período se agrega la fecha
        de creación para distinguirlas. Usa archivos.all() para aprovechar prefetch_related."""
        dias = sorted({a.fecha_abono for a in self.archivos.all()
                       if a.tipo == ArchivoCargado.TRANSBANK and a.fecha_abono and not a.error})
        if not dias:
            return "Conciliación sin abonos cargados"
        desde, hasta = dias[0], dias[-1]
        nombre = f"Conciliación del {desde:%d/%m/%Y}" + (f" al {hasta:%d/%m/%Y}" if desde != hasta else "")
        if self._periodo_repetido(desde, hasta):
            nombre += f" (creada el {timezone.localtime(self.creada_en):%d/%m %H:%M})"
        return nombre

    def _periodo_repetido(self, desde, hasta) -> bool:
        validos = Q(archivos__tipo=ArchivoCargado.TRANSBANK, archivos__error="", archivos__fecha_abono__isnull=False)
        return (Conciliacion.objects.exclude(pk=self.pk)
                .annotate(p_desde=Min("archivos__fecha_abono", filter=validos),
                          p_hasta=Max("archivos__fecha_abono", filter=validos))
                .filter(p_desde=desde, p_hasta=hasta).exists())

    def __str__(self):
        return self.etiqueta


class ArchivoCargado(models.Model):
    TRANSBANK, BORDERO, CARTOLA, DESCONOCIDO = "transbank", "bordero", "cartola", "desconocido"
    TIPOS = [(TRANSBANK, "Transbank"), (BORDERO, "Bordero"), (CARTOLA, "Cartola"), (DESCONOCIDO, "No reconocido")]

    conciliacion = models.ForeignKey(Conciliacion, related_name="archivos", on_delete=models.CASCADE)
    tipo = models.CharField(max_length=12, choices=TIPOS, default=DESCONOCIDO)
    medio = models.CharField(max_length=10, choices=MEDIO_CHOICES, blank=True)  # vacío: todos los medios
    # Transbank: medio -> {total_ventas, comision, iva_comision, total_abono}. Un archivo puede traer varios medios.
    por_medio = models.JSONField(default=dict, blank=True)
    banco = models.CharField(max_length=40, blank=True)
    archivo = models.FileField(upload_to="cargas/%Y/%m/")
    nombre = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    moneda = models.CharField(max_length=30, blank=True)
    cuenta = models.CharField(max_length=60, blank=True)
    fecha_abono = models.DateField(null=True, blank=True)
    desde = models.DateField(null=True, blank=True)
    hasta = models.DateField(null=True, blank=True)
    filas = models.PositiveIntegerField(default=0)
    total_abono = models.BigIntegerField(null=True, blank=True)
    resumen = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("conciliacion", "sha256")]
        ordering = ["tipo", "medio", "nombre"]

    def __str__(self):
        return self.nombre

    @property
    def etiqueta_medio(self) -> str:
        if self.medio:
            return self.get_medio_display()
        return ", ".join(cat.ETIQUETA_MEDIO[m] for m in cat.MEDIOS if m in self.por_medio)

    @property
    def moneda_extranjera(self) -> bool:
        """Transbank o cartola cuya moneda no es pesos (esta versión concilia solo pesos)."""
        return self.tipo in (self.TRANSBANK, self.CARTOLA) and not clave(self.moneda).startswith("pesos")


class CoberturaBordero(models.Model):
    """Rango de fechas cubierto por un bordero cargado (se conserva aunque se borre la conciliación)."""

    desde = models.DateField()
    hasta = models.DateField()
    archivo = models.ForeignKey(ArchivoCargado, null=True, blank=True, on_delete=models.SET_NULL)


class PagoBordero(models.Model):
    """Pago con tarjeta registrado en el bordero. Único en toda la base (no se duplica entre meses)."""

    hab = models.CharField(max_length=20, blank=True)
    reserva = models.CharField(max_length=30, blank=True)
    cuenta = models.CharField(max_length=30, blank=True)
    cod_deb = models.CharField(max_length=20)
    descripcion = models.CharField(max_length=120, blank=True)
    factura = models.CharField(max_length=30, blank=True)
    valor = models.BigIntegerField()
    documento = models.CharField(max_length=60, blank=True)
    documento_norm = models.CharField(max_length=60, blank=True, db_index=True)
    fecha = models.DateField()
    hora = models.CharField(max_length=10, blank=True)
    usuario = models.CharField(max_length=40, blank=True)
    designacion = models.CharField(max_length=120, blank=True)
    invalido = models.BooleanField(default=False)
    # Borderos que traen este pago (se traslapan entre meses). Al quitar el último, el pago deja de existir.
    archivos = models.ManyToManyField(ArchivoCargado, related_name="pagos", blank=True)
    conciliacion = models.ForeignKey(Conciliacion, null=True, blank=True, related_name="pagos_conciliados",
                                     on_delete=models.SET_NULL)

    class Meta:
        # Identidad sin documento ni valor: son justo los datos que el área responsable de FrontOffice puede corregir.
        constraints = [models.UniqueConstraint(fields=["fecha", "hora", "cuenta", "cod_deb"], name="pago_bordero_unico")]
        ordering = ["fecha", "hora"]

    def __str__(self):
        return f"{self.cod_deb} {self.documento} {self.fecha:%d/%m/%Y}"


class VentaTransbank(models.Model):
    conciliacion = models.ForeignKey(Conciliacion, related_name="ventas", on_delete=models.CASCADE)
    archivo = models.ForeignKey(ArchivoCargado, related_name="ventas", on_delete=models.CASCADE)
    fila = models.PositiveIntegerField(default=0)
    medio = models.CharField(max_length=10, choices=MEDIO_CHOICES)
    es_venta = models.BooleanField(default=True)
    fecha_venta = models.DateField()
    tipo_movimiento = models.CharField(max_length=40, blank=True)
    codigo_comercio = models.CharField(max_length=20, blank=True)
    local = models.CharField(max_length=80, blank=True)
    monto_original = models.BigIntegerField(default=0)
    monto_vuelto = models.BigIntegerField(default=0)
    monto_abono_valido = models.BigIntegerField(default=0)
    comision = models.BigIntegerField(default=0)
    iva_comision = models.BigIntegerField(default=0)
    total_abono = models.BigIntegerField(default=0)
    tipo_venta = models.CharField(max_length=20, blank=True)
    cuota_num = models.PositiveSmallIntegerField(null=True, blank=True)
    cuota_total = models.PositiveSmallIntegerField(null=True, blank=True)
    tarjeta = models.CharField(max_length=30, blank=True)
    codigo_autorizacion = models.CharField(max_length=30, blank=True)
    codigo_norm = models.CharField(max_length=30, blank=True, db_index=True)
    boleta = models.CharField(max_length=30, blank=True)
    # Resultado
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, blank=True)
    pago = models.ForeignKey(PagoBordero, null=True, blank=True, related_name="ventas", on_delete=models.SET_NULL)
    monto_bordero = models.BigIntegerField(null=True, blank=True)
    diferencia = models.BigIntegerField(null=True, blank=True)
    codigo_sugerido = models.CharField(max_length=60, blank=True)
    nota = models.CharField(max_length=200, blank=True)
    mensaje = models.TextField(blank=True)

    class Meta:
        ordering = ["medio", "fecha_venta", "fila"]

    @property
    def tipo(self) -> str:
        return cat.TIPO.get(self.categoria, "")

    @property
    def es_falla(self) -> bool:
        return cat.es_falla(self.categoria)

    @property
    def cuota(self) -> str:
        return f"{self.cuota_num}/{self.cuota_total}" if self.cuota_num else ""

    @property
    def marca_tarjeta(self) -> str:
        """Marca según los primeros dígitos de la tarjeta que informa Transbank ('' si no se reconoce)."""
        return NOMBRE_COD_DEB.get(cod_deb_de_tarjeta(self.tarjeta), "")


class ResultadoAbono(models.Model):
    conciliacion = models.ForeignKey(Conciliacion, related_name="abonos", on_delete=models.CASCADE)
    archivo = models.ForeignKey(ArchivoCargado, related_name="resultados_abono", on_delete=models.CASCADE)
    medio = models.CharField(max_length=10, choices=MEDIO_CHOICES)
    fecha_abono = models.DateField()
    total_abono = models.BigIntegerField()
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES)
    cartola_fecha = models.DateField(null=True, blank=True)
    cartola_descripcion = models.CharField(max_length=200, blank=True)
    cartola_monto = models.BigIntegerField(null=True, blank=True)
    diferencia = models.BigIntegerField(null=True, blank=True)
    mensaje = models.TextField(blank=True)

    class Meta:
        ordering = ["medio", "fecha_abono"]
        constraints = [models.UniqueConstraint(fields=["archivo", "medio"], name="abono_unico_por_archivo_y_medio")]

    @property
    def tipo(self) -> str:
        return cat.TIPO.get(self.categoria, "")


class CorreccionManual(models.Model):
    """Decisión del analista sobre una venta anómala. No edita los archivos originales: al volver a conciliar, el dato
    editado entra al cruce como un pago del bordero y el motor verifica si ahora calza. Si solo se acepta (sin datos),
    la venta queda corregida y el comentario es la evidencia.

    La venta se identifica por sus datos (código, medio, cuota, fecha y monto) y no por su id, porque las ventas se
    borran y se vuelven a crear cada vez que se concilia."""

    conciliacion = models.ForeignKey(Conciliacion, related_name="correcciones", on_delete=models.CASCADE)
    medio = models.CharField(max_length=10, choices=MEDIO_CHOICES)
    codigo_norm = models.CharField(max_length=30, blank=True)
    cuota_num = models.PositiveSmallIntegerField(default=0)
    fecha_venta = models.DateField()
    monto_original = models.BigIntegerField()
    codigo_autorizacion = models.CharField(max_length=30, blank=True)
    local = models.CharField(max_length=80, blank=True)
    # Dato original, copiado al corregir (el archivo del bordero se puede reemplazar después).
    categoria_original = models.CharField(max_length=20, choices=CATEGORIA_CHOICES)
    mensaje_original = models.TextField(blank=True)
    documento_original = models.CharField(max_length=60, blank=True)
    monto_bordero_original = models.BigIntegerField(null=True, blank=True)
    cod_deb_original = models.CharField(max_length=10, blank=True)
    # Dato editado por el analista (vacío si solo acepta).
    documento = models.CharField(max_length=60, blank=True)
    monto = models.BigIntegerField(null=True, blank=True)
    cod_deb = models.CharField(max_length=10, blank=True)
    fecha_bordero = models.DateField(null=True, blank=True)
    aceptada = models.BooleanField(default=False)
    comentario = models.TextField(blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    modificada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha_venta", "codigo_norm"]
        verbose_name = "corrección manual"
        verbose_name_plural = "correcciones manuales"
        constraints = [models.UniqueConstraint(
            fields=["conciliacion", "medio", "codigo_norm", "cuota_num", "fecha_venta", "monto_original"],
            name="una_correccion_por_venta")]

    @property
    def clave(self) -> tuple:
        return self.medio, self.codigo_norm, self.cuota_num, self.fecha_venta, self.monto_original


class MovimientoCartola(models.Model):
    conciliacion = models.ForeignKey(Conciliacion, related_name="movimientos_cartola", on_delete=models.CASCADE)
    fecha = models.DateField()
    descripcion = models.CharField(max_length=200, blank=True)
    canal = models.CharField(max_length=80, blank=True)
    nro_docto = models.CharField(max_length=40, blank=True)
    cargo = models.BigIntegerField(default=0)
    abono = models.BigIntegerField(default=0)
    saldo = models.BigIntegerField(default=0)
    es_transbank = models.BooleanField(default=False)
    conciliado = models.BooleanField(default=False)
    medio_probable = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["fecha"]


class Pendiente(models.Model):
    """Pago con tarjeta del bordero sin abono de Transbank al cierre de una conciliación."""

    pago = models.OneToOneField(PagoBordero, related_name="pendiente", on_delete=models.CASCADE)
    medio = models.CharField(max_length=10, choices=MEDIO_CHOICES)
    origen = models.ForeignKey(Conciliacion, related_name="pendientes", on_delete=models.CASCADE)
    cierre = models.ForeignKey(Conciliacion, null=True, blank=True, related_name="pendientes_cerrados",
                               on_delete=models.SET_NULL)
    abierto = models.BooleanField(default=True)
    mensaje = models.TextField(blank=True)
    revisado = models.BooleanField(default=False)
    observacion = models.TextField(blank=True)

    class Meta:
        ordering = ["pago__fecha", "pago__hora"]
