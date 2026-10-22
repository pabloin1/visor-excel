"""Comprueba la paginación de listas largas en las páginas Django."""

import io
import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from documents.models import Document, Version
from documents.services import history


def workbook_bytes(version):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Datos"
    sheet.append(["Clave", "Monto"])
    for number in range(1, 37):
        sheet.append([f"AP-{number:03d}", number + version * 100])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


class DjangoPaginationTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings_override = override_settings(MEDIA_ROOT=root / "uploads", VISOR_CACHE_ROOT=root / "cache")
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def test_library_pages_documents_and_preserves_search(self):
        for number in range(16):
            document = Document.objects.create(name=f"reporte-{number:02d}", created_at=timezone.now())
            Version.objects.create(
                document=document, version_number=1, original_filename=f"reporte-{number:02d}.xlsx",
                stored_path=f"{number:064x}.xlsx", sha256=f"{number:064x}",
                uploaded_at=timezone.now(), sheet_count=1, row_count=1,
            )
        first = self.client.get(reverse("documents:library"), {"q": "reporte", "sort": "name"})
        self.assertEqual(len(first.context["items"]), 10)
        self.assertIn("q=reporte", first.context["pager"]["next"])
        second = self.client.get(first.context["pager"]["next"])
        self.assertEqual(len(second.context["items"]), 6)
        self.assertEqual(second.context["pager"]["number"], 2)

    def test_long_version_history_data_changes_and_chart_are_paged(self):
        version_ids = []
        for number in range(1, 13):
            result = history.upload(
                filename="paginado.xlsx", content=workbook_bytes(number),
                mode="new_version" if number > 1 else "",
                comparison_keys=json.dumps({"Datos": ["Clave"]}) if number > 1 else None,
            )
            self.assertEqual(result["status"], "created")
            version_ids.append(result["version_id"])

        library = self.client.get(reverse("documents:library"), {"q": "paginado", "sort": "name"})
        item = library.context["items"][0]
        self.assertEqual(len(item["versions"]), 3)
        self.assertTrue(item["has_more_versions"])
        self.assertContains(library, "Ver historial completo de paginado")
        versions_page = self.client.get(item["versions_url"])
        self.assertEqual(len(versions_page.context["versions"]), 10)
        self.assertIn("q=paginado", versions_page.context["library_url"])
        older_versions = self.client.get(versions_page.context["pager"]["next"])
        self.assertEqual(len(older_versions.context["versions"]), 2)

        url = reverse("documents:version", args=[version_ids[-1]])
        current = self.client.get(url, {"view": "changes", "sheet": "Datos"})
        self.assertEqual(len(current.context["history"]), 8)
        self.assertEqual(current.context["history_total"], 11)
        older_history = self.client.get(current.context["history_pager"]["next"])
        self.assertEqual(len(older_history.context["history"]), 3)
        self.assertEqual(older_history.context["comparison"]["version_number"], 4)
        selected_older = self.client.get(older_history.context["history"][-1]["url"])
        self.assertEqual(selected_older.context["comparison"]["version_number"], 2)

        earlier_change = self.client.get(url, {
            "view": "changes", "sheet": "Datos", "change": version_ids[1], "kind": "updated", "change_page": 1,
        })
        self.assertEqual(earlier_change.context["history_pager"]["number"], 2)
        self.assertEqual(len(earlier_change.context["change_records"]), 16)
        self.assertEqual(earlier_change.context["changes"]["total"], 36)

        data = self.client.get(url, {"view": "data", "sheet": "Datos", "page": 1})
        self.assertEqual(len(data.context["rows"]["rows"]), 11)
        self.assertEqual(data.context["pager"]["number"], 2)
        self.assertEqual(self.client.get(url, {"view": "data", "sheet": "Datos", "page": 99}).status_code, 302)

        chart = self.client.get(url, {"view": "summary", "sheet": "Datos", "category_col": "0", "sort_chart": "alpha"})
        self.assertEqual(len(chart.context["chart_items"]), 10)
        self.assertEqual(chart.context["chart_pager"]["pages"], 4)
        chart_next = self.client.get(chart.context["chart_pager"]["next"])
        self.assertEqual(len(chart_next.context["chart_items"]), 10)
        self.assertEqual(chart_next.context["sort_chart"], "alpha")

        others = self.client.get(url, {"view": "summary", "sheet": "Datos", "category_col": "0", "other_page": 1})
        self.assertEqual(others.context["other_count"], 29)
        self.assertEqual(len(others.context["other_details"]), 10)
        self.assertTrue(others.context["other_open"])
        self.assertContains(others, 'id="other-details" class="others-disclosure" open')
