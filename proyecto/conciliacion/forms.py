from django import forms
from django.utils import timezone

from .models import MESES, ParametrosSistema


class MesForm(forms.Form):
    mes = forms.TypedChoiceField(label="Mes de abono", coerce=int,
                                 choices=[(i, nombre) for i, nombre in enumerate(MESES, 1)])
    anio = forms.IntegerField(label="Año", min_value=2020, max_value=2100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hoy = timezone.localdate()
        self.fields["mes"].initial = hoy.month
        self.fields["anio"].initial = hoy.year


class ParametrosForm(forms.ModelForm):
    class Meta:
        model = ParametrosSistema
        fields = ["tolerancia_clp", "umbral_similitud", "dias_holgura", "ventana_dias", "patrones_cartola"]
        help_texts = {
            "tolerancia_clp": "Diferencia máxima en pesos para considerar que dos montos son iguales.",
            "umbral_similitud": "Entre 0,5 y 1. Qué tan parecido debe ser un código para sugerir un error de "
                                "digitación (1 = idéntico).",
            "dias_holgura": "Días hábiles que puede tardar un abono en aparecer en la cartola.",
            "ventana_dias": "Días máximos entre la venta en Transbank y su registro en el bordero.",
            "patrones_cartola": "Separados por coma. Una línea de la cartola es un abono Transbank si su "
                                "descripción contiene alguno.",
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


class RevisionForm(forms.Form):
    revisado = forms.BooleanField(required=False)
    observacion = forms.CharField(required=False, widget=forms.Textarea, max_length=1000)
