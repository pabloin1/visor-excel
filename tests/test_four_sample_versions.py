"""Comprueba los libros de muestra mediante el flujo real de versiones Django."""

import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from documents.services import history
from muestras.generar_cuatro_versiones import FILENAME, SHEET_NAME


SAMPLES = Path(__file__).resolve().parents[1] / "muestras" / "historial_principal_4_versiones"
EXPECTED_STEPS = ((30, 10, 0), (0, 8, 50), (30, 12, 0))


class FourSampleVersionsTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings_override = override_settings(
            MEDIA_ROOT=root / "uploads",
            VISOR_CACHE_ROOT=root / "cache",
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def test_samples_replace_principal_and_show_all_history(self):
        version_ids = []
        for number in range(1, 5):
            path = SAMPLES / f"v{number}" / FILENAME
            self.assertTrue(path.is_file(), path)
            result = history.upload(
                filename=FILENAME,
                content=path.read_bytes(),
                mode="new_version" if number > 1 else "",
                comparison_keys=json.dumps({SHEET_NAME: ["Folio"]}) if number > 1 else None,
            )
            self.assertEqual(result["status"], "created")
            version_ids.append(result["version_id"])
            if number > 1:
                sheet = result["change_summary"]["sheets"][0]
                actual = (sheet["added"], sheet["updated"], sheet["removed"])
                self.assertEqual(actual, EXPECTED_STEPS[number - 2])

        current = history.get_version(version_ids[-1])
        self.assertTrue(current["is_primary"])
        self.assertEqual(current["version_number"], 4)
        self.assertEqual(current["sheets"][0]["row_count"], 110)
        self.assertEqual(
            [(item["previous_version"], item["version_number"]) for item in current["change_history"]],
            [(1, 2), (2, 3), (3, 4)],
        )
        for item, expected in zip(current["change_history"], EXPECTED_STEPS):
            sheet = item["sheets"][0]
            self.assertEqual((sheet["added"], sheet["updated"], sheet["removed"]), expected)

        rows = history.get_version_rows(version_ids[-1], SHEET_NAME, page_size=200)
        self.assertEqual(rows["total_rows"], 110)
        folios = {row["r"][1] for row in rows["rows"]}
        self.assertEqual(folios, {f"AP-{number:04d}" for number in range(51, 161)})

        report = history.get_workbook_report(version_ids[-1])
        self.assertEqual((report["sheet_count"], report["total_rows"]), (1, 110))
        self.assertEqual(report["sheets"][0]["suggested_category"], 0)
        self.assertEqual(report["sheets"][0]["suggested_measure"], 3)
        self.assertTrue(report["sheets"][0]["categorical_fields"][1]["identifier"])
        summary_page = self.client.get(reverse("documents:version", args=[version_ids[-1]]))
        self.assertEqual(summary_page.status_code, 200)
        self.assertContains(summary_page, "Resumen del libro Excel")
        self.assertContains(summary_page, "Suma de Monto por Municipio")

        page = self.client.get(reverse("documents:version", args=[version_ids[-1]]), {
            "view": "changes", "sheet": SHEET_NAME,
        })
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context["history"]), 3)
        for old, new in ((1, 2), (2, 3), (3, 4)):
            self.assertContains(page, f"v{old} → v{new}")
        for version_id, expected in zip(version_ids[1:], EXPECTED_STEPS):
            for kind, count in zip(("added", "updated", "removed"), expected):
                self.assertEqual(
                    history.get_version_changes(version_id, sheet=SHEET_NAME, kind=kind)["total"],
                    count,
                )
