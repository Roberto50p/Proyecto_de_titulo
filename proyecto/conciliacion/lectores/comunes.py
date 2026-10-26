"""Funciones compartidas por los lectores de archivos."""

import io
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import xlrd

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_FECHA_ES = re.compile(r"(\d{1,2})\s+([a-záéíóú]+)\s+(\d{4})", re.IGNORECASE)


class ArchivoNoReconocido(Exception):
    """El archivo no tiene el formato esperado (o no es un Excel)."""


def es_vacio(valor) -> bool:
    if valor is None:
        return True
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def texto(valor) -> str:
    """Texto limpio de una celda ('' si está vacía)."""
    if es_vacio(valor):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def sin_acentos(valor: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", valor) if unicodedata.category(c) != "Mn")


def clave(valor) -> str:
    """Texto en minúsculas sin acentos ni espacios repetidos, para comparar encabezados."""
    return re.sub(r"\s+", " ", sin_acentos(texto(valor)).lower())


def normalizar_codigo(valor) -> str:
    """Código de autorización / documento comparable: sin espacios, mayúsculas, sin ceros a la izquierda."""
    limpio = re.sub(r"\s+", "", texto(valor)).upper()
    return limpio.lstrip("0")


def parse_fecha_es(valor) -> date:
    """'07 septiembre 2026' -> date(2026, 9, 7)."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    m = _FECHA_ES.search(texto(valor))
    if not m or m.group(2).lower() not in MESES:
        raise ValueError(f"Fecha no reconocida: {valor!r}")
    return date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))


def fechas_es(valor) -> list[date]:
    """Todas las fechas en español presentes en un texto."""
    salida = []
    for d, mes, a in _FECHA_ES.findall(texto(valor)):
        if mes.lower() in MESES:
            salida.append(date(int(a), MESES[mes.lower()], int(d)))
    return salida


def parse_fecha_dmy(valor) -> date:
    """'04/09/2026' o datetime -> date."""
    if isinstance(valor, pd.Timestamp):
        return valor.date()
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return datetime.strptime(texto(valor), "%d/%m/%Y").date()


def a_entero(valor) -> int:
    """Monto a entero CLP (vacío -> 0). Acepta '16.258.428,00' y números."""
    if es_vacio(valor):
        return 0
    if isinstance(valor, (int, float)):
        return int(round(valor))
    limpio = texto(valor).replace("$", "").replace(" ", "")
    if "," in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    elif limpio.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", limpio):
        limpio = limpio.replace(".", "")
    try:
        return int(round(float(limpio)))
    except ValueError:
        return 0


# Registro BOF de Excel 2.x, 3.0 y 4.0 sin contenedor OLE (así exporta FrontOffice el bordero ".XLS").
_BOF_BIFF_ANTIGUO = (b"\x09\x00", b"\x09\x02", b"\x09\x04")


def _celda_xlrd(celda, datemode):
    if celda.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return None
    if celda.ctype == xlrd.XL_CELL_DATE:
        return xlrd.xldate.xldate_as_datetime(celda.value, datemode)
    return celda.value


def _leer_biff_antiguo(contenido: bytes, max_filas: int | None) -> dict[str, pd.DataFrame]:
    """pandas (calamine) no lee Excel 2.x–4.0; xlrd sí. Sin página de códigos se asume Windows-1252."""
    libro = xlrd.open_workbook(file_contents=contenido, logfile=io.StringIO(), encoding_override="cp1252")
    hojas = {}
    for hoja in libro.sheets():
        filas = range(hoja.nrows if max_filas is None else min(hoja.nrows, max_filas))
        hojas[hoja.name] = pd.DataFrame([[_celda_xlrd(c, libro.datemode) for c in hoja.row(i)] for i in filas],
                                        dtype=object)
    return hojas


def leer_libro(archivo, max_filas: int | None = None) -> dict[str, pd.DataFrame]:
    """Todas las hojas sin encabezados y conservando textos. Lanza ArchivoNoReconocido si no es Excel.

    Acepta .xlsx, .xls (Excel 97-2003) y los .XLS de Excel 2.x–4.0 que exporta FrontOffice.
    """
    try:
        if hasattr(archivo, "read"):
            inicio = archivo.read(2)
            archivo.seek(0)
        else:
            with open(archivo, "rb") as f:
                inicio = f.read(2)
        if inicio in _BOF_BIFF_ANTIGUO:
            contenido = archivo.read() if hasattr(archivo, "read") else Path(archivo).read_bytes()
            return _leer_biff_antiguo(contenido, max_filas)
        return pd.read_excel(archivo, header=None, dtype=object, nrows=max_filas, sheet_name=None)
    except Exception as exc:  # pandas y xlrd lanzan distintos errores según el formato
        raise ArchivoNoReconocido("El archivo no es un Excel legible.") from exc
    finally:
        if hasattr(archivo, "seek"):
            archivo.seek(0)


def leer_hoja(archivo, max_filas: int | None = None) -> pd.DataFrame:
    """Primera hoja del libro (ver leer_libro)."""
    return next(iter(leer_libro(archivo, max_filas).values()))


def buscar_celda(hoja: pd.DataFrame, etiqueta: str) -> tuple[int, int] | None:
    """Primera celda cuyo texto (sin acentos, minúsculas) empieza con la etiqueta."""
    objetivo = clave(etiqueta)
    for fila in range(len(hoja)):
        for col in range(hoja.shape[1]):
            if clave(hoja.iat[fila, col]).startswith(objetivo):
                return fila, col
    return None


def valor_a_la_derecha(hoja: pd.DataFrame, fila: int, col: int):
    for c in range(col + 1, hoja.shape[1]):
        if not es_vacio(hoja.iat[fila, c]):
            return hoja.iat[fila, c]
    return None
