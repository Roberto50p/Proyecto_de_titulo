# Backlog de correcciones y cierre del proyecto

**Hotel Plaza San Francisco**  
**Periodo:** 14 al 18 de noviembre de 2026

---

## 1. Análisis y comprensión de la base de datos

**Fecha límite:** Sábado 14 de noviembre  
**Prioridad:** Crítica  
**Complejidad:** Alta

### Descripción

Actualmente no tenemos claridad sobre como está la organización del la base de datos, qué tablas ni qué manera se almacena los registros generados despues de una conciliación. Es necesario comprender su forma para asi evitar modificaciones que afecten otras funcionalidas, tienes que trabajal.

### Tareas

- [ ] Identificar todas las tablas y sus relaciones.
- [ ] Revisar qué información se almacena al finalizar una conciliación.
- [ ] Identificar cómo se relacionan las transacciones con sus estados y anomalías.
- [ ] Investigar cómo funciona el almacenamiento de las revisiones y observaciones.
- [ ] Identificar qué funciones del sistema consultan o modifican cada tabla.
- [ ] Crear un respaldo de la base de datos antes de realizar cambios.

### Criterio de finalización

La persona comprende la estructura de la base de datos y puede identificar dónde se almacenan y modifican los registros.

---

## 2. Análisis de registros y definición de pendientes

**Fecha límite:** Domingo 15 de noviembre  
**Prioridad:** Crítica  
**Complejidad:** Muy alta

### Descripción

Al finalizar una conciliación, el sistema genera una tabla de registros cuyo propósito y contenido no están completamente claros, No se entiende si son casos normales o anomalos. Además, existe una columna llamada Pendientes, pero desconocemos qué condiciones determinan que un registro pertenezca a esa categoría. Debemos revisar la lógica actual y decidir si los Pendientes es algo que agrega valor o no

### Tareas

- [ ] Determinar qué representa cada fila de la tabla generada después de una conciliación.
- [ ] Identificar el origen de los registros mostrados y sus relaciones con los archivos procesados.
- [ ] Analizar qué condiciones hacen que un registro sea considerado pendiente.
- [ ] Revisar qué información muestra actualmente el botón Pendientes.
- [ ] Determinar si los pendientes corresponden a anomalías, registros sin conciliar u operaciones por revisar.
- [ ] Definir qué acciones podrán realizar los analistas sobre los registros pendientes.
- [ ] Documentar los estados oficiales y sus reglas de transición.

### Criterio de finalización

El equipo entiende que chotas es eso y decidio qué hacer con esos pendientes

---

## 3. Restauración de compatibilidad con archivos de BancoEstado

**Fecha límite:** Domingo 15 de noviembre  
**Prioridad:** Alta  
**Complejidad:** Media-alta

### Descripción

Anteriormente el proyecto permitía procesar cartolas bancarias de BancoEstado, pero actualmente esta funcionalidad dejó de operar correctamente debido a los cambios realizados en el sistema.

Necesitamos revisar la función encargada de identificar y procesar los archivos bancarios para comprender qué modificación provocó este problema y recuperar la compatibilidad con BancoEstado.

La corrección no debe afectar el procesamiento de los archivos del banco que actualmente funciona.

### Tareas

- [ ] Localizar la función encargada de identificar y procesar las cartolas bancarias.
- [ ] Revisar cómo funcionaba anteriormente la lectura de archivos de BancoEstado.
- [ ] Comparar las columnas y estructuras entre BancoEstado y el banco actualmente compatible.
- [ ] Identificar qué cambio provocó que BancoEstado dejara de funcionar.
- [ ] Corregir la función para que permita procesar ambos formatos bancarios.
- [ ] Verificar que la identificación y normalización de las cartolas sea correcta.
- [ ] Realizar pruebas utilizando archivos reales de BancoEstado.
- [ ] Comprobar que los archivos del banco original continúen funcionando correctamente.

### Criterio de finalización

La wea funca con BancoEstado y con el otro banco sin romper nada.

---

## 4. Corrección de la funcionalidad Reemplazar

**Fecha límite:** Lunes 16 de noviembre  
**Prioridad:** Alta  
**Complejidad:** Alta

### Descripción

Actualmente, al utilizar el botón Reemplazar sobre un archivo específico, el sistema modifica todos los archivos en lugar de únicamente el seleccionado. Esta wea es tonta y estupida, Cómo un archivo va a tener bigote, pido maximo esfuerzo de modificación.

### Tareas

- [ ] Localizar la función asociada al botón Reemplazar.
- [ ] Revisar cómo se identifica el registro seleccionado.
- [ ] Identificar por qué la actualización afecta a múltiples registros.
- [ ] Corregir la lógica para modificar exclusivamente el registro indicado.
- [ ] Comprobar que los registros restantes mantengan sus valores originales.
- [ ] Realizar pruebas con registros repetidos y distintos identificadores.

### Criterio de finalización

La wea funca

---

## 5. Corrección de las inconsistencias del resumen de conciliación

**Fecha límite:** Lunes 16 de noviembre  
**Prioridad:** Alta  
**Complejidad:** Alta

### Descripción

Después de procesar una conciliación, el resumen indica que existen cinco registros de crédito. Sin embargo, al seleccionar dicha categoría se muestran muchos más registros. Actualmente desconocemos si el contador representa anomalías, pendientes, registros conciliados u otra clasificación. Debemos investigar el origen de esta diferencia y asegurar que las cifras del resumen sean consistentes con la información mostrada en las tablas.

### Tareas

- [ ] Identificar de dónde se obtiene el contador de registros de crédito.
- [ ] Determinar qué tipo de registros está contabilizando el resumen.
- [ ] Revisar las consultas y filtros aplicados al seleccionar Crédito.
- [ ] Comparar los criterios utilizados por el resumen y la tabla detallada.
- [ ] Corregir las diferencias entre ambos resultados.
- [ ] Comprobar que los contadores de débito y prepago funcionen correctamente.
- [ ] Verificar que los totales correspondan a los registros reales de la base de datos.

### Criterio de finalización

Los totales del resumen coinciden con los registros que muestran sus respectivos filtros y categorías.

---

## 6. Revisión de campos de observación y guardado

**Fecha límite:** Martes 17 de noviembre  
**Prioridad:** Media  
**Complejidad:** Media

### Descripción

En la tabla de registros existe una columna de revisión que contiene un campo para escribir, una casilla Revisado y un botón Guardar. Actualmente no comprendemos qué función cumple cada elemento ni qué información se modifica cuando el usuario interactúa con ellos. Debemos investigar su comportamiento y determinar si realmente aportan al proceso de revisión de los analistas.

### Tareas

- [ ] Investigar qué información recibe el campo de texto de revisión.
- [ ] Identificar la función de la casilla Revisado.
- [ ] Determinar qué operación ejecuta el botón Guardar.
- [ ] Revisar en qué tabla y columnas se almacena la información.
- [ ] Definir el comportamiento esperado de cada control.
- [ ] Corregir funcionalidades que no cumplan su propósito.
- [ ] Eliminar o deshabilitar controles innecesarios, si corresponde.
- [ ] Comprobar que la información guardada persista correctamente.

### Criterio de finalización

Los controles de revisión tienen una función definida, comprensible y verificable en la base de datos.

---

## 7. Implementación oficial del rol Administrador

**Fecha límite:** Martes 17 de noviembre  
**Prioridad:** Alta  
**Complejidad:** Alta

### Descripción

El sistema será utilizado principalmente por dos analistas que, durante esta etapa, Usaran el rol de Administrador, se requiere formalizar el rol Administrador con para decidir si eliminar los registros, o limpiar la BD del sistema.

### Tareas

- [ ] Definir los permisos del rol Administrador y del rol Analista.
- [ ] Configurar los roles y restringir las funciones administrativas.
- [ ] Habilitar la eliminación de registros individuales para administradores.
- [ ] Crear un botón de limpieza de la base de datos.
- [ ] Agregar confirmación obligatoria y respaldo previo a las operaciones destructivas.
- [ ] Definir qué tablas pueden limpiarse sin afectar usuarios ni configuración.
- [ ] Crear una interfaz administrativa diferenciada.
- [ ] Comprobar que el rol Analista no pueda ejecutar acciones administrativas, incluso mediante solicitudes directas.

### Criterio de finalización

tiene que trabajal

---

## 8. Pruebas integrales y estabilización

**Fecha límite:** Miércoles 18 de noviembre  
**Prioridad:** Alta  
**Complejidad:** Media

### Descripción

Una vez finalizadas las correcciones, debemos comprobar que las modificaciones no hayan afectado el funcionamiento general del sistema. Se ejecutarán pruebas completas de conciliación y se verificarán las funciones de consulta, revisión, reemplazo, pendientes y administración. Esta etapa permitirá identificar errores críticos antes del cierre del proyecto.

### Tareas

- [ ] Ejecutar una conciliación completa con archivos de prueba.
- [ ] Validar que los registros se almacenen correctamente.
- [ ] Comprobar las cantidades mostradas en los resúmenes.
- [ ] Probar los filtros de débito, crédito y prepago.
- [ ] Verificar la funcionalidad Reemplazar.
- [ ] Comprobar la revisión y el guardado de observaciones.
- [ ] Validar el funcionamiento de la sección Pendientes.
- [ ] Probar el procesamiento de cartolas de BancoEstado.
- [ ] Comprobar que el procesamiento del banco original continúe funcionando.
- [ ] Probar permisos administrativos y eliminación en una base de datos de pruebas.
- [ ] Corregir los errores críticos detectados.
- [ ] Preparar una versión estable para la entrega.

### Criterio de finalización

Las funcionalidades críticas operan correctamente y la versión se encuentra lista para su presentación.