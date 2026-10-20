def identificar_procesar(archivos):
    resultados = []
    for archivo in archivos:
        nombre = archivo.name.lower()
        if "debito" in nombre:
            tipo = "Débito"
        elif "credito" in nombre:
            tipo = "Crédito"
        elif "prepago" in nombre:
            tipo = "Prepago"
        else:
            tipo = "Desconocido"

        resultados.append({
            "nombre": archivo.name,
            "tipo": tipo
        })

    return resultados