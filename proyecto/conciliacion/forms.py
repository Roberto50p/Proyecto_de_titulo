from django import forms

from .models import ParametrosSistema
from .motor import categorias as cat
from .motor.parametros import NOMBRE_COD_DEB, leer_reglas_medio


class ParametrosForm(forms.ModelForm):
    class Meta:
        model = ParametrosSistema
        fields = ["tolerancia_clp", "umbral_similitud", "dias_holgura", "ventana_dias", "patrones_cartola",
                  "reglas_medio_cartola", "omitir_moneda_extranjera"]
        widgets = {"reglas_medio_cartola": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "tolerancia_clp": "Diferencia máxima en pesos para considerar que dos montos son iguales.",
            "umbral_similitud": "Entre 0,5 y 1. Qué tan parecido debe ser un código para sugerir un error de "
                                "digitación (1 = idéntico).",
            "dias_holgura": "Días hábiles que puede tardar un abono en aparecer en la cartola.",
            "ventana_dias": "Días máximos entre la venta en Transbank y su registro en el bordero.",
            "patrones_cartola": "Separados por coma. Una línea de la cartola es un abono Transbank si su "
                                "descripción contiene alguno.",
            "reglas_medio_cartola": "Una regla por línea: 'texto de la cartola = medio probable'. Se usa para "
                                    "orientar los abonos que llegaron al banco sin archivo Transbank; gana la "
                                    "primera que calce.",
            "omitir_moneda_extranjera": "Si está marcado, los archivos Transbank o cartolas en dólares se dejan "
                                        "fuera con un aviso; si no, bloquean la conciliación hasta quitarlos.",
        }

    def clean_umbral_similitud(self):
        valor = self.cleaned_data["umbral_similitud"]
        if not 0.5 <= valor <= 1:
            raise forms.ValidationError("Debe estar entre 0,5 y 1.")
        return valor

    def clean_patrones_cartola(self):
        valor = self.cleaned_data["patrones_cartola"]
        if not [p for p in valor.split(",") if p.strip()]:
            raise forms.ValidationError("Indica al menos un texto.")
        return valor

    def clean_reglas_medio_cartola(self):
        valor = self.cleaned_data["reglas_medio_cartola"]
        try:
            leer_reglas_medio(valor)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return valor


class CorreccionForm(forms.Form):
    """Recuadro de corrección de una venta anómala. Con datos, el motor los verifica al volver a conciliar; sin
    datos ("aceptar"), el comentario es obligatorio porque es la única evidencia de la decisión.

    Cada categoría edita solo lo que está mal; el resto se toma del bordero (los valores iniciales) sin mostrarse,
    y el servidor ignora lo que llegue para un campo que no corresponde. Nada de esto modifica el bordero: se guarda
    en el sistema como la decisión del analista. La fecha nunca se edita: es la del pago o, si no hay, la de la venta."""

    DATOS = ("documento", "monto", "cod_deb", "fecha_bordero")
    EDITABLES = {
        cat.SIN_BORDERO: ("documento", "monto", "cod_deb"),  # falta el registro entero
        cat.DIGITACION: ("documento",),
        cat.DIF_MONTO: ("monto",),
    }

    documento = forms.CharField(label="Documento", required=False, max_length=60)
    monto = forms.IntegerField(label="Monto", required=False, min_value=1)
    cod_deb = forms.ChoiceField(label="Cod. Deb.", required=False)
    fecha_bordero = forms.DateField(label="Fecha en el bordero", required=False,
                                    widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    aceptada = forms.BooleanField(label="Aceptar sin corregir datos", required=False)
    comentario = forms.CharField(label="Comentario", required=False, max_length=1000,
                                 widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, categoria: str, medio: str, cod_debs, **kwargs):
        super().__init__(*args, **kwargs)
        self.categoria = categoria
        for campo in set(self.DATOS) - set(self.EDITABLES.get(categoria, ())):
            del self.fields[campo]
        if not self.puede_aceptar or self.solo_aceptar:
            del self.fields["aceptada"]
        if "cod_deb" in self.fields:  # solo los códigos del medio de la venta: en crédito no aparece RCO
            del_medio = sorted(k for k, medios in cod_debs.items() if medio in medios)
            self.fields["cod_deb"].choices = [("", "—")] * (len(del_medio) != 1) + [
                (k, f"{k} · {NOMBRE_COD_DEB[k]}" if k in NOMBRE_COD_DEB else k) for k in del_medio]

    @property
    def solo_aceptar(self) -> bool:
        return self.categoria in cat.SOLO_ACEPTAR

    @property
    def puede_aceptar(self) -> bool:
        return self.solo_aceptar or self.categoria == cat.DIF_MONTO

    @property
    def comentario_obligatorio(self) -> bool:
        """Sin registro en bordero: el recuadro llega prellenado con lo de Transbank y siempre calza al volver a
        conciliar, así que la evidencia es el comentario (dónde se verificó el pago)."""
        return self.solo_aceptar or self.categoria == cat.SIN_BORDERO

    def clean(self):
        datos = super().clean()
        datos["aceptada"] = self.solo_aceptar or (self.puede_aceptar and datos.get("aceptada", False))
        if datos["aceptada"]:
            if not datos.get("comentario", "").strip():
                self.add_error("comentario", "Escribe qué decidiste: es obligatorio al aceptar sin corregir datos.")
            datos.update(documento="", monto=None, cod_deb="", fecha_bordero=None)
            return datos
        if self.comentario_obligatorio and not datos.get("comentario", "").strip():
            self.add_error("comentario", "Escribe dónde verificaste el pago (voucher, cuenta del huésped, recepción).")
        datos.update({k: self.initial.get(k) for k in self.DATOS if k not in self.fields})  # lo que ya está bien
        for campo in ("documento", "monto", "cod_deb"):
            if datos.get(campo) in (None, ""):
                self.add_error(campo if campo in self.fields else None, f"Falta {campo.replace('_', '. ')}.")
        return datos


class FiltroDatosForm(forms.Form):
    """Rango de fechas de las conciliaciones a exportar y limpiar (ambos extremos opcionales e inclusivos)."""

    # <input type="date"> solo acepta AAAA-MM-DD (el formato local es-cl no lo muestra).
    desde = forms.DateField(label="Desde", required=False,
                            widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(label="Hasta (fecha tope)", required=False,
                            widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha desde no puede ser posterior a la fecha tope.")
        return datos
