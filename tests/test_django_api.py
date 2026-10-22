import io
import importlib
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from openpyxl import Workbook
from documents.models import Version



def workbook_bytes():
    book = Workbook()
    sheet = book.active
    sheet.title = "Datos"
    sheet.append(["Clave", "Monto"])
    sheet.append(["001", 10])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


class DjangoApiTests(TestCase):
    def test_wsgi_and_asgi_entrypoints_load(self):
        self.assertTrue(callable(importlib.import_module("config.wsgi").application))
        self.assertTrue(callable(importlib.import_module("config.asgi").application))

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name) / "data"
        self.settings_override = override_settings(
            MEDIA_ROOT=root / "uploads", VISOR_CACHE_ROOT=root / "cache"
        )
        self.settings_override.enable()
        self.client = Client(enforce_csrf_checks=True)

    def tearDown(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def test_template_upload_queries_and_delete(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"/static/documents/app.generated.css", page.content)
        self.assertNotIn(b"/static/app.js", page.content)
        self.assertIn("csrftoken", self.client.cookies)
        token = self.client.cookies["csrftoken"].value

        payload = workbook_bytes()
        upload = self.client.post(
            "/api/files",
            {"file": SimpleUploadedFile("reporte.xlsx", payload)},
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(upload.status_code, 200, upload.content)
        result = upload.json()
        self.assertEqual(result["status"], "created")
        vid = result["version_id"]

        library = self.client.get("/api/library").json()
        self.assertEqual(library["total"], 1)
        self.assertEqual(library["items"][0]["primary_id"], vid)
        self.assertEqual(self.client.get(f"/api/versions/{vid}").status_code, 200)
        rows = self.client.get(f"/api/versions/{vid}/rows?sheet=Datos").json()
        self.assertEqual(rows["total_rows"], 1)
        self.assertEqual(self.client.get(f"/api/versions/{vid}/summary?sheet=Datos").status_code, 200)
        self.assertEqual(self.client.get(f"/api/versions/{vid}/changes").status_code, 200)

        deleted = self.client.delete(f"/api/versions/{vid}", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/library").json()["total"], 0)

    def test_csrf_and_invalid_query_are_rejected(self):
        payload = workbook_bytes()
        upload = self.client.post(
            "/api/files", {"file": SimpleUploadedFile("reporte.xlsx", payload)}
        )
        self.assertEqual(upload.status_code, 403)
        invalid = self.client.get("/api/library?page=abc")
        self.assertEqual(invalid.status_code, 400)

    def test_api_can_target_existing_document_with_different_filename(self):
        self.client.get("/")
        token = self.client.cookies["csrftoken"].value
        created = self.client.post("/api/files", {
            "file": SimpleUploadedFile("origen.xlsx", workbook_bytes()),
        }, HTTP_X_CSRFTOKEN=token).json()
        document_id = Version.objects.get(pk=created["version_id"]).document_id
        book = Workbook()
        sheet = book.active
        sheet.title = "Datos"
        sheet.append(["Clave", "Estado"])
        sheet.append(["001", "Activo"])
        output = io.BytesIO()
        book.save(output)
        payload = output.getvalue()
        setup = self.client.post("/api/files", {
            "file": SimpleUploadedFile("otro_nombre.xlsx", payload),
            "mode": "new_version", "target_document_id": document_id,
        }, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(setup.json()["status"], "comparison_setup_required")
        saved = self.client.post("/api/files", {
            "file": SimpleUploadedFile("otro_nombre.xlsx", payload),
            "mode": "new_version", "target_document_id": document_id,
            "comparison_keys": json.dumps({"Datos": ["Clave"]}),
        }, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(saved.json()["status"], "created")
        self.assertEqual(Version.objects.get(pk=saved.json()["version_id"]).document_id, document_id)

    def test_admin_reads_uploaded_version(self):
        self.client.get("/")
        token = self.client.cookies["csrftoken"].value
        upload = self.client.post(
            "/api/files",
            {"file": SimpleUploadedFile("reporte.xlsx", workbook_bytes())},
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(upload.status_code, 200)
        admin_user = get_user_model().objects.create_superuser(
            username="admin-test", password="local-test-password"
        )
        self.client.force_login(admin_user)
        page = self.client.get("/admin/documents/version/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "reporte.xlsx")
