"""
Evaluación manual de archivos de muestra con los servicios y la base de prueba de Django.
"""

import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import override_settings
from django.test.runner import DiscoverRunner

from documents.models import Version
from documents.services import history as app_module
from documents.services.history import HTTPException

CASOS_DIR = BASE_DIR / "muestras" / "casos_prueba"

def test_upload(filename: str, content: bytes):
    try:
        res = app_module.upload(filename=filename, content=content, mode="")
        return {"ok": True, "res": res}
    except HTTPException as e:
        return {"ok": False, "status": e.status_code, "detail": e.detail}
    except Exception as e:
        return {"ok": False, "status": 500, "detail": str(e)}

def main():
    runner = DiscoverRunner(verbosity=0)
    runner.setup_test_environment()
    databases = runner.setup_databases()
    try:
        with tempfile.TemporaryDirectory() as temp_dir, override_settings(
            MEDIA_ROOT=Path(temp_dir) / "uploads",
            VISOR_CACHE_ROOT=Path(temp_dir) / "cache",
        ):
            print("=" * 80)
            print("EVALUACIÓN DE LA SUITE DE CASOS DE PRUEBA (FASE 1 & 2)")
            print("=" * 80)
            for tf in sorted(CASOS_DIR.iterdir()):
                if tf.name == "README.md":
                    continue
                res = test_upload(tf.name, tf.read_bytes())
                ver_count = Version.objects.filter(original_filename=tf.name).count()
                print(f"\n[ARCHIVO]: {tf.name}")
                if res["ok"]:
                    print(f"  Resultado: ÉXITO (status={res['res'].get('status')})")
                    print(f"  En BD: {ver_count} versión(es)")
                    vid = res["res"].get("version_id")
                    if vid:
                        ver_data = app_module.get_version(vid)
                        print(f"  Opciones detectadas: {ver_data.get('import_options')}")
                        for sheet in ver_data["sheets"]:
                            print(f"    - Hoja '{sheet['name']}': {sheet['row_count']} filas")
                else:
                    print(f"  Resultado: ERROR CONTROLADO HTTP {res['status']}: {res['detail']}")
                    print(f"  En BD: {ver_count} registros")
            print("Evaluación completada.")
    finally:
        runner.teardown_databases(databases)
        runner.teardown_test_environment()

if __name__ == "__main__":
    main()
