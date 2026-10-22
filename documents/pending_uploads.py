"""Short-lived originals for multi-step uploads rendered by Django."""

import re
import secrets
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.utils import timezone

from documents.models import PendingContent


SESSION_KEY = "visor_pending_upload"
TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MAX_AGE = 24 * 60 * 60


def pending_dir() -> Path:
    return Path(settings.MEDIA_ROOT).parent / ".pending-uploads"


def clear(request) -> None:
    entry = request.session.pop(SESSION_KEY, None)
    if isinstance(entry, dict) and TOKEN_PATTERN.fullmatch(entry.get("token", "")):
        (pending_dir() / f'{entry["token"]}.bin').unlink(missing_ok=True)
        if settings.VISOR_ORIGINAL_STORAGE == "database":
            PendingContent.objects.filter(token=entry["token"]).delete()


def stage(request, uploaded, *, target_document_id=None) -> None:
    clear(request)
    directory = pending_dir()
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for candidate in directory.glob("*.bin"):
        if now - candidate.stat().st_mtime > MAX_AGE:
            candidate.unlink(missing_ok=True)
    token = secrets.token_hex(16)
    with (directory / f"{token}.bin").open("xb") as stream:
        for chunk in uploaded.chunks():
            stream.write(chunk)
    if settings.VISOR_ORIGINAL_STORAGE == "database":
        try:
            PendingContent.objects.filter(created_at__lt=timezone.now() - timedelta(seconds=MAX_AGE)).delete()
            PendingContent.objects.create(
                token=token, content=(directory / f"{token}.bin").read_bytes(), created_at=timezone.now()
            )
        except Exception:
            (directory / f"{token}.bin").unlink(missing_ok=True)
            raise
    request.session[SESSION_KEY] = {
        "token": token, "filename": uploaded.name,
        "target_document_id": target_document_id,
    }


def set_target(request, document_id: int) -> None:
    if get(request) is None:
        raise ValueError("La carga pendiente caducó. Seleccione el archivo de nuevo.")
    entry = request.session[SESSION_KEY]
    entry["target_document_id"] = document_id
    request.session[SESSION_KEY] = entry


def get(request):
    entry = request.session.get(SESSION_KEY)
    if not isinstance(entry, dict) or not TOKEN_PATTERN.fullmatch(entry.get("token", "")):
        return None
    path = pending_dir() / f'{entry["token"]}.bin'
    if settings.VISOR_ORIGINAL_STORAGE == "database":
        saved = PendingContent.objects.filter(token=entry["token"]).values("created_at").first()
        if not saved or saved["created_at"] < timezone.now() - timedelta(seconds=MAX_AGE):
            clear(request)
            return None
        if not path.is_file():
            content = PendingContent.objects.values_list("content", flat=True).get(token=entry["token"])
            pending_dir().mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(content))
    elif not path.is_file():
        clear(request)
        return None
    return entry["filename"], path


def process(request, service, *, mode="", comparison_keys=None):
    pending = get(request)
    if pending is None:
        raise ValueError("La carga pendiente caducó. Seleccione el archivo de nuevo.")
    filename, path = pending
    target_document_id = request.session[SESSION_KEY].get("target_document_id")
    with path.open("rb") as stream:
        return service(
            filename=filename, content=File(stream), mode=mode,
            comparison_keys=comparison_keys, target_document_id=target_document_id,
        )
