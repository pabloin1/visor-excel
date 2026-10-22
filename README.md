# Visor de Excel

Para una demo de 30 días en Render, consulta [DEPLOY-RENDER.md](DEPLOY-RENDER.md).

Herramienta personal para cargar archivos Excel, explorar sus datos en un resumen visual y consultar una biblioteca de documentos con versiones.
En local, el proyecto usa Django, plantillas Django y SQLite. Los originales se guardan en `data/uploads/`. La demo de Render usa PostgreSQL para conservar también los originales entre reinicios.
La interfaz usa vistas y formularios de Django: cada búsqueda, filtro, cambio de hoja y consulta del historial se resuelve en el servidor. Los formularios de carga y eliminación usan CSRF y siguen el patrón POST/redirect/GET. La API JSON sigue disponible para compatibilidad. Un script estático pequeño habilita arrastrar Excel sobre las tarjetas; el botón y todo el proceso de carga funcionan sin JavaScript ni solicitudes `fetch`. Las bases SQLite individuales de `data/cache/` son índices derivados para consultar hojas grandes; se reconstruyen desde los originales y no sustituyen la base de Django.

La presentación conserva Tailwind CSS 4 y estilos propios. Las fuentes CSS están en `assets/`; `build_css.py` genera `documents/static/documents/app.generated.css`. Las plantillas están en `documents/templates/documents/` y los recursos estáticos en `documents/static/documents/`, siguiendo la organización por aplicación de Django. No se usa Node.js ni npm: el script de Python descarga y ejecuta el compilador independiente oficial de Tailwind cuando se necesita recompilar. El CSS generado está incluido y ejecutar la aplicación no requiere una compilación.

La pantalla inicial muestra una tarjeta por documento, con búsqueda por nombre del documento o de cualquiera de sus archivos de versión, orden por actualización, nombre o cantidad de registros, y páginas de 10 tarjetas. Cada tarjeta muestra la versión vigente, su nombre de archivo original y una vista previa de las tres versiones más recientes; **Ver historial completo** abre el resto en páginas de 10 versiones. **Agregar versión** permite elegir un Excel para esa tarjeta aunque su nombre o columnas hayan cambiado. También se puede arrastrar un Excel sobre la tarjeta; el indicador visual muestra el destino y continúa en el formulario Django de comparación. El botón permite hacer lo mismo sin arrastrar. Desde el visor, **Volver a la biblioteca** regresa al listado.

Al cargar un Excel desde el botón general, si su nombre no coincide con ningún documento y ya hay documentos en la biblioteca, se pide elegir uno de una lista buscable y paginada o guardarlo como documento independiente. La asociación se basa en la elección explícita del usuario. Si el nombre coincide, se muestra la comparación de estructura y se puede confirmar ese documento, elegir otro o crear uno nuevo. Antes de guardar una versión se eligen las columnas clave compartidas para comparar registros. El nombre original de cada versión permanece visible en el historial.

La vista **Resumen** presenta primero un panorama del libro: número de hojas, filas sumadas entre hojas, hojas vacías y observaciones de estructura. Después muestra la hoja elegida, su gráfico y perfiles por columna: números válidos y omitidos, categorías frecuentes y rango de fechas. Las sumas entre hojas no deduplican entidades. Los folios, claves e identificadores no se eligen automáticamente como categoría o medida, y no se les calculan sumas en el perfil. El recuento siempre cuenta filas; los promedios de «Otros» ponderan los registros de cada grupo. La vista **Datos** permite buscar, filtrar, ordenar y paginar la tabla. La tabla muestra 25 registros por página; el gráfico y el desglose de «Otros» muestran 10 categorías por página. **Cambios** muestra ocho comparaciones entre versiones por página y 20 registros por página dentro de cada comparación. Los enlaces conservan la selección y los filtros de la vista.

## Importación y análisis

- La interfaz admite archivos `.xlsx` y `.xls` de hasta 50 MB. El original se conserva en el historial. La API conserva la importación CSV existente por compatibilidad.
- En Excel se intenta detectar la fila de encabezados. Los encabezados vacíos o repetidos se normalizan.
- Los identificadores de texto con ceros a la izquierda se conservan. La inferencia de tipos es aproximada y no cambia los valores originales.
- Las columnas mixtas se identifican en el resumen. Puedes agrupar por sus valores originales o analizarlas como medida; en este último caso solo se usan los valores que ya son numéricos y se informa cuántos textos o nulos se omitieron. No se convierten textos automáticamente.
- Al cargar un archivo con un nombre ya existente, el diálogo compara hojas, columnas, orden y tipos estimados. La detección de renombres es solo una sugerencia.
- Las hojas vacías y las búsquedas sin coincidencias tienen mensajes distintos. La tabla pagina y filtra desde el servidor.
- Al guardar una nueva versión, selecciona una o más columnas clave por hoja. La combinación debe identificar una sola fila; si hay claves repetidas, la versión no se guarda hasta corregir la selección.
- La pestaña **Cambios** compara la versión nueva con la anterior y muestra filas agregadas, actualizadas y eliminadas, junto con los cambios de hojas y columnas. Las altas o bajas de columnas se informan como cambios de estructura y no se cuentan artificialmente como filas actualizadas.
- La versión más reciente de cada documento se marca como **Principal** y es el snapshot vigente dentro del visor. Al actualizarlo se usa el contenido de la nueva versión: filas ausentes se consideran eliminadas y no se conservan en el principal. Los originales anteriores siguen disponibles en el historial.
- Si una hoja no tiene columnas en común entre versiones, sus filas se reportan como eliminadas y agregadas; no es posible identificar actualizaciones en esa hoja.

## Pruebas

```powershell
.\.venv\Scripts\python.exe manage.py test -v 1
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

## Ejecutar
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```
Abre http://127.0.0.1:8000

Para aplicar cambios de estilo, ejecuta `.\.venv\Scripts\python.exe build_css.py`. La primera compilación descarga el ejecutable independiente oficial de Tailwind 4.3.3 a `.cache/` y comprueba su SHA-256; las siguientes usan la copia local. El CSS generado ya está incluido en el proyecto, por lo que ejecutar la aplicación no requiere descarga ni compilación.

### Historial anterior

Si ya tenías datos en `data/history.db`, conserva esa base y `data/uploads/`. Después de `migrate`, ejecuta una vez:

```powershell
.\.venv\Scripts\python.exe manage.py import_legacy_history
```

El comando comprueba los archivos originales y sus hashes, importa documentos y versiones con sus mismos identificadores y deja intacta la base anterior. Si se ejecuta de nuevo sobre una importación idéntica, solo informa que ya está hecha. La base activa de Django es `data/django.db`; las cachés de consulta siguen en `data/cache/`. En esta migración local se creó el respaldo `data/backup-before-django-2026-10-16/` antes de importar.

### Datos y recuperación

Django administra los metadatos de documentos y versiones mediante sus modelos y migraciones. Las bases SQLite en `data/cache/` son derivadas y se reconstruyen a partir de los originales. Para respaldar o restaurar el historial, conserva **juntos** `data/django.db` y `data/uploads/`; verifica los hashes de los originales. Antes de la integración del servicio con Django se guardó una copia en `data/backup-before-django-integration-2026-10-19/`.

La carga publica el original y la caché tras prepararlos en archivos temporales. Si un borrado termina en la base pero el sistema no permite retirar un archivo, la API responde con `cleanup_pending: true`. Para listar archivos derivados u originales huérfanos:

```powershell
.\.venv\Scripts\python.exe manage.py reconcile_storage
```

Para limpiar solamente candidatos con más de 24 horas, revisa primero el listado y ejecuta `reconcile_storage --delete`. El comando comprueba el hash del original antes de borrarlo y también detecta carpetas temporales de cargas interrumpidas y archivos pendientes de un formulario de carga que quedó sin completar.

`VISOR_DATA_ROOT` permite usar una copia aislada de `django.db`, `uploads/` y `cache/`. Por defecto apunta a `data/`. `VISOR_DEBUG=1` es el modo local; con `VISOR_DEBUG=0` es obligatorio definir `SECRET_KEY` o `VISOR_SECRET_KEY`. `VISOR_ALLOWED_HOSTS` acepta una lista de hosts separada por comas. En Render se exige el inicio de sesión y se guardan los originales en PostgreSQL; consulta [DEPLOY-RENDER.md](DEPLOY-RENDER.md) antes de publicar.

## Probar con datos de ejemplo
```bash
python make_sample.py
```
Sube `muestras/v1/ventas.xlsx` y luego `muestras/v2/ventas.xlsx`: la app te preguntará si es una versión nueva.
Si subes el mismo archivo dos veces, detecta el duplicado por hash y abre el existente.

### Probar el historial de seis versiones

```bash
python muestras/generar_historial_versiones.py
```

El script crea seis libros con el mismo nombre (`demo_historial_versiones.xlsx`) en
`muestras/historial_versiones/v1` a `v6`. Carga primero el de `v1` y después los de
`v2` a `v6`, en orden. En cada aviso de archivo existente, elige **Guardar como nueva
versión**. Las versiones ilustran cambios de datos, más registros, una columna nueva,
valores mixtos en `Monto`, el cambio de `Municipio` a `Localidad` y una hoja adicional.

Los libros se pueden regenerar ejecutando el mismo comando; solo reemplaza los seis
archivos de prueba generados. Si ya existe en el visor un documento llamado
`demo_historial_versiones`, elimínalo antes para iniciar una cadena de versiones limpia.

### Probar el principal y el historial con cuatro versiones

En [`muestras/historial_principal_4_versiones/`](muestras/historial_principal_4_versiones/README.md) hay cuatro libros `padron_historial_principal.xlsx` listos para cargar en orden. Permiten comprobar un aumento de 30 filas, una reducción de 50, otro aumento de 30 y tres tramos de cambios visibles desde la versión principal. La guía de esa carpeta indica los totales esperados y la columna clave que debes elegir. Se regeneran con `python muestras/generar_cuatro_versiones.py`.

## Estructura
- `config/` y `manage.py`: configuración, rutas y arranque de Django.
- `documents/views.py` y `documents/urls.py`: capa HTTP y contrato de la API.
- `documents/models.py` y `documents/migrations/`: esquema de documentos y versiones administrado por Django.
- `documents/services/`: historial, lectura de archivos, caché, perfil del libro Excel y comparación de versiones.
- `documents/management/commands/import_legacy_history.py`: migración segura del historial anterior.
- `documents/management/commands/reconcile_storage.py`: informe y limpieza verificada de archivos huérfanos.
- `documents/pages.py` y `documents/forms.py`: páginas HTML y validación de los formularios de biblioteca, carga y visor.
- `documents/pending_uploads.py`: archivo temporal para completar la selección de modo y claves al crear una versión.
- `documents/templates/documents/`: biblioteca, visor, carga, confirmación de borrado y componentes compartidos.
- `documents/static/documents/`: CSS e iconos servidos por `django.contrib.staticfiles`.
- `assets/tailwind.css` y `assets/css/`: fuentes de estilo; `build_css.py` genera la hoja compilada en la carpeta estática de la app.
- `build_css.py`: compila Tailwind desde un comando de Python, sin Node.js ni npm.
- `data/`: `django.db`, originales en `uploads/` y cachés en `cache/`. Respalda `django.db` y `uploads/` juntos para conservar el historial.

## API
Las páginas HTML usan `/`, `/upload/`, `/versions/{id}/` y `/versions/{id}/delete/`. Las URL se generan por nombre mediante `documents/urls.py`.

La API JSON de compatibilidad conserva estas rutas:
`POST /api/files` · `GET /api/library` · `GET /api/documents` · `GET /api/versions/{id}` · `GET /api/versions/{id}/summary` · `GET /api/versions/{id}/changes` · `DELETE /api/versions/{id}`

El JSON del resumen conserva `metrics` y `chart` y añade `details` con el perfil de la hoja. La página HTML consulta por tramos las categorías del gráfico para evitar cargar listas completas en memoria.

Para asociar un archivo de otro nombre a un documento desde la API, `POST /api/files` acepta `mode=new_version` y `target_document_id=<id>`; al guardar también requiere `comparison_keys` como en cualquier nueva versión. Sin ese parámetro, el comportamiento previo de la API basado en el nombre se conserva.

La versión vigente muestra en **Cambios** toda la secuencia de comparaciones del documento (v1 → v2, v2 → v3, etc.). Cada tramo permite consultar agregados, actualizados y eliminados por hoja. `GET /api/versions/{id}` incluye `change_history` hasta la versión solicitada; `GET /api/versions/{id}/changes` devuelve el detalle del tramo que termina en esa versión. Para conservar el historial, solo se puede eliminar la versión más reciente; la API devuelve `409` al intentar borrar una versión anterior.
Si una versión anterior se eliminó antes de esta protección, su resumen puede seguir visible, pero el detalle de esa comparación requiere recuperar el archivo original de esa versión desde un respaldo.
