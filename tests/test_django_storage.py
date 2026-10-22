import hashlib
import io
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from openpyxl import Workbook

from documents.models import Document, Version
from documents.services import history


def workbook_bytes():
    book = Workbook()
    book.active.append(["Clave", "Monto"])
    book.active.append(["001", 10])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


class StorageTransactionTests(TransactionTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.settings_override = override_settings(
            MEDIA_ROOT=root / "uploads", VISOR_CACHE_ROOT=root / "cache"
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temporary.cleanup()

    def test_failure_publishing_cache_rolls_back_metadata_and_original(self):
        publish = history._publish

        def fail_on_cache(source, destination, sha256=None):
            if destination.suffix == ".db":
                raise OSError("cache write failed")
            return publish(source, destination, sha256)

        with mock.patch.object(history, "_publish", side_effect=fail_on_cache):
            with self.assertRaises(OSError):
                history.upload("reporte.xlsx", workbook_bytes())

        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(Version.objects.count(), 0)
        self.assertEqual(list(history.uploads_dir().iterdir()), [])
        self.assertEqual(list(history.cache_dir().iterdir()), [])

    def test_delete_reports_failed_cleanup_and_reconcile_can_retry(self):
        created = history.upload("reporte.xlsx", workbook_bytes())
        version = Version.objects.get(pk=created["version_id"])
        original = history.uploads_dir() / version.stored_path
        cache = history.cache_dir() / f"{version.sha256}.db"

        with mock.patch.object(history.logger, "exception"), mock.patch.object(
            history.Path, "unlink", side_effect=OSError("busy")
        ):
            result = history.delete_version(version.pk)
        self.assertEqual(result, {"ok": True, "cleanup_pending": True})
        self.assertFalse(Version.objects.exists())
        self.assertTrue(original.exists())
        self.assertTrue(cache.exists())

        output = io.StringIO()
        call_command("reconcile_storage", "--delete", "--min-age-hours=0", stdout=output)
        self.assertFalse(original.exists())
        self.assertFalse(cache.exists())
        self.assertIn("eliminados: 2", output.getvalue())

    def test_existing_original_is_never_overwritten(self):
        payload = workbook_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        history.uploads_dir().mkdir(parents=True)
        path = history.uploads_dir() / f"{sha}.xlsx"
        path.write_bytes(b"incorrect")

        with self.assertRaises(RuntimeError):
            history.upload("reporte.xlsx", payload)

        self.assertEqual(path.read_bytes(), b"incorrect")
        self.assertFalse(Version.objects.exists())

    def test_reconcile_removes_interrupted_temp_directories(self):
        history.cache_dir().mkdir(parents=True)
        interrupted = history.cache_dir() / ".cache-build-interrupted"
        interrupted.mkdir()
        (interrupted / "partial.db").write_bytes(b"incomplete")

        call_command("reconcile_storage", "--delete", "--min-age-hours=0", stdout=io.StringIO())

        self.assertFalse(interrupted.exists())

    def test_chunked_upload_limit_leaves_no_files(self):
        class ChunkedFile:
            def chunks(self):
                yield b"123"
                yield b"456"

        with mock.patch.object(history, "MAX_FILE_SIZE", 5):
            with self.assertRaises(history.HTTPException) as error:
                history.upload("reporte.csv", ChunkedFile())

        self.assertEqual(error.exception.status_code, 413)
        self.assertEqual(list(history.uploads_dir().iterdir()), [])
        self.assertFalse(Version.objects.exists())

    def test_concurrent_identical_uploads_create_one_version(self):
        payload = workbook_bytes()
        barrier = threading.Barrier(2)
        stage = history._stage_file

        def synchronized_stage(content, destination):
            digest = stage(content, destination)
            barrier.wait(timeout=10)
            return digest

        def load():
            close_old_connections()
            try:
                return history.upload("reporte.xlsx", payload)
            finally:
                close_old_connections()

        with mock.patch.object(history, "_stage_file", side_effect=synchronized_stage):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: load(), range(2)))

        self.assertEqual({result["status"] for result in results}, {"created", "duplicate"})
        self.assertEqual(Version.objects.count(), 1)
        self.assertEqual(Document.objects.count(), 1)

    def test_concurrent_new_versions_do_not_save_stale_comparison(self):
        first = workbook_bytes()
        history.upload("reporte.xlsx", first)
        book = Workbook()
        book.active.append(["Clave", "Monto"])
        book.active.append(["001", 20])
        second_file = io.BytesIO()
        book.save(second_file)
        book.active["B2"] = 30
        third_file = io.BytesIO()
        book.save(third_file)

        barrier = threading.Barrier(2)
        stage = history._stage_file

        def synchronized_stage(content, destination):
            digest = stage(content, destination)
            barrier.wait(timeout=10)
            return digest

        def load(payload):
            close_old_connections()
            try:
                try:
                    return history.upload(
                        "reporte.xlsx", payload, mode="new_version",
                        comparison_keys='{"Sheet": ["Clave"]}',
                    )
                except history.HTTPException as exc:
                    return {"status": exc.status_code}
            finally:
                close_old_connections()

        with mock.patch.object(history, "_stage_file", side_effect=synchronized_stage):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(load, [second_file.getvalue(), third_file.getvalue()]))

        self.assertEqual({result["status"] for result in results}, {"created", 409})
        self.assertEqual(Version.objects.count(), 2)
        latest = Version.objects.order_by("-version_number").first()
        self.assertEqual(latest.version_number, 2)
        self.assertEqual(latest.change_summary["previous_version"], 1)
