"""Report orphaned originals and caches left by interrupted operations."""

import hashlib
import re
import shutil
import time
from pathlib import Path

from django.core.management.base import BaseCommand

from documents.models import Version
from documents.pending_uploads import TOKEN_PATTERN, pending_dir
from documents.services.history import cache_dir, uploads_dir


ORIGINAL_NAME = re.compile(r"^([0-9a-f]{64})\.(xlsx|xls|csv)$")
CACHE_NAME = re.compile(r"^([0-9a-f]{64})\.db$")
TEMP_PREFIXES = (".incoming-", ".building-", ".cache-build-")


class Command(BaseCommand):
    help = "Informa archivos huérfanos; --delete limpia solo candidatos antiguos y verificados."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true")
        parser.add_argument("--min-age-hours", type=float, default=24)

    def handle(self, *args, **options):
        referenced = set(Version.objects.values_list("stored_path", flat=True))
        hashes = set(Version.objects.values_list("sha256", flat=True))
        removed = reported = 0
        threshold = time.time() - max(0, options["min_age_hours"]) * 3600
        for directory, pattern, references in (
            (uploads_dir(), ORIGINAL_NAME, referenced),
            (cache_dir(), CACHE_NAME, hashes),
        ):
            if not directory.exists():
                continue
            for path in directory.iterdir():
                if path.is_dir() and not path.is_symlink() and path.name.startswith(TEMP_PREFIXES):
                    reported += 1
                    if (
                        options["delete"] and path.stat().st_mtime <= threshold
                        and path.resolve().parent == directory.resolve()
                    ):
                        shutil.rmtree(path)
                        removed += 1
                        self.stdout.write(f"Eliminado temporal: {path}")
                    else:
                        self.stdout.write(f"Temporal interrumpido: {path}")
                    continue
                if not path.is_file():
                    continue
                match = pattern.fullmatch(path.name)
                if not match:
                    continue
                reference = path.name if directory == uploads_dir() else match.group(1)
                if reference in references:
                    continue
                reported += 1
                verified = directory != uploads_dir() or self._matches_hash(path, match.group(1))
                if options["delete"] and verified and path.stat().st_mtime <= threshold:
                    path.unlink()
                    removed += 1
                    self.stdout.write(f"Eliminado: {path}")
                else:
                    self.stdout.write(f"Huérfano: {path}")
        directory = pending_dir()
        if directory.is_dir():
            for path in directory.glob("*.bin"):
                if not TOKEN_PATTERN.fullmatch(path.stem) or path.stat().st_mtime > threshold:
                    continue
                reported += 1
                if options["delete"] and path.resolve().parent == directory.resolve():
                    path.unlink()
                    removed += 1
                    self.stdout.write(f"Eliminado temporal de carga: {path}")
                else:
                    self.stdout.write(f"Temporal de carga pendiente: {path}")
        self.stdout.write(f"Huérfanos: {reported}; eliminados: {removed}.")

    @staticmethod
    def _matches_hash(path: Path, expected: str) -> bool:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected
