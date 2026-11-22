"""Parámetros de la conciliación (editables desde la pantalla Parámetros)."""

from dataclasses import dataclass, field

from ..lectores.comunes import clave
from .categorias import CREDITO, DEBITO, PREPAGO

EQUIVALENCIAS_INICIALES = {
    "RCO": frozenset({DEBITO, PREPAGO}),
    "V$": frozenset({CREDITO}),
    "MC$": frozenset({CREDITO}),
    "AME$": frozenset({CREDITO}),
    "D$": frozenset({CREDITO}),
}

# Nombre de cada Cod. Deb. del bordero, para mostrarlo junto al código.
NOMBRE_COD_DEB = {"V$": "Visa", "MC$": "Mastercard", "AME$": "American Express", "D$": "Diners", "RCO": "Redcompra"}

# Marca según los primeros dígitos de la tarjeta (norma de las marcas; Transbank informa los 6 primeros).
# Los prefijos más largos van primero: 34/37 son Amex y 36/38/30 Diners antes de mirar un solo dígito.
PREFIJOS_MARCA = [("34", "AME$"), ("37", "AME$"), ("30", "D$"), ("36", "D$"), ("38", "D$"), ("4", "V$"),
                  ("5", "MC$")] + [(str(p), "MC$") for p in range(22, 28)]


def cod_deb_de_tarjeta(tarjeta: str) -> str:
    """'4929 13** **** 8005' -> 'V$'. Vacío si la tarjeta no trae dígitos iniciales o la marca no se reconoce."""
    digitos = "".join(c for c in (tarjeta or "").split("*")[0] if c.isdigit())
    return next((cod for prefijo, cod in sorted(PREFIJOS_MARCA, key=lambda p: -len(p[0]))
                 if digitos.startswith(prefijo)), "") if digitos else ""

# Texto en la descripción de la cartola -> medio de pago probable del abono (para abonos sin archivo Transbank).
REGLAS_MEDIO_CARTOLA_INICIALES = (
    ("tc tbk", "Crédito"),
    ("abonos realizados por transbank", "Débito o prepago"),
    ("tarjeta debito", "Débito o prepago"),
)


def leer_reglas_medio(texto: str) -> tuple[tuple[str, str], ...]:
    """'texto = medio' por línea -> ((texto, medio), ...). Lanza ValueError si una línea no tiene ese formato."""
    reglas = []
    for n, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip():
            continue
        patron, igual, medio = linea.partition("=")
        if not igual or not patron.strip() or not medio.strip():
            raise ValueError(f"Línea {n}: usa el formato 'texto de la cartola = medio probable'.")
        reglas.append((patron.strip(), medio.strip()))
    return tuple(reglas)


def escribir_reglas_medio(reglas) -> str:
    return "\n".join(f"{p} = {m}" for p, m in reglas)


@dataclass
class Parametros:
    tolerancia_clp: int = 100
    umbral_similitud: float = 0.75
    dias_holgura: int = 1
    patrones_cartola: tuple[str, ...] = ("transbank", "tbk")
    equivalencias: dict[str, frozenset[str]] = field(default_factory=lambda: dict(EQUIVALENCIAS_INICIALES))
    # Distancia máxima en días entre la venta y su registro en el bordero para el cruce por código.
    ventana_dias: int = 3
    reglas_medio_cartola: tuple[tuple[str, str], ...] = REGLAS_MEDIO_CARTOLA_INICIALES
    # Archivos Transbank o cartolas en otra moneda: False = bloquean la conciliación, True = se omiten con aviso.
    omitir_moneda_extranjera: bool = False

    def medios_de(self, cod_deb: str) -> frozenset[str]:
        return self.equivalencias.get(cod_deb, frozenset())

    def medio_probable(self, descripcion: str) -> str:
        texto = clave(descripcion)
        return next((m for p, m in self.reglas_medio_cartola if clave(p) in texto), "Sin determinar")

    def a_dict(self) -> dict:
        return {
            "tolerancia_clp": self.tolerancia_clp,
            "umbral_similitud": self.umbral_similitud,
            "dias_holgura": self.dias_holgura,
            "patrones_cartola": list(self.patrones_cartola),
            "equivalencias": {k: sorted(v) for k, v in self.equivalencias.items()},
            "ventana_dias": self.ventana_dias,
            "reglas_medio_cartola": [list(r) for r in self.reglas_medio_cartola],
            "omitir_moneda_extranjera": self.omitir_moneda_extranjera,
        }

    @classmethod
    def desde_dict(cls, datos: dict) -> "Parametros":
        base = cls()
        return cls(
            tolerancia_clp=int(datos.get("tolerancia_clp", base.tolerancia_clp)),
            umbral_similitud=float(datos.get("umbral_similitud", base.umbral_similitud)),
            dias_holgura=int(datos.get("dias_holgura", base.dias_holgura)),
            patrones_cartola=tuple(datos.get("patrones_cartola", base.patrones_cartola)),
            equivalencias={k: frozenset(v) for k, v in datos.get("equivalencias", {}).items()}
            or base.equivalencias,
            ventana_dias=int(datos.get("ventana_dias", base.ventana_dias)),
            reglas_medio_cartola=tuple(tuple(r) for r in datos.get("reglas_medio_cartola", base.reglas_medio_cartola)),
            omitir_moneda_extranjera=bool(datos.get("omitir_moneda_extranjera", base.omitir_moneda_extranjera)),
        )
