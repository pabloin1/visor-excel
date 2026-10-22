"""Importa el historial de FastAPI a las tablas administradas por Django."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from documents.models import Document, Version, VersionContent


JSON_FIELDS = ("import_options", "schema_info", "comparison_keys", "change_summary")


def load_legacy(source: Path):
    if not source.is_file():
        raise CommandError(f"No existe el historial original: {source}")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        documents = [dict(row) for row in connection.execute("SELECT * FROM documents ORDER BY id")]
        versions = [dict(row) for row in connection.execute("SELECT * FROM versions ORDER BY id")]
    return documents, versions


def validate_originals(versions, uploads: Path):
    for version in versions:
        stored_path = version["stored_path"]
        if Path(stored_path).name != stored_path:
            raise CommandError(f"Ruta inválida en versión {version['id']}: {stored_path}")
        original = uploads / stored_path
        if not original.is_file():
            raise CommandError(f"Falta el archivo de la versión {version['id']}: {original}")
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        if digest != version["sha256"]:
            raise CommandError(f"El archivo de la versión {version['id']} no coincide con su SHA-256.")


class Command(BaseCommand):
    help = "Importa una vez data/history.db sin tocar el historial original ni sus archivos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=Path,
            default=Path(settings.BASE_DIR) / "data" / "history.db",
            help="Ruta de la base SQLite anterior.",
        )

    def handle(self, *args, **options):
        source = options["source"].resolve()
        documents, versions = load_legacy(source)
        validate_originals(versions, Path(settings.MEDIA_ROOT))

        source_doc_ids = {row["id"] for row in documents}
        source_version_ids = {row["id"] for row in versions}
        if any(row["document_id"] not in source_doc_ids for row in versions):
            raise CommandError("El historial original contiene versiones sin documento.")

        target_docs = Document.objects.count()
        target_versions = Version.objects.count()
        if target_docs or target_versions:
            existing_docs = {row["id"]: row for row in Document.objects.values("id", "name", "created_at")}
            existing_versions = {row["id"]: row for row in Version.objects.values("id", "sha256", "document_id")}
            matches = (
                set(existing_docs) == source_doc_ids
                and set(existing_versions) == source_version_ids
                and all(
                    existing_docs[row["id"]]["name"] == row["name"]
                    and existing_docs[row["id"]]["created_at"] == datetime.fromisoformat(row["created_at"])
                    for row in documents
                )
                and all(
                    existing_versions[row["id"]]["sha256"] == row["sha256"]
                    and existing_versions[row["id"]]["document_id"] == row["document_id"]
                    for row in versions
                )
            )
            if matches:
                self.stdout.write(self.style.SUCCESS(
                    f"Historial ya importado: {target_docs} documentos y {target_versions} versiones."
                ))
                return
            raise CommandError(
                "La base Django ya contiene datos distintos. No se modificó nada; revise la migración manualmente."
            )

        with transaction.atomic():
            for row in documents:
                Document.objects.create(
                    id=row["id"],
                    name=row["name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            for row in versions:
                fields = {
                    "id": row["id"],
                    "document_id": row["document_id"],
                    "version_number": row["version_number"],
                    "original_filename": row["original_filename"],
                    "stored_path": row["stored_path"],
                    "sha256": row["sha256"],
                    "uploaded_at": datetime.fromisoformat(row["uploaded_at"]),
                    "sheet_count": row["sheet_count"],
                    "row_count": row["row_count"],
                }
                for field in JSON_FIELDS:
                    fields[field] = json.loads(row[field]) if row.get(field) else None
                saved = Version.objects.create(**fields)
                if settings.VISOR_ORIGINAL_STORAGE == "database":
                    original = Path(settings.MEDIA_ROOT) / row["stored_path"]
                    VersionContent.objects.create(version=saved, content=original.read_bytes())

        self.stdout.write(self.style.SUCCESS(
            f"Importados {len(documents)} documentos y {len(versions)} versiones desde {source}."
        ))
