# Suite de casos de prueba — Visor de Excel

Esta suite reúne archivos representativos con casos límite y variaciones de formato frecuentes en hojas de cálculo.

## Catálogo de casos

| Archivo | Caso límite | Resultado verificado |
| :--- | :--- | :--- |
| `01_excel_metadatos_previos.xlsx` | Títulos/notas antes de los encabezados reales en la fila 4. | Se detecta la fila de encabezados (índice 3) y se devuelven `Codigo`, `Nombre`, `Departamento`, `Presupuesto`. |
| `02_excel_encabezados_duplicados_y_vacios.xlsx` | Encabezados repetidos o vacíos y celdas nulas. | Se normalizan a `Columna_3` y `Cantidad_2`, sin colisiones. |
| `03_excel_tipos_mixtos_y_ceros.xlsx` | Identificadores con ceros a la izquierda y columna de números/textos. | Se conservan `00129482` y `02840`; la columna mixta se identifica y sus valores no se fuerzan a otro tipo. |
| `04_csv_coma_utf8.csv` | CSV separado por comas y texto UTF-8 con acentos. | Se leen las 4 filas y los encabezados acentuados. |
| `05_csv_puntoycoma_latin1.csv` | CSV delimitado por `;`, codificación Latin-1. | Se detectan `latin-1` y `;`; se conservan los caracteres acentuados. |
| `06_csv_tab_utf8_sig.csv` | CSV con tabuladores y BOM UTF-8. | Se detectan `utf-8-sig` y tabulador; se leen 3 columnas. |
| `07_archivo_vacio.csv` / `.xlsx` | Archivo de 0 bytes. | Se rechaza con HTTP 400 y mensaje claro; no se registra una versión. |
| `08_excel_hojas_vacias.xlsx` | Libro con hoja con datos, hoja vacía y hoja solo con encabezados. | Se conservan las hojas; las hojas sin registros presentan un estado vacío. |
| `09_archivo_corrupto.xlsx` | Contenido inválido con extensión `.xlsx`. | Se rechaza con HTTP 400 y mensaje comprensible; no se registra una versión. |
| `10_archivo_grande.csv` | CSV de 35.000 filas y 8 columnas (~2,2 MB). | Se conservan todas las filas y las consultas combinadas de búsqueda, filtro y orden devuelven páginas limitadas desde el servidor. |

## Validación de regresión

La suite funcional se ejecuta con:

```bash
.\.venv\Scripts\python.exe manage.py test -v 1
```

Las pruebas usan la base temporal creada por Django y directorios temporales para originales y cachés; no alteran el historial normal de la aplicación. `tests/ejecutar_pruebas_fase1.py` es una evaluación manual separada de la suite automatizada.
