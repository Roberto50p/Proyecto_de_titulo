"""Mensajes por registro: qué pasó y qué hacer, en lenguaje del analista."""

from datetime import date

from . import categorias as c


def pesos(monto) -> str:
    if monto is None:
        return "-"
    signo = "-" if monto < 0 else ""
    return f"{signo}${abs(int(monto)):,}".replace(",", ".")


def fecha(valor: date | None) -> str:
    return valor.strftime("%d/%m/%Y") if valor else "-"


PLANTILLAS = {
    c.OK: "Venta conciliada con el bordero.",
    c.DIF_MONTO: (
        "El código {codigo} está en el bordero, pero Transbank informa {monto_tbk} y el bordero {monto_bordero} "
        "(diferencia {diferencia}). Revisar el cobro con el detalle de la cuenta en FrontOffice."
    ),
    c.DIGITACION: (
        "El código {codigo} de Transbank no existe en el bordero; el más parecido es {sugerido} "
        "({fecha_bordero}, {monto_bordero}). Corregir el documento en FrontOffice."
    ),
    c.SIN_BORDERO: (
        "Venta Transbank del {fecha_venta} por {monto_tbk} (código {codigo}, {local}) sin registro en el bordero. "
        "Verificar si el pago se ingresó con otro medio o falta registrarlo."
    ),
    c.FUERA_PERIODO: (
        "Venta del {fecha_venta} fuera del período de los borderos cargados. "
        "Cargar el bordero de esa fecha para verificarla."
    ),
    c.CUOTA: (
        "Cuota {cuota} de una venta del {fecha_venta} por {monto_tbk}. "
        "La venta original está fuera de los borderos cargados; se sigue como cuota."
    ),
    c.MEDIO_DISTINTO: (
        "El bordero registró el pago como {cod_deb}, que no corresponde a {medio} según la tabla de equivalencias. "
        "Confirmar el medio de pago."
    ),
    c.SIN_ABONO: (
        "Pago con {cod_deb} del {fecha_bordero} por {monto_bordero} (documento {documento}) sin abono de Transbank "
        "al cierre. Queda pendiente para el próximo mes."
    ),
    c.ABONO_CARTOLA: "{detalle}",
    c.DATO_INVALIDO: "{detalle}",
}


def mensaje(categoria: str, **ctx) -> str:
    return PLANTILLAS[categoria].format(**ctx)
