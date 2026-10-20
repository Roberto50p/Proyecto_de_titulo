
# Proyecto_de_titulo

## Tareas

### 1. Crear nueva interfaz propuesta
**Rama:** `feature/interfaz-reportes`  
**Participantes:** 2 a 3 integrantes

- [ ] Diseñar nueva página principal.
- [ ] Desarrollar página principal en Django.
- [ ] Validar diseño responsivo.
- [ ] Verificar que la interfaz actual de conciliación en dólares siga funcionando.

**Nota:** Por ahora, desarrollar solamente la página principal, debido a que las demás páginas llaman funciones futuras que todavía no hemos implementado.

---

### 2. Avanzar en el proyecto

#### 2.1. Proceso ETL
#### Inicio 18/10       
#### Final 21/10
#### 4 días de trabajo
**Rama:** `feature/etl-clp`  
**Participantes:** 2 integrantes

**Análisis de archivos**
- [x] Analizar estructura del Excel del Hotel.
- [x] Analizar estructura del Excel de Transbank.
- [x] Analizar estructura del Excel del Banco.
- [x] Identificar columnas y datos comunes entre archivos.
- [x] Definir estructura estandarizada para la conciliación.
<!--Con el contexto ya aclarado las tarjetas tranbank (debito, credito, prepago) seguiran las siguientes columnas oara su total:
	ventas:
		Monto original de venta (+)	
		Monto vuelto	
		Tipo de venta/cuota	
		N° de cuota	
		Monto venta válido para abono (+)	
		Comisión Transbank (-)	
		IVA Comisión Transbank (-)	
		Total abono (=)	
	Ventas anuladas:
		Fecha anulación	
		Monto anulado (-)	
		Monto retención anulacion	
		Motivo retención	
		Devolución comisión Transbank por anulación (+)	
		Iva devolución comisión Transbank por anulación (+)					
	Cobros	
		Periodo de cobro	
		Detalle del cobro u observación	
		Monto cobro por servicio (-)	
		IVA cobro por servicio (-)
	Identificador									
		N° de tarjeta	
		Código de autorización de venta	
		Código de autorización de anulación	
		Orden de pedido / orden de compra	
		Número único	
		ID de servicio
	ID transacción (TID)	
	N° de boleta 
    ahora tenemos problemas al encontrar una columna identificadora o asociada con la cartola del banco y el bordero -->

**Extracción de datos**
- [] Crear función para leer Excel del Hotel.
- [x] Crear función para leer Excel de Transbank.
<!--Cree una funcion en views.py (linea 1078) la cual los excel los guarda en una lista y luego los manda al archivo de ETL y ahi hacer la primera normalizacion de nombre del archivo 
sigue una logica la cual aplica con todas las tarjetas transbank-->
- [ ] Crear función para leer Excel del Banco.
- [ ] Validar existencia de columnas obligatorias.

**Transformación y limpieza**
- [ ] Normalizar formatos de fechas.
- [ ] Normalizar montos en pesos chilenos.
- [ ] Normalizar identificadores de transacciones.
- [ ] Detectar valores nulos y registros duplicados.
- [ ] Implementar validaciones de datos incorrectos.
- [ ] Consolidar datos normalizados.

**Pruebas ETL**
- [ ] Probar lectura de los tres Excel.
- [ ] Verificar integridad de los registros procesados.
- [ ] Validar salida del ETL para el motor de conciliación.

---

#### 2.2. Proceso de conciliación
#### Inicio 22/10       
#### Final 26/10
#### 5 días de trabajo
**Rama:** `feature/conciliacion-debito`  
**Participantes:** 3 integrantes

**Análisis y reglas de negocio**
- [ ] Definir llaves de cruce entre archivos.
- [ ] Definir criterios de conciliación de débito.
- [ ] Definir estados de conciliación.
- [ ] Establecer criterios para identificar anomalías.

**Conciliación de débito**
- [ ] Crear función de cruce Hotel vs. Transbank.
- [ ] Crear función de cruce Transbank vs. Banco.
- [ ] Integrar conciliación entre los tres archivos.
- [ ] Identificar transacciones correctamente conciliadas.
- [ ] Detectar diferencias entre montos.
- [ ] Detectar identificadores incorrectos.
- [ ] Detectar transacciones sin coincidencia.
- [ ] Identificar diferencias por fechas de abono.
- [ ] Clasificar anomalías según su causa.

**Pruebas de conciliación**
- [ ] Probar transacciones correctamente conciliadas.
- [ ] Probar diferencias de montos.
- [ ] Probar identificadores incorrectos.
- [ ] Probar registros duplicados.
- [ ] Probar transacciones con diferencias de fechas.
- [ ] Validar resultados de débito con datos reales.

**Extensión a otras tarjetas**
- [ ] Analizar reglas específicas de prepago.
- [ ] Implementar conciliación de prepago.
- [ ] Analizar tratamiento de tarjetas de crédito.
- [ ] Identificar operaciones de crédito en cuotas.
- [ ] Implementar seguimiento de hasta tres cuotas.
- [ ] Detectar cuotas pendientes y diferencias.
- [ ] Probar conciliación de crédito y prepago.

---

#### 2.3. Proceso de reportes
#### Inicio 27/10       
#### Final 28/10
#### 2 días de trabajo
**Rama:** `feature/interfaz-reportes`  
**Participantes:** 2 a 3 integrantes

**Integración con Django**
- [ ] Crear formulario para cargar los tres Excel.
- [ ] Validar formato de archivos cargados.
- [ ] Conectar formulario con el proceso ETL.
- [ ] Conectar ETL con el motor de conciliación.
- [ ] Implementar mensajes de procesamiento y errores.

**Excel de registros conciliados**
- [ ] Definir estructura del Excel de salida.
- [ ] Crear función de exportación a `.xlsx`.
- [ ] Incorporar transacciones conciliadas.
- [ ] Incorporar identificadores y trazabilidad de origen.
- [ ] Validar montos y registros exportados.

**Excel de anomalías**
- [ ] Definir estructura del Excel de anomalías.
- [ ] Crear función de exportación a `.xlsx`.
- [ ] Incorporar registros con diferencias.
- [ ] Incorporar descripción del motivo de anomalía.
- [ ] Diferenciar errores de datos y operaciones pendientes.
- [ ] Validar registros exportados.

**Descarga de resultados**
- [ ] Implementar descarga de Excel conciliado.
- [ ] Implementar descarga de Excel de anomalías.
- [ ] Mostrar resumen de registros procesados.
- [ ] Probar generación y descarga de ambos archivos.

---

### 3. Integración y control de calidad
#### Inicio 29/10       
#### Final 29/10
#### 1 dias de trabajo
**Participantes:** 3 integrantes

**GitHub**
- [ ] Crear rama `feature/etl-clp`.
- [ ] Crear rama `feature/conciliacion-debito`.
- [ ] Crear rama `feature/interfaz-reportes`.
- [ ] Definir estructura de carpetas compartida.
- [ ] Definir contratos de entrada y salida entre módulos.
- [ ] Integrar modificaciones mediante Pull Requests.

**Pruebas integrales**
- [ ] Ejecutar conciliación completa de débito.
- [ ] Comprobar coherencia entre los tres archivos.
- [ ] Verificar generación de ambos Excel.
- [ ] Validar clasificación de anomalías.
- [ ] Comprobar que la conciliación en dólares no presente errores.
- [ ] Ejecutar pruebas con crédito y prepago.
- [ ] Corregir errores identificados.

---

### 4. Entrega de beta
#### Inicio 30/10       
#### Final 30/10
#### 1 dias de trabajo
**Participantes:** 3 integrantes

- [ ] Verificar funcionamiento general de la plataforma.
- [ ] Validar procesamiento de archivos en pesos chilenos.
- [ ] Validar resultados de conciliación con casos conocidos.
- [ ] Preparar documentación técnica.
- [ ] Preparar demostración para el cliente.
- [ ] Entregar primera beta funcional.

**Fecha objetivo:** 31 de octubre de 2026.
**firma por los muchachoides**
