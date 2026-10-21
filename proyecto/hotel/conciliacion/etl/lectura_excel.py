def identificar_procesar(archivos):
    resultados = []
    for archivo in archivos:
        nombre = archivo.name.lower()
        if "debito" in nombre:
            tipo = "Debito"
        elif "credito" in nombre:
            tipo = "Credito"
        elif "prepago" in nombre:
            tipo = "Prepago"
        elif "cartola" in nombre:
            tipo = "Cartola"
        elif "bordero" in nombre:
            tipo = "Bordero"
        else:
            tipo = "Desconocido"

        resultados.append({
            "nombre": archivo.name,
            "tipo": tipo
        })

    return resultados
