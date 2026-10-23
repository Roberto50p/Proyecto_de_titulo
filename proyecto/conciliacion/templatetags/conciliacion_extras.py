from django import template

from ..motor import categorias as cat
from ..motor.mensajes import pesos as _pesos

register = template.Library()


@register.filter
def pesos(valor):
    if valor is None or valor == "":
        return "-"
    return _pesos(valor)


@register.filter
def miles(valor):
    return f"{int(valor or 0):,}".replace(",", ".")


@register.filter
def medio(codigo):
    return cat.ETIQUETA_MEDIO.get(codigo, codigo)


@register.filter
def categoria(codigo):
    return cat.ETIQUETA.get(codigo, codigo)


@register.filter
def tipo_de(codigo):
    return cat.TIPO.get(codigo, "")


@register.filter
def get(diccionario, clave):
    return (diccionario or {}).get(clave)
