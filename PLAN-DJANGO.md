# Plan de acción: completar la integración con Django

## Estado de ejecución (2026-10-19)

- Etapa 0: respaldo `data/backup-before-django-integration-2026-10-19/` creado y hashes de la base y los originales cotejados.
- Etapa 1: metadatos de documentos y versiones movidos al ORM; las bases por archivo siguen siendo cachés SQLite.
- Etapa 2: carga por bloques, preparación temporal de archivos, transacción de metadatos, publicación sin sobrescritura, reintentos ante conflicto y comando de reconciliación implementados.
- Etapa 3: pruebas principales migradas al ejecutor de Django; añadidas pruebas de fallo de publicación, limpieza pendiente y carga simultánea.
- Etapa 4: configuración local documentada y clave obligatoria si se desactiva `DEBUG`. La publicación en red sigue condicionada a implementar autenticación y permisos; no forma parte del uso local actual.
- Corrección del historial: la versión vigente expone y muestra todas las comparaciones anteriores; los tramos se pueden consultar por separado y las versiones históricas quedan protegidas contra eliminación para no romper la cadena.
- Cierre de la migración local: `manage.py test` descubre la suite completa, se retiró el sondeo de paginación que duplicaba la caché antigua y se eliminaron los bytecodes residuales de FastAPI. Las cachés SQLite derivadas permanecen separadas por decisión del proyecto.
- Integración gráfica: se corrigió la carga WSGI y se comprobó en Edge la biblioteca, el resumen, las filas y los tramos del historial con un viewport móvil de 390 px. El servidor sirvió la plantilla, los archivos estáticos y las respuestas de API sin errores.
- Interfaz Django: la biblioteca, el visor, la carga y la confirmación de borrado se trasladaron a plantillas y formularios de `documents`; los recursos se separaron en `documents/static/documents`. La API JSON sigue activa para clientes existentes, mientras la interfaz usa navegación y formularios HTML sin JavaScript. Las cargas de varias etapas conservan el archivo en un temporal administrado por la sesión y lo limpian al guardar o cancelar.
- El grafo local de código se reconstruyó tras retirar `frontend/`; ya no contiene rutas de `backend/main.py` ni `frontend/app.js`.

**Evidencia de cierre:** `manage.py test` aprobó 32 pruebas, incluidas las pruebas de páginas HTML, formularios de carga, historial y limpieza de temporales; las dos pruebas de concurrencia pasaron tres repeticiones adicionales en la etapa anterior. `manage.py check`, `makemigrations --check --dry-run` y `compileall` terminaron sin errores. La lectura del historial activo confirmó 2 documentos y 4 versiones, con la página, biblioteca y versión vigente respondiendo 200. La base real conservó el mismo SHA-256 que el respaldo y sus 4 originales conservaron sus hashes. `reconcile_storage` informó cero huérfanos. En una base de prueba, cargar el CSV de 35 000 filas tomó 6.61 s; abrir sus metadatos, 10.26 ms; buscar filas, 22.62 ms; y generar su resumen, 100.33 ms. Edge confirmó que la nueva biblioteca, el resumen, los datos, la carga y el historial se renderizan a 390 px sin desbordamiento de página; el SHA-256 de la base real permaneció igual durante la revisión.

## Alcance y criterio de cierre

La aplicación sigue siendo una herramienta local. Conservar el formato de la API, los identificadores y las versiones existentes, los archivos originales y las cachés de consulta. Django administrará los metadatos de `Document` y `Version`; las bases SQLite de `data/cache/` seguirán siendo cachés reconstruibles y podrán usar `sqlite3`.

El trabajo termina cuando las cargas, consultas y eliminaciones funcionan con la base configurada en Django; los fallos no dejan versiones incompletas ni borran originales válidos; y las pruebas usan la base de prueba creada por Django. No se migrarán datos de producción durante el cambio de código.

## 0. Preparar una línea base recuperable

1. Registrar el estado de `manage.py check`, `showmigrations documents` y las pruebas actuales.
2. Antes de modificar datos reales, respaldar juntos `data/django.db` y `data/uploads/`; registrar tamaño y SHA-256 de cada original. Conservar también `data/history.db` si existe. Probar que el respaldo puede leerse y que sus hashes coinciden.
3. Capturar respuestas representativas de la API: carga inicial, duplicado, aviso de nombre existente, nueva versión, biblioteca, filas, resumen, cambios y eliminación. Medir el tiempo de carga/consulta de un CSV grande.

**Salida:** respaldo verificable y pruebas de regresión que documenten el comportamiento actual. Si falla una etapa posterior, restaurar *ambos* `django.db` y `uploads/` del mismo respaldo; las cachés pueden reconstruirse.

## 1. Llevar los metadatos a la conexión de Django

1. Cambiar `documents/services/history.py` para consultar y modificar `Document` y `Version` mediante el ORM. Para consultas complejas que lo justifiquen, usar `django.db.connection.cursor()` con parámetros, nunca una conexión `sqlite3` nueva a `data/django.db`.
2. Obtener rutas desde `django.conf.settings` o inyectarlas en el servicio. Evitar que el servicio construya la ruta fija `data/django.db`; la base de datos debe venir exclusivamente de `DATABASES`.
3. Mantener por ahora `stored_path`, las tablas actuales y la forma de las respuestas JSON. Convertir explícitamente los campos JSON y las fechas donde sea necesario para conservar la salida de la API. No introducir una migración de esquema salvo que las pruebas demuestren su necesidad.
4. Conservar `sqlite3` en `cache.py` y `comparison.py` para las bases derivadas por archivo. Separar con claridad esa capa de la base administrada por Django.

**Aceptación:** las vistas leen y escriben usando la base de prueba de Django; el admin muestra las mismas versiones; `makemigrations --check --dry-run` no detecta cambios inesperados; las respuestas de la API mantienen su contrato.

## 2. Hacer seguras las cargas y eliminaciones

1. Recibir el archivo en una ruta temporal única y calcular su SHA-256 por bloques, respetando el límite de 50 MB. Validar y construir la caché en una ruta temporal antes de publicar el original y la caché definitivos.
2. Usar `transaction.atomic()` para crear el documento y la versión juntos. Mantener la transacción corta: hacer lectura de Excel y construcción de caché antes de abrirla. Conservar las restricciones únicas de hash y de `(documento, número de versión)`; resolver colisiones concurrentes con un reintento acotado y una respuesta definida.
3. Publicar archivos sin sobrescribir un original válido. Si la operación de base falla, retirar solo los archivos creados por esa carga. Agregar una comprobación de reconciliación para detectar archivos huérfanos tras una interrupción del proceso; no eliminar automáticamente archivos sin revisión de referencias y hashes.
4. En la eliminación, confirmar primero la eliminación de metadatos y después limpiar original y caché. Hacer la limpieza repetible; si falla, registrar el archivo pendiente para reintentarla. No devolver un error ambiguo cuando la versión ya fue eliminada.
5. Reconstruir el perfil estructural antiguo mediante el ORM y dentro de una operación controlada, evitando escrituras por una segunda conexión.

**Aceptación:** probar fallos de parseo, caché, inserción, conflicto de unicidad, publicación y borrado. En cada caso, el historial sigue siendo consultable, ningún original referenciado desaparece y se puede reintentar sin duplicar versiones. Dos cargas simultáneas del mismo archivo producen una sola versión.

## 3. Sustituir pruebas con esquema manual por pruebas de Django

1. Migrar `tests/test_django_api.py` a `django.test.TestCase` y usar `manage.py test`; crear los datos mediante modelos y migraciones de la base de prueba. Aislar `MEDIA_ROOT` y el directorio de caché en carpetas temporales.
2. Conservar los casos de negocio de `test_version_schema.py` y `test_version_changes.py`, adaptándolos al servicio nuevo. Eliminar la dependencia de `tests/support.py` que crea manualmente las tablas `documents` y `versions`.
3. Usar `TransactionTestCase` donde haya que observar confirmaciones, reversiones o concurrencia real. Añadir pruebas de inyección de fallos para la etapa 2 y una comparación de respuestas con la línea base.
4. Ejecutar `manage.py check`, `makemigrations --check --dry-run`, `manage.py test` y una prueba manual con una copia del historial real. Comparar IDs, nombres, cantidades de versiones, hashes y apertura de hojas antes y después.

**Aceptación:** suite verde sin escribir en `data/django.db` ni en `data/uploads/`; mismo resultado funcional con los archivos de ejemplo y con la copia del historial.

## 4. Configuración local y posible despliegue

1. Mantener la configuración local documentada. Hacer explícitos `DEBUG`, `SECRET_KEY` y `ALLOWED_HOSTS` por entorno; impedir un arranque no local con la clave de respaldo.
2. Si la aplicación se publica en una red, definir antes autenticación y permisos para lectura, carga y eliminación, además de HTTPS, cookies seguras, archivos estáticos y revisión de `manage.py check --deploy`. No activar HSTS ni redirección HTTPS en la configuración local HTTP.
3. Actualizar `README.md` con la nueva suite de pruebas, respaldo y restauración, rutas de datos y límites de uso.

**Aceptación:** ejecución local intacta. Una futura configuración de despliegue debe pasar su revisión de seguridad con valores reales del entorno; las advertencias propias del modo local quedan documentadas.

## Orden de implementación

Trabajar en etapas 0 → 1 → 2 → 3 → 4. Tras cada etapa, ejecutar sus pruebas y revisar la integridad del historial. Si falla una aceptación, corregir esa etapa antes de continuar. Mantener los cambios de esquema y la migración de datos fuera de alcance salvo evidencia concreta de que son necesarios.
