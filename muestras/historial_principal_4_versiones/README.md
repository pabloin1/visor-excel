# Cuatro versiones para probar el principal y el historial

Sube `v1/padron_historial_principal.xlsx`, luego los archivos de `v2`, `v3` y `v4`, **en ese orden**. Todos tienen el mismo nombre para que el visor los reconozca como versiones del mismo documento. En cada aviso de archivo existente, elige **Guardar como nueva versión** y selecciona **Folio** como columna clave de la hoja **Padron**.

| Tramo | Filas del principal | Agregados | Actualizados | Eliminados |
| --- | ---: | ---: | ---: | ---: |
| v1 inicial | 100 | — | — | — |
| v1 → v2 | 130 | 30 | 10 | 0 |
| v2 → v3 | 80 | 0 | 8 | 50 |
| v3 → v4 | 110 | 30 | 12 | 0 |

Después de subir `v4`, abre su versión **Principal**. En **Datos** deben aparecer 110 filas: los folios `AP-0051` a `AP-0160`. Los 50 folios `AP-0001` a `AP-0050` ya no forman parte del principal. En **Cambios** deben aparecer los tres tramos de la tabla, cada uno con sus totales y sus registros. Sumados a lo largo del historial hay **60 agregados, 30 actualizados y 50 eliminados**; estos son eventos entre versiones, no filas adicionales del principal.

Los cambios de valores se hicieron en `Monto` y `Estado`: 10 folios en v2 (`AP-0051` a `AP-0060`), 8 en v3 (`AP-0061` a `AP-0068`) y 12 en v4 (`AP-0071` a `AP-0082`). Los valores editados se conservan en las versiones posteriores.

Para regenerar los libros, ejecuta desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe muestras\generar_cuatro_versiones.py
```

Si el documento de prueba ya existe en el visor, elimina sus versiones desde la más reciente hacia la primera antes de comenzar otra prueba completa.
