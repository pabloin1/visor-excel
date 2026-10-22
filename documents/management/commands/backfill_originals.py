"""Copy verified local originals into the durable database storage."""

import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from documents.models import Version, VersionContent
from documents.services.history import uploads_dir


class Command(BaseCommand):
    help = "Guarda originales locales verificados en la base para una exportación a Render."

    def handle(self, *args, **options):
        missing = []
        copied = 0
        for version in Version.objects.order_by("pk").iterator():
            stored = VersionContent.objects.filter(version_id=version.pk).values_list("content", flat=True).first()
            if stored is not None:
                if hashlib.sha256(bytes(stored)).hexdigest() != version.sha256:
                    raise CommandError(f"El original guardado de la versión {version.pk} no coincide con su SHA-256.")
                continue
            path = uploads_dir() / version.stored_path
            if not path.is_file():
                missing.append(version.pk)
                continue
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != version.sha256:
                raise CommandError(f"El original de la versión {version.pk} no coincide con su SHA-256.")
            with transaction.atomic():
                VersionContent.objects.get_or_create(version=version, defaults={"content": content})
            copied += 1
        if missing:
            raise CommandError(f"Faltan originales de las versiones: {', '.join(map(str, missing))}. Se copiaron {copied} originales válidos.")
        self.stdout.write(self.style.SUCCESS(f"Originales guardados: {copied}."))
