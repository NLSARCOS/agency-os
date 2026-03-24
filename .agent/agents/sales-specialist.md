Plan de ejecución detallado para **[TEST] Tarea de prueba**:

## Objetivo operativo
Crear en el workspace un archivo `test_mission_result.txt` con el contenido exacto:

```txt
OK - mission test
```

y confirmar la ruta final del archivo generado.

## Alcance
### Dentro del alcance
1. Crear el archivo en `/home/nelson/.openclaw/workspace/`
2. Escribir el contenido exacto requerido
3. Verificar que el archivo exista
4. Verificar que el contenido sea correcto
5. Reportar la ruta final

### Fuera del alcance
- Integraciones externas
- Lógica adicional
- Formato enriquecido
- Archivos adicionales

## Plan paso a paso

### 1. Preparación
- Confirmar que el workspace objetivo es `/home/nelson/.openclaw/workspace`
- Validar que existe permiso de escritura en esa ruta

### 2. Creación del archivo
- Crear el archivo:
`/home/nelson/.openclaw/workspace/test_mission_result.txt`
- Escribir exactamente:
`OK - mission test`

### 3. Verificación
- Comprobar que el archivo existe
- Leer el archivo para validar que el contenido coincida exactamente
- Confirmar que no haya texto extra ni salto inesperado problemático

### 4. Entrega
- Reportar como resultado final:
- ruta absoluta del archivo
- estado de creación
- validación de contenido

## Criterio de éxito
La misión se considera completada solo si:
- existe `test_mission_result.txt` en el workspace
- contiene exactamente `OK - mission test`
- se reporta la ruta final absoluta

## Riesgos / notas
- Riesgo bajo
- Tarea directa, sin dependencias externas
- Se puede ejecutar en una sola operación y validar inmediatamente