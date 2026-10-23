"""Medios de pago y categorías de resultado, con sus etiquetas, tipos y colores."""

DEBITO, CREDITO, PREPAGO = "DEBITO", "CREDITO", "PREPAGO"
MEDIOS = [DEBITO, CREDITO, PREPAGO]
ETIQUETA_MEDIO = {DEBITO: "Débito", CREDITO: "Crédito", PREPAGO: "Prepago"}
COLOR_MEDIO = {DEBITO: "#1F5FA8", CREDITO: "#B7791F", PREPAGO: "#2F7D4F"}
FONDO_MEDIO = {DEBITO: "#E8F0FA", CREDITO: "#FBF2E3", PREPAGO: "#E7F4EC"}

OK = "OK"
DIF_MONTO = "DIF_MONTO"
DIGITACION = "DIGITACION"
SIN_BORDERO = "SIN_BORDERO"
FUERA_PERIODO = "FUERA_PERIODO"
CUOTA = "CUOTA"
MEDIO_DISTINTO = "MEDIO_DISTINTO"
SIN_ABONO = "SIN_ABONO"
ABONO_CARTOLA = "ABONO_CARTOLA"
DATO_INVALIDO = "DATO_INVALIDO"

ETIQUETA = {
    OK: "Conciliado",
    DIF_MONTO: "Diferencia de monto",
    DIGITACION: "Error de digitación",
    SIN_BORDERO: "Venta Transbank sin registro en bordero",
    FUERA_PERIODO: "Fuera del período del bordero",
    CUOTA: "Cuota en seguimiento",
    MEDIO_DISTINTO: "Medio de pago distinto",
    SIN_ABONO: "Pago en bordero aún no abonado",
    ABONO_CARTOLA: "Abono no encontrado en cartola",
    DATO_INVALIDO: "Dato inválido",
}

OPERACION, DATO, AVISO, PENDIENTE = "Operación", "Dato", "Aviso", "Pendiente"
TIPO = {
    OK: "OK",
    DIF_MONTO: OPERACION,
    DIGITACION: DATO,
    SIN_BORDERO: OPERACION,
    FUERA_PERIODO: AVISO,
    CUOTA: AVISO,
    MEDIO_DISTINTO: AVISO,
    SIN_ABONO: PENDIENTE,
    ABONO_CARTOLA: OPERACION,
    DATO_INVALIDO: DATO,
}
# Menor número = más grave (para ordenar listados).
GRAVEDAD = {OPERACION: 1, DATO: 2, PENDIENTE: 3, AVISO: 4, "OK": 5}

# Orden de las filas de la matriz y de los listados.
ORDEN_CATEGORIAS = [DIF_MONTO, SIN_BORDERO, ABONO_CARTOLA, DIGITACION, DATO_INVALIDO,
                    SIN_ABONO, MEDIO_DISTINTO, CUOTA, FUERA_PERIODO, OK]
CATEGORIAS_FALLA = {c for c, t in TIPO.items() if t in (OPERACION, DATO)}


def es_falla(categoria: str) -> bool:
    return categoria in CATEGORIAS_FALLA
