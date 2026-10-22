# Demo en Render (30 días)

Este proyecto incluye [`render.yaml`](render.yaml) para crear un servicio web y una base PostgreSQL gratuitos. El despliegue usa Django, Gunicorn y WhiteNoise. Los metadatos, originales Excel y archivos de carga pendientes se guardan en PostgreSQL; las bases SQLite de `cache/` se reconstruyen en el disco temporal cuando hacen falta.

## Crear la demo

1. Sube este repositorio a GitHub, sin `data/`, secretos ni archivos exportados.
2. En Render, crea un **Blueprint** desde el repositorio. Render leerá `render.yaml` y preparará el servicio web y PostgreSQL.
3. Cuando Render lo solicite, define `VISOR_ADMIN_USERNAME` y una contraseña segura en `VISOR_ADMIN_PASSWORD`. No los guardes en Git. `SECRET_KEY` y `DATABASE_URL` los configura el Blueprint.
4. Espera a que el build complete `collectstatic`, `migrate` y `bootstrap_admin`. Abre la URL del servicio y entra con el usuario elegido. `/healthz/` debe devolver `ok` cuando la base esté disponible.

El inicio de sesión protege las páginas y la API. La API devuelve HTTP 401 si falta la sesión. El administrador se crea una sola vez; los despliegues posteriores no cambian su contraseña. Si necesitas cambiarla, usa las herramientas de Django con acceso a la base o crea otra cuenta administrativa mediante un comando de gestión propio.

## Importar el historial local (opcional)

La demo empieza vacía. Si quieres llevar los documentos y versiones actuales a PostgreSQL, haz primero un respaldo **conjunto** de `data/django.db` y `data/uploads/`, y comprueba que el despliegue ya completó las migraciones. Desde tu equipo:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py backfill_originals
.\.venv\Scripts\python.exe manage.py dumpdata documents.Document documents.Version documents.VersionContent --output render-history.json
```

`backfill_originals` verifica el SHA-256 antes de copiar los Excel a la base local; se puede repetir. Si falta algún original, hay que recuperarlo del respaldo antes de importar. `render-history.json` contiene **todos los Excel originales** codificados y debe tratarse como dato privado.

Obtén la **External Database URL** de la base PostgreSQL en Render y, en la misma terminal, ejecuta:

```powershell
$env:DATABASE_URL = "URL_EXTERNA_DE_POSTGRES"
.\.venv\Scripts\python.exe manage.py loaddata render-history.json
Remove-Item Env:DATABASE_URL
```

Importa en una base vacía: `loaddata` conserva los identificadores y el historial, pero puede chocar con versiones ya cargadas. Tras verificar la demo, borra `render-history.json` de tu equipo si ya no lo necesitas. No lo subas al repositorio.

## Límites de esta demo

- Render gratuito borra el disco del servicio al reiniciar, redeplegar o suspenderlo. Solo las cachés y copias temporales usan ese disco; los originales se vuelven a recuperar desde PostgreSQL.
- PostgreSQL gratuito expira **30 días después de su creación** y tiene **1 GB** de almacenamiento. La aplicación admite Excel de hasta 50 MB, pero sus originales y metadatos consumen ese cupo. Haz un respaldo o pasa a un plan persistente antes del vencimiento si quieres conservar la demo.
- El servicio gratuito se suspende tras 15 minutos sin tráfico y la primera solicitud posterior puede tardar aproximadamente un minuto.
- El servicio gratuito dispone de memoria limitada; prueba primero con libros pequeños. Los Excel cercanos al máximo permitido de 50 MB pueden agotar la memoria al analizarlos.
- Los archivos locales en `data/` no se publican automáticamente. La demo puede iniciarse vacía o importarse con los pasos anteriores.

`manage.py check --deploy` puede mostrar avisos sobre HSTS para subdominios y precarga. Esta demo activa HSTS solo para su propio host durante una hora; no solicita precarga ni afecta otros subdominios de Render.

Consulta los detalles vigentes en la [guía oficial de Django en Render](https://render.com/docs/deploy-django), las [limitaciones del plan gratuito](https://render.com/docs/free) y la [referencia de Blueprints](https://render.com/docs/blueprint-spec).
