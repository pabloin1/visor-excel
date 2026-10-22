import io
import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from openpyxl import Workbook

from documents.models import Version
from documents.services import history as app
from documents.services.history import HTTPException


def make_workbook(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Padron"
    sheet.append(["Folio", "Localidad", "Monto", "Estado"])
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class VersionChangesTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings_override = override_settings(
            MEDIA_ROOT=self.root / "data" / "uploads",
            VISOR_CACHE_ROOT=self.root / "data" / "cache",
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def upload(self, filename, content, mode="", comparison_keys=None):
        return app.upload(
            filename=filename,
            content=content,
            mode=mode,
            comparison_keys=(
                json.dumps(comparison_keys) if comparison_keys is not None else None
            ),
        )

    def test_next_version_reports_added_updated_and_removed_rows(self):
        previous = make_workbook([
            ["AP-001", "Tuxtla", 100, "Activo"],
            ["AP-002", "Tapachula", 200, "Activo"],
            ["AP-003", "Comitán", 300, "Inactivo"],
        ])
        current = make_workbook([
            ["AP-001", "Tuxtla", 125, "Activo"],
            ["AP-002", "Tapachula", 200, "Activo"],
            ["AP-004", "Palenque", 400, "Activo"],
        ])
        first = self.upload("padron.xlsx", previous)
        setup = self.upload("padron.xlsx", current, mode="new_version")
        self.assertEqual(setup["status"], "comparison_setup_required")
        self.assertEqual(setup["sheets"][0]["available_keys"][0], "Folio")

        second = self.upload(
            "padron.xlsx",
            current,
            mode="new_version",
            comparison_keys={"Padron": ["Folio"]},
        )
        sheet = second["change_summary"]["sheets"][0]
        self.assertEqual((sheet["added"], sheet["updated"], sheet["removed"]), (1, 1, 1))
        self.assertEqual(sheet["key_columns"], ["Folio"])

        changes = app.get_version_changes(
            second["version_id"], sheet="Padron", kind="updated"
        )
        self.assertEqual(changes["total"], 1)
        self.assertEqual(
            changes["records"][0]["changes"],
            [{"column": "Monto", "old": 100.0, "new": 125.0}],
        )
        added = app.get_version_changes(second["version_id"], sheet="Padron", kind="added")
        self.assertEqual(added["records"][0]["keys"], {"Folio": "AP-004"})
        removed = app.get_version_changes(second["version_id"], sheet="Padron", kind="removed")
        self.assertEqual(removed["records"][0]["keys"], {"Folio": "AP-003"})

        version = app.get_version(second["version_id"])
        self.assertTrue(version["is_primary"])
        self.assertEqual(version["version_number"], 2)
        self.assertEqual(first["status"], "created")

    def test_duplicate_key_rejects_new_version_without_partial_history(self):
        previous = make_workbook([["AP-001", "Tuxtla", 100, "Activo"]])
        duplicate_keys = make_workbook([
            ["AP-001", "Tuxtla", 110, "Activo"],
            ["AP-001", "Palenque", 120, "Activo"],
        ])
        self.upload("padron.xlsx", previous)

        with self.assertRaises(HTTPException) as error:
            self.upload(
                "padron.xlsx",
                duplicate_keys,
                mode="new_version",
                comparison_keys={"Padron": ["Folio"]},
            )

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("no identifican filas únicas", error.exception.detail)
        count = Version.objects.count()
        self.assertEqual(count, 1)

    def test_current_version_exposes_every_comparison_and_preserves_history(self):
        first = self.upload("padron.xlsx", make_workbook([
            ["AP-001", "Tuxtla", 100, "Activo"],
        ]))
        second = self.upload(
            "padron.xlsx",
            make_workbook([["AP-001", "Tuxtla", 125, "Activo"]]),
            mode="new_version",
            comparison_keys={"Padron": ["Folio"]},
        )
        third = self.upload(
            "padron.xlsx",
            make_workbook([
                ["AP-001", "Tuxtla", 150, "Activo"],
                ["AP-002", "Tapachula", 200, "Activo"],
            ]),
            mode="new_version",
            comparison_keys={"Padron": ["Folio"]},
        )

        self.assertEqual(app.get_version(first["version_id"])["change_history"], [])
        self.assertEqual(
            [item["id"] for item in app.get_version(second["version_id"])["change_history"]],
            [second["version_id"]],
        )
        current = app.get_version(third["version_id"])
        self.assertTrue(current["is_primary"])
        self.assertEqual(
            [(item["id"], item["previous_version"], item["version_number"])
             for item in current["change_history"]],
            [(second["version_id"], 1, 2), (third["version_id"], 2, 3)],
        )
        self.assertEqual(
            [(item["sheets"][0]["added"], item["sheets"][0]["updated"])
             for item in current["change_history"]],
            [(0, 1), (1, 1)],
        )
        response = self.client.get(f'/api/versions/{third["version_id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["change_history"]), 2)
        old_detail = self.client.get(
            f'/api/versions/{second["version_id"]}/changes?sheet=Padron&kind=updated'
        ).json()
        self.assertEqual(old_detail["records"][0]["changes"][0]["new"], 125.0)
        new_detail = self.client.get(
            f'/api/versions/{third["version_id"]}/changes?sheet=Padron&kind=updated'
        ).json()
        self.assertEqual(new_detail["records"][0]["changes"][0]["new"], 150.0)

        blocked = self.client.delete(f'/api/versions/{first["version_id"]}')
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(Version.objects.count(), 3)
        self.assertEqual(len(app.get_version(third["version_id"])["change_history"]), 2)

        removed_latest = self.client.delete(f'/api/versions/{third["version_id"]}')
        self.assertEqual(removed_latest.status_code, 200)
        previous_current = app.get_version(second["version_id"])
        self.assertTrue(previous_current["is_primary"])
        self.assertEqual(len(previous_current["change_history"]), 1)
