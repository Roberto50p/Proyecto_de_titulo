import pandas as pd
def identificar_procesar(archivos):
    #los archivos estan guardados en la lista archivos y necesito ahora aplicar la logica por la cual es la siguiente:
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
            "tipo": tipo,
            "archivo": archivo
        })

    return resultados
    #ya tenemos todos los archivos, siguiente codigo los almacena en un diccionario de DF y asi poder tratarlos de manera independiente uno del otro de manera automatica
def crear_dataframes(resultados):
    dataframes = {}
    for resultado in resultados:
        tipo = resultado["tipo"]
        archivo = resultado["archivo"]
        if tipo == "Desconocido":
            continue
        df = pd.read_excel(archivo)
        dataframes[tipo] = df
    # Seleccionar DataFrame de débito
    df_debito = dataframes["Debito"]

    # Mostrar los primeros 10 registros
    #comentario para subir cositas jiji
    print(df_debito.head(10).to_string())
    return dataframes