from django.conf import settings
from django.db import models

from .motor import categorias as cat

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]
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

    anio = models.PositiveSmallIntegerField("Año")
    mes = models.PositiveSmallIntegerField()
    estado = models.CharField(max_length=10, choices=ESTADOS, default=BORRADOR)
    parametros = models.JSONField(default=dict, blank=True)
    resumen = models.JSONField(default=dict, blank=True)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    creada_en = models.DateTimeField(auto_now_add=True)
    procesada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("anio", "mes")]
        ordering = ["-anio", "-mes"]
        verbose_name = "conciliación"
        verbose_name_plural = "conciliaciones"

    @property
    def etiqueta(self) -> str:
        return f"{MESES[self.mes - 1]} {self.anio}"

    def __str__(self):
        return self.etiqueta


class ArchivoCargado(models.Model):
    TRANSBANK, BORDERO, CARTOLA, DESCONOCIDO = "transbank", "bordero", "cartola", "desconocido"
    TIPOS = [(TRANSBANK, "Transbank"), (BORDERO, "Bordero"), (CARTOLA, "Cartola"), (DESCONOCIDO, "No reconocido")]

    conciliacion = models.ForeignKey(Conciliacion, related_name="archivos", on_delete=models.CASCADE)
    tipo = models.CharField(max_length=12, choices=TIPOS, default=DESCONOCIDO)
    medio = models.CharField(max_length=10, choices=MEDIO_CHOICES, blank=True)
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
    archivo = models.ForeignKey(ArchivoCargado, null=True, blank=True, related_name="pagos",
                                on_delete=models.SET_NULL)
    conciliacion = models.ForeignKey(Conciliacion, null=True, blank=True, related_name="pagos_conciliados",
                                     on_delete=models.SET_NULL)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["documento_norm", "fecha", "hora", "valor", "cuenta", "cod_deb"], name="pago_bordero_unico")]
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
    revisado = models.BooleanField(default=False)
    observacion = models.TextField(blank=True)

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


class ResultadoAbono(models.Model):
    conciliacion = models.ForeignKey(Conciliacion, related_name="abonos", on_delete=models.CASCADE)
    archivo = models.OneToOneField(ArchivoCargado, related_name="resultado_abono", on_delete=models.CASCADE)
    medio = models.CharField(max_length=10, choices=MEDIO_CHOICES)
    fecha_abono = models.DateField()
    total_abono = models.BigIntegerField()
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES)
    cartola_fecha = models.DateField(null=True, blank=True)
    cartola_descripcion = models.CharField(max_length=200, blank=True)
    cartola_monto = models.BigIntegerField(null=True, blank=True)
    diferencia = models.BigIntegerField(null=True, blank=True)
    mensaje = models.TextField(blank=True)
    revisado = models.BooleanField(default=False)
    observacion = models.TextField(blank=True)

    class Meta:
        ordering = ["medio", "fecha_abono"]

    @property
    def tipo(self) -> str:
        return cat.TIPO.get(self.categoria, "")


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
