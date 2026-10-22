import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from openpyxl import Workbook

from documents import pending_uploads
from documents.models import PendingContent, VersionContent
from documents.services import history


def workbook_bytes(amount):
    book = Workbook()
    book.active.append(["Clave", "Monto"])
    book.active.append(["001", amount])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


class RenderStorageTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.override = override_settings(
            MEDIA_ROOT=root / "uploads",
            VISOR_CACHE_ROOT=root / "cache",
            VISOR_ORIGINAL_STORAGE="database",
        )
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.temporary.cleanup()

    def test_versions_and_changes_rebuild_after_ephemeral_files_disappear(self):
        first = history.upload("demo.xlsx", workbook_bytes(10))
        second = history.upload(
            "demo.xlsx", workbook_bytes(20), mode="new_version",
            comparison_keys='{"Sheet": ["Clave"]}',
        )
        self.assertEqual(VersionContent.objects.count(), 2)
        for path in history.uploads_dir().glob("*.xlsx"):
            path.unlink()
        for path in history.cache_dir().glob("*.db"):
            path.unlink()

        current = history.get_version(second["version_id"])
        self.assertEqual(current["version_number"], 2)
        self.assertEqual(history.get_version_rows(second["version_id"], "Sheet")["total_rows"], 1)
        self.assertEqual(history.get_workbook_report(second["version_id"])["sheet_count"], 1)
        changes = history.get_version_changes(second["version_id"], "Sheet", "updated")
        self.assertEqual(changes["total"], 1)
        self.assertTrue((history.uploads_dir() / history.get_version_row(first["version_id"])["stored_path"]).exists())

    def test_staged_upload_recovers_after_local_file_disappears(self):
        request = RequestFactory().get("/upload/")
        middleware = SessionMiddleware(lambda request: None)
        middleware.process_request(request)
        pending_uploads.stage(
            request, SimpleUploadedFile("demo.xlsx", workbook_bytes(10))
        )
        token = request.session[pending_uploads.SESSION_KEY]["token"]
        path = pending_uploads.pending_dir() / f"{token}.bin"
        path.unlink()
        self.assertEqual(pending_uploads.get(request)[0], "demo.xlsx")
        self.assertTrue(path.exists())
        self.assertTrue(PendingContent.objects.filter(pk=token).exists())
        pending_uploads.clear(request)
        self.assertFalse(PendingContent.objects.filter(pk=token).exists())

    def test_local_original_can_be_backfilled_and_exported(self):
        with override_settings(VISOR_ORIGINAL_STORAGE="filesystem"):
            version_id = history.upload("demo.xlsx", workbook_bytes(10))["version_id"]
        self.assertFalse(VersionContent.objects.filter(version_id=version_id).exists())
        call_command("backfill_originals", stdout=io.StringIO())
        output = io.StringIO()
        call_command(
            "dumpdata", "documents.Document", "documents.Version", "documents.VersionContent",
            stdout=output,
        )
        records = json.loads(output.getvalue())
        self.assertEqual(len(records), 3)
        self.assertTrue(next(item for item in records if item["model"] == "documents.versioncontent")["fields"]["content"])


@override_settings(VISOR_REQUIRE_LOGIN=True)
class RenderAccessTests(TestCase):
    def test_viewer_requires_login_and_health_is_public(self):
        self.assertEqual(self.client.get("/healthz/").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 302)
        response = self.client.get("/api/library")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Se requiere iniciar sesión.")
        get_user_model().objects.create_user(username="demo", password="clave-segura-123")
        self.assertEqual(self.client.post("/accounts/login/", {
            "username": "demo", "password": "clave-segura-123",
        }).status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/accounts/logout/").status_code, 302)
        self.assertEqual(self.client.get("/accounts/login/").status_code, 200)

    def test_admin_bootstrap_is_idempotent(self):
        with mock.patch.dict("os.environ", {
            "VISOR_ADMIN_USERNAME": "operador",
            "VISOR_ADMIN_PASSWORD": "clave-segura-123",
        }):
            call_command("bootstrap_admin", stdout=io.StringIO())
            user = get_user_model().objects.get(username="operador")
            self.assertTrue(user.is_superuser)
            call_command("bootstrap_admin", stdout=io.StringIO())
            self.assertEqual(get_user_model().objects.filter(username="operador").count(), 1)
