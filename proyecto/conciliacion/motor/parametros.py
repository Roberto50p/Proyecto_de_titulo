"""Parámetros de la conciliación (editables desde la pantalla Parámetros)."""

from dataclasses import dataclass, field

from .categorias import CREDITO, DEBITO, PREPAGO

EQUIVALENCIAS_INICIALES = {
    "RCO": frozenset({DEBITO, PREPAGO}),
    "V$": frozenset({CREDITO}),
    "MC$": frozenset({CREDITO}),
    "AME$": frozenset({CREDITO}),
    "D$": frozenset({CREDITO}),
}


@dataclass
class Parametros:
    tolerancia_clp: int = 100
    umbral_similitud: float = 0.75
    dias_holgura: int = 1
    patrones_cartola: tuple[str, ...] = ("transbank", "tbk")
    equivalencias: dict[str, frozenset[str]] = field(default_factory=lambda: dict(EQUIVALENCIAS_INICIALES))
    # Distancia máxima en días entre la venta y su registro en el bordero para el cruce por código.
    ventana_dias: int = 3

    def medios_de(self, cod_deb: str) -> frozenset[str]:
        return self.equivalencias.get(cod_deb, frozenset())

    def a_dict(self) -> dict:
        return {
            "tolerancia_clp": self.tolerancia_clp,
            "umbral_similitud": self.umbral_similitud,
            "dias_holgura": self.dias_holgura,
            "patrones_cartola": list(self.patrones_cartola),
            "equivalencias": {k: sorted(v) for k, v in self.equivalencias.items()},
            "ventana_dias": self.ventana_dias,
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
        )
