from io import BytesIO

from pypdf import PdfReader

from conciliacion.reportes.pdf import generar

SECCIONES = ["1. Resumen", "2. Matriz de resultados", "3. Débito", "4. Crédito", "Cuotas", "5. Prepago",
             "6. Pendientes", "7. Parámetros"]


def test_pdf_septiembre(septiembre_procesado):
    contenido = generar(septiembre_procesado)
    assert contenido.startswith(b"%PDF")
    lector = PdfReader(BytesIO(contenido))
    texto = "\n".join(p.extract_text() for p in lector.pages)
    assert "HOTELERA SAN FRANCISCO S.A." in texto
    assert "Septiembre 2026" in texto
    posiciones = [texto.index(s) for s in SECCIONES]
    assert posiciones == sorted(posiciones)
    assert f"Página 1 de {len(lector.pages)}" in texto
    assert "F0FUAZ" in texto and "0FOFUAZ" in texto
    assert "5.269.462" in texto


def test_pdf_con_texto_especial_en_observacion(septiembre_procesado):
    from conciliacion.models import Pendiente

    p = Pendiente.objects.first()
    p.observacion = "monto<bordero & revisar"
    p.save()
    texto = "\n".join(pg.extract_text() for pg in PdfReader(BytesIO(generar(septiembre_procesado))).pages)
    assert "monto<bordero & revisar" in texto
