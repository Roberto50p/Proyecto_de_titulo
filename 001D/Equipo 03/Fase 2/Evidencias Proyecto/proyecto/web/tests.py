from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .views import clasificar_archivos_dolar


def _f(nombre):
    return SimpleUploadedFile(nombre, b"x")


class ClasificarArchivosDolarTests(TestCase):
    def test_reparte_por_nombre(self):
        nombres = ["ERP_nov.xlsx", "AMEX US$.xls", "Dinners.xls", "visa dolar.xls",
                   "MasterCard.xls", "Cartola.xlsx", "TBK_dolar.xlsx"]
        archivos, problemas = clasificar_archivos_dolar([_f(n) for n in nombres])
        self.assertEqual(problemas, [])
        self.assertEqual({c: f.name for c, f in archivos.items()}, dict(zip(
            ["archivo1", "archivo2", "archivo3", "archivo4", "archivo5", "archivo6", "archivo7"], nombres)))

    def test_desconocido_ambiguo_y_duplicado(self):
        _, problemas = clasificar_archivos_dolar([_f("reporte.xlsx"), _f("visa tbk.xlsx"),
                                                  _f("erp1.xlsx"), _f("erp2.xlsx")])
        self.assertEqual(len(problemas), 3)
        self.assertIn("reporte.xlsx", problemas[0])
        self.assertIn("visa tbk.xlsx", problemas[1])
        self.assertIn("erp2.xlsx", problemas[2])


class ProcesamientoVistaTests(TestCase):
    def test_sin_archivos_avisa_en_vez_de_error_500(self):
        self.client.force_login(User.objects.create_user("u"))
        r = self.client.post(reverse("PR"), {"archivos": [_f("ERP.xlsx")]}, follow=True)
        self.assertContains(r, "Faltan: Amex, Diners, Visa, Mastercard, Transbank.")
