import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.db.models.functions import Lower
from django.utils import timezone

from documents.models import Document, Version

from documents.services.comparison import (
    compare_cached_versions,
    comparison_setup,
    get_cached_change_records,
    normalized_row_keys,
)

from documents.services.parsing import (
    read_sheets,
    build_schema_profile,
    compare_schema_profiles,
)
from documents.services.cache import build_cache_for_version as build_cache
from documents.services.report import sheet_report, workbook_report

ALLOWED = {".xlsx", ".xls", ".csv"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
logger = logging.getLogger(__name__)


def uploads_dir() -> Path:
    return Path(settings.MEDIA_ROOT)


def cache_dir() -> Path:
    return Path(getattr(settings, "VISOR_CACHE_ROOT", Path(settings.BASE_DIR) / "data" / "cache"))


class HTTPException(Exception):
    """Error de negocio que las vistas Django convierten en respuesta JSON."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def api_timestamp(value) -> str:
    return value.isoformat(timespec="seconds") if hasattr(value, "isoformat") else value.replace(" ", "T", 1)


def version_row(version: Version | None) -> dict | None:
    """Keep the existing response shape while metadata moves to Django models."""
    if version is None:
        return None
    row = {field.attname: getattr(version, field.attname) for field in Version._meta.fields}
    for name in ("import_options", "schema_info", "comparison_keys", "change_summary"):
        row[name] = json.dumps(row[name], ensure_ascii=False) if row[name] is not None else None
    return row


def get_version_row(vid: int) -> dict | None:
    return version_row(Version.objects.filter(pk=vid).first())


def _stage_file(content, destination: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    chunks = content.chunks() if hasattr(content, "chunks") else (content,)
    with destination.open("wb") as stream:
        for chunk in chunks:
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise HTTPException(413, "El archivo supera el tamaño máximo permitido de 50 MB.")
            digest.update(chunk)
            stream.write(chunk)
    if total == 0:
        raise HTTPException(400, "El archivo está vacío (0 bytes).")
    return digest.hexdigest()


def _publish(source: Path, destination: Path, sha256: str | None = None) -> bool:
    """Create a final path atomically without replacing another upload."""
    try:
        os.link(source, destination)
        return True
    except FileExistsError:
        if sha256 and hashlib.sha256(destination.read_bytes()).hexdigest() != sha256:
            raise RuntimeError(f"El archivo existente no coincide con su hash: {destination.name}")
        return False


def schema_profile_for_version(version) -> dict:
    """Returns a stored profile or reconstructs it for a pre-profile history entry."""
    try:
        profile = json.loads(version["schema_info"]) if version["schema_info"] else None
    except (TypeError, json.JSONDecodeError):
        profile = None
    if isinstance(profile, dict) and isinstance(profile.get("sheets"), list):
        return profile

    path = uploads_dir() / version["stored_path"]
    options = json.loads(version["import_options"]) if version["import_options"] else {}
    sheets, _ = read_sheets(path, options)
    profile = build_schema_profile(sheets)
    Version.objects.filter(pk=version["id"]).update(schema_info=profile)
    return profile


def schema_changes_for_version(current: dict, previous: dict | None, summary: dict) -> list[dict]:
    saved = summary.get("schema_changes")
    if isinstance(saved, list):
        return saved
    if previous is None:
        return []
    try:
        return compare_schema_profiles(
            schema_profile_for_version(previous), schema_profile_for_version(current)
        )
    except (OSError, ValueError):
        logger.warning("No se pudo reconstruir la estructura entre las versiones %s y %s", previous["id"], current["id"])
        return []


def build_cache_for_version(sha256: str, path: Path, options: dict) -> Path:
    return build_cache(sha256, path, options, cache_dir())


def upload(
    filename: str,
    content,
    mode: str = "",
    header_row: Optional[int] = None,
    delimiter: Optional[str] = None,
    encoding: Optional[str] = None,
    comparison_keys: Optional[str] = None,
    target_document_id: Optional[int] = None,
):
    uploads_dir().mkdir(parents=True, exist_ok=True)
    cache_dir().mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Formato '{ext}' no soportado. Formatos admitidos: .xlsx, .xls, .csv")

    mode = mode if isinstance(mode, str) else ""
    if target_document_id is not None and mode != "new_version":
        raise HTTPException(400, "El documento de destino solo se admite para una nueva versión.")
    explicit_document = None
    if target_document_id is not None:
        try:
            target_document_id = int(target_document_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "El documento de destino no es válido.") from exc
        explicit_document = Document.objects.filter(pk=target_document_id).first() if target_document_id > 0 else None
        if explicit_document is None:
            raise HTTPException(404, "El documento de destino no existe.")
    user_opts = {}
    if isinstance(header_row, int):
        user_opts["header_row"] = header_row
    if isinstance(delimiter, str) and delimiter:
        user_opts["delimiter"] = delimiter
    if isinstance(encoding, str) and encoding:
        user_opts["encoding"] = encoding
    stem = Path(filename).stem

    with tempfile.TemporaryDirectory(prefix=".incoming-", dir=uploads_dir()) as incoming:
        staged_original = Path(incoming) / f"upload{ext}"
        sha = _stage_file(content, staged_original)
        duplicate = Version.objects.filter(sha256=sha).first()
        if duplicate:
            return {"status": "duplicate", "version_id": duplicate.pk}

        if target_document_id is not None:
            doc = explicit_document
        else:
            doc = Document.objects.annotate(lower_name=Lower("name")).filter(
                lower_name=stem.lower()
            ).first()
        try:
            sheets, detected_opts = read_sheets(staged_original, user_opts)
            profile = build_schema_profile(sheets)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"Error al procesar el archivo: {exc}") from exc

        if doc and mode not in ("new_version", "new_document"):
            previous = version_row(doc.versions.first())
            try:
                old_profile = schema_profile_for_version(previous) if previous else {"sheets": []}
                changes = compare_schema_profiles(old_profile, profile)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            return {
                "status": "name_match",
                "document": {"id": doc.pk, "name": doc.name},
                "schema_comparison": {"has_changes": bool(changes), "changes": changes},
            }

        if mode == "choose_destination" and not doc and Document.objects.exists():
            return {"status": "destination_required"}

        previous = version_row(doc.versions.first()) if doc and mode == "new_version" else None
        comparison_key_map = None
        change_summary = None
        if previous:
            old_profile = schema_profile_for_version(previous)
            schema_changes = compare_schema_profiles(old_profile, profile)
            if not comparison_keys:
                return {
                    "status": "comparison_setup_required",
                    "document": {"id": doc.pk, "name": doc.name},
                    "sheets": comparison_setup(old_profile, profile),
                    "schema_comparison": {"has_changes": bool(schema_changes), "changes": schema_changes},
                }
            try:
                comparison_key_map = normalized_row_keys(comparison_keys, old_profile, profile)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

        with tempfile.TemporaryDirectory(prefix=".building-", dir=cache_dir()) as building:
            try:
                staged_cache = build_cache(sha, staged_original, detected_opts, Path(building))
            except Exception as exc:
                raise HTTPException(
                    500, f"No se pudo preparar el archivo para consultarlo: {exc}"
                ) from exc

            if previous:
                previous_path = uploads_dir() / previous["stored_path"]
                previous_opts = json.loads(previous["import_options"]) if previous["import_options"] else {}
                build_cache_for_version(previous["sha256"], previous_path, previous_opts)
                try:
                    change_summary = compare_cached_versions(
                        previous["sha256"], sha, comparison_key_map, Path(building),
                        previous_cache_dir=cache_dir(),
                    )
                    change_summary["previous_version"] = previous["version_number"]
                    change_summary["schema_changes"] = schema_changes
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from exc
                except Exception as exc:
                    raise HTTPException(400, f"No se pudo comparar el contenido: {exc}") from exc

            final_original = uploads_dir() / f"{sha}{ext}"
            final_cache = cache_dir() / f"{sha}.db"
            for attempt in range(3):
                created_original = created_cache = False
                try:
                    with transaction.atomic():
                        duplicate = Version.objects.filter(sha256=sha).first()
                        if duplicate:
                            return {"status": "duplicate", "version_id": duplicate.pk}
                        now = timezone.now()
                        target_doc = doc if doc and mode == "new_version" else Document.objects.create(
                            name=stem if not doc else f"{stem} ({now.date().isoformat()})",
                            created_at=now,
                        )
                        if previous:
                            current_latest = target_doc.versions.first()
                            if current_latest is None or current_latest.pk != previous["id"]:
                                raise HTTPException(
                                    409, "La versión principal cambió; revise de nuevo la comparación."
                                )
                        number = (
                            target_doc.versions.aggregate(latest=Max("version_number"))["latest"] or 0
                        ) + 1
                        version = Version.objects.create(
                            document=target_doc,
                            version_number=number,
                            original_filename=filename,
                            stored_path=final_original.name,
                            sha256=sha,
                            uploaded_at=now,
                            sheet_count=len(sheets),
                            row_count=sum(len(frame) for frame in sheets.values()),
                            import_options=detected_opts,
                            schema_info=profile,
                            comparison_keys=comparison_key_map,
                            change_summary=change_summary,
                        )
                        created_original = _publish(staged_original, final_original, sha)
                        created_cache = _publish(staged_cache, final_cache)
                    return {
                        "status": "created",
                        "version_id": version.pk,
                        "import_options": detected_opts,
                        "change_summary": change_summary,
                        "is_primary": True,
                    }
                except (IntegrityError, OperationalError):
                    _cleanup_failed_publish(sha, final_original, final_cache,
                                            created_original, created_cache)
                    time.sleep(0.05 * (attempt + 1))
                    try:
                        duplicate = Version.objects.filter(sha256=sha).first()
                    except OperationalError:
                        duplicate = None
                    if duplicate:
                        return {"status": "duplicate", "version_id": duplicate.pk}
                    if attempt == 2:
                        raise HTTPException(
                            409, "La carga coincidi? con otra operaci?n; int?ntelo de nuevo."
                        )
                except Exception:
                    _cleanup_failed_publish(sha, final_original, final_cache,
                                            created_original, created_cache)
                    raise


def _cleanup_failed_publish(sha, original, cache, created_original, created_cache):
    if not (created_original or created_cache):
        return
    try:
        referenced = Version.objects.filter(sha256=sha).exists()
    except OperationalError:
        logger.warning("No se pudo verificar la limpieza de la carga %s", sha)
        return
    if not referenced:
        if created_original:
            original.unlink(missing_ok=True)
        if created_cache:
            cache.unlink(missing_ok=True)


def list_documents():
    documents = []
    for document in Document.objects.prefetch_related("versions"):
        versions = list(document.versions.all())
        if not versions:
            continue
        documents.append({
            "id": document.pk,
            "name": document.name,
            "versions": [{
                "id": version.pk,
                "version_number": version.version_number,
                "original_filename": version.original_filename,
                "uploaded_at": api_timestamp(version.uploaded_at),
                "sheet_count": version.sheet_count,
                "row_count": version.row_count,
                "is_primary": index == 0,
            } for index, version in enumerate(versions)],
        })
    return documents


def list_library(
    q: str = "",
    sort: str = "recent",
    page: int = 0,
    page_size: int = 15,
    version_limit: int | None = None,
):
    """Return one page of documents, optionally limiting each history preview."""
    if sort not in {"recent", "name", "rows"}:
        raise HTTPException(400, "Orden no v?lido")

    latest = Version.objects.filter(document_id=OuterRef("pk")).order_by("-version_number", "-id")
    documents = Document.objects.annotate(
        primary_id=Subquery(latest.values("id")[:1]),
        version_number=Subquery(latest.values("version_number")[:1]),
        uploaded_at=Subquery(latest.values("uploaded_at")[:1]),
        sheet_count=Subquery(latest.values("sheet_count")[:1]),
        row_count=Subquery(latest.values("row_count")[:1]),
        primary_filename=Subquery(latest.values("original_filename")[:1]),
        version_count=Count("versions"),
    ).filter(primary_id__isnull=False)
    query = q.strip()[:120]
    if query:
        matching_files = Version.objects.filter(original_filename__icontains=query).values("document_id")
        documents = documents.filter(Q(name__icontains=query) | Q(pk__in=matching_files))
    order = {
        "recent": ("-uploaded_at", "-id"),
        "name": (Lower("name"), "-id"),
        "rows": ("-row_count", "-id"),
    }[sort]
    total = documents.count()
    selected = list(documents.order_by(*order)[page * page_size:(page + 1) * page_size])
    items = [{
        "id": document.pk,
        "name": document.name,
        "primary_id": document.primary_id,
        "version_number": document.version_number,
        "uploaded_at": api_timestamp(document.uploaded_at),
        "sheet_count": document.sheet_count,
        "row_count": document.row_count,
        "primary_filename": document.primary_filename,
        "version_count": document.version_count,
        "versions": [],
    } for document in selected]
    by_document = {item["id"]: item for item in items}
    if version_limit is None:
        versions = Version.objects.filter(document_id__in=by_document).order_by(
            "-version_number", "-id"
        )
    else:
        versions = (
            version
            for item in items
            for version in Version.objects.filter(document_id=item["id"]).order_by(
                "-version_number", "-id"
            )[:max(0, version_limit)]
        )
    for version in versions:
        by_document[version.document_id]["versions"].append({
            "id": version.pk,
            "version_number": version.version_number,
            "original_filename": version.original_filename,
            "uploaded_at": api_timestamp(version.uploaded_at),
            "sheet_count": version.sheet_count,
            "row_count": version.row_count,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_version(vid: int):
    v = get_version_row(vid)
    path = uploads_dir() / v["stored_path"] if v else None
    if not v or not path.exists():
        raise HTTPException(404, "Archivo no encontrado")

    opts = json.loads(v["import_options"]) if v["import_options"] else {}
    cache_path = build_cache_for_version(v["sha256"], path, opts)

    ccon = sqlite3.connect(cache_path)
    ccon.row_factory = sqlite3.Row
    sheets_meta = ccon.execute("SELECT * FROM _sheets ORDER BY rowid ASC").fetchall()
    ccon.close()

    sheets = []
    for sm in sheets_meta:
        cols = json.loads(sm["columns_json"])
        num_cols = json.loads(sm["numeric_cols_json"])
        date_cols = json.loads(sm["date_cols_json"])
        column_types = json.loads(sm["column_types_json"])
        sheets.append({
            "name": sm["sheet_name"],
            "columns": cols,
            "row_count": sm["row_count"],
            "numeric_columns": num_cols,
            "date_columns": date_cols,
            "column_types": column_types,
        })

    latest = Version.objects.filter(document_id=v["document_id"]).aggregate(
        version_number=Max("version_number")
    )
    try:
        change_summary = json.loads(v["change_summary"]) if v["change_summary"] else None
    except (TypeError, json.JSONDecodeError):
        change_summary = None
    history_versions = list(Version.objects.filter(
        document_id=v["document_id"], version_number__lte=v["version_number"]
    ).order_by("version_number", "id"))
    versions_by_number = {version.version_number: version for version in history_versions}
    change_history = []
    for version in history_versions:
        summary = version.change_summary
        if not isinstance(summary, dict):
            continue
        prior = versions_by_number.get(summary.get("previous_version"))
        schema_changes = summary.get("schema_changes")
        if not isinstance(schema_changes, list):
            schema_changes = schema_changes_for_version(
                version_row(version), version_row(prior), summary
            )
        change_history.append({
            "id": version.pk,
            "version_number": version.version_number,
            "previous_version": summary.get("previous_version"),
            "uploaded_at": api_timestamp(version.uploaded_at),
            "sheets": summary.get("sheets", []),
            "schema_changes": schema_changes,
        })
    return {
        "id": v["id"],
        "document_id": v["document_id"],
        "document_name": Document.objects.filter(pk=v["document_id"]).values_list("name", flat=True).first(),
        "version_number": v["version_number"],
        "filename": v["original_filename"],
        "import_options": opts,
        "is_primary": latest["version_number"] == v["version_number"],
        "change_summary": change_summary,
        "change_history": change_history,
        "sheets": sheets,
    }


def get_version_rows(
    vid: int,
    sheet: str,
    page: int = 0,
    page_size: int = 100,
    q: Optional[str] = "",
    sort_col: Optional[int] = None,
    sort_dir: str = "asc",
    filters: Optional[str] = None,
):
    v = get_version_row(vid)
    if not v:
        raise HTTPException(404, "Versión no encontrada")

    path = uploads_dir() / v["stored_path"]
    opts = json.loads(v["import_options"]) if v["import_options"] else {}
    cache_path = build_cache_for_version(v["sha256"], path, opts)

    ccon = sqlite3.connect(cache_path)
    ccon.row_factory = sqlite3.Row
    sm = ccon.execute("SELECT * FROM _sheets WHERE sheet_name = ?", (sheet,)).fetchone()
    if not sm:
        ccon.close()
        raise HTTPException(404, f"Hoja '{sheet}' no encontrada")

    tbl = sm["table_name"]
    cols = json.loads(sm["columns_json"])
    total_rows = sm["row_count"]

    where_clauses = []
    params = []

    if q and q.strip():
        for term in q.strip().lower().split():
            where_clauses.append("__search LIKE ?")
            params.append(f"%{term}%")

    if filters:
        try:
            fdict = json.loads(filters)
            if isinstance(fdict, dict):
                for c_idx_str, fval in fdict.items():
                    if fval and str(fval).strip():
                        c_idx = int(c_idx_str)
                        if 0 <= c_idx < len(cols):
                            where_clauses.append(f"c{c_idx} LIKE ?")
                            params.append(f"%{str(fval).strip()}%")
        except Exception:
            pass

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    count_sql = f"SELECT COUNT(1) FROM {tbl}{where_sql}"
    filtered_rows = ccon.execute(count_sql, params).fetchone()[0]

    order_sql = " ORDER BY row_idx ASC"
    if sort_col is not None and 0 <= sort_col < len(cols):
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        order_sql = f" ORDER BY c{sort_col} {direction} NULLS LAST, row_idx ASC"

    offset = max(0, page * page_size)
    col_select = ", ".join([f"c{i}" for i in range(len(cols))]) if cols else "row_idx"
    data_sql = f"SELECT row_idx, {col_select} FROM {tbl}{where_sql}{order_sql} LIMIT ? OFFSET ?"
    data_params = params + [page_size, offset]

    rows = []
    for r in ccon.execute(data_sql, data_params).fetchall():
        r_dict = dict(r)
        r_idx = r_dict.pop("row_idx")
        rows.append({"n": r_idx, "r": [r_dict.get(f"c{i}") for i in range(len(cols))]})

    ccon.close()
    return {
        "sheet": sheet,
        "total_rows": total_rows,
        "filtered_rows": filtered_rows,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (filtered_rows + page_size - 1) // page_size),
        "columns": cols,
        "rows": rows,
    }


def get_version_changes(
    vid: int,
    sheet: Optional[str] = None,
    kind: str = "updated",
    page: int = 0,
    page_size: int = 50,
):
    if kind not in {"added", "updated", "removed"}:
        raise HTTPException(400, "El tipo de cambio debe ser added, updated o removed.")
    page = max(0, page)
    page_size = min(100, max(1, page_size))
    version = get_version_row(vid)
    if not version:
        raise HTTPException(404, "Versión no encontrada")
    try:
        summary = json.loads(version["change_summary"]) if version["change_summary"] else None
        keys_by_sheet = json.loads(version["comparison_keys"]) if version["comparison_keys"] else {}
    except (TypeError, json.JSONDecodeError):
        summary, keys_by_sheet = None, {}
    if not summary:
        return {
            "first_version": True,
            "sheets": [],
            "records": [],
            "total": 0,
            "page": page,
            "total_pages": 1,
        }

    previous_number = summary.get("previous_version")
    previous = version_row(Version.objects.filter(
        document_id=version["document_id"], version_number=previous_number
    ).order_by("-id").first())
    sheets = summary.get("sheets", [])
    schema_changes = schema_changes_for_version(version, previous, summary)
    selected_sheet = sheet or (sheets[0]["sheet"] if sheets else None)
    selected_summary = next((item for item in sheets if item["sheet"] == selected_sheet), None)
    if selected_sheet and not selected_summary:
        raise HTTPException(404, f"No hay comparación para la hoja '{selected_sheet}'.")
    if not previous:
        return {
            "first_version": False,
            "details_available": False,
            "previous_version": previous_number,
            "sheets": sheets,
            "schema_changes": schema_changes,
            "selected_sheet": selected_sheet,
            "records": [],
            "total": selected_summary.get(kind, 0) if selected_summary else 0,
            "page": page,
            "total_pages": 1,
            "kind": kind,
        }

    total, records = get_cached_change_records(
        previous["sha256"],
        version["sha256"],
        selected_sheet,
        keys_by_sheet.get(selected_sheet, []),
        kind,
        page,
        page_size,
        cache_dir(),
    ) if selected_summary else (0, [])
    return {
        "first_version": False,
        "details_available": True,
        "previous_version": previous_number,
        "sheets": sheets,
        "schema_changes": schema_changes,
        "selected_sheet": selected_sheet,
        "kind": kind,
        "records": records,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


def get_version_summary(
    vid: int,
    sheet: str,
    category_col: Optional[int] = None,
    measure_col: Optional[int] = None,
    stat_op: str = "sum",
    date_period: str = "month",
    sort_chart: str = "desc",
    chart_page: Optional[int] = None,
    other_page: Optional[int] = None,
    page_size: int = 10,
):
    v = get_version_row(vid)
    if not v:
        raise HTTPException(404, "Versión no encontrada")

    path = uploads_dir() / v["stored_path"]
    opts = json.loads(v["import_options"]) if v["import_options"] else {}
    cache_path = build_cache_for_version(v["sha256"], path, opts)

    ccon = sqlite3.connect(cache_path)
    ccon.row_factory = sqlite3.Row
    sm = ccon.execute("SELECT * FROM _sheets WHERE sheet_name = ?", (sheet,)).fetchone()
    if not sm:
        ccon.close()
        raise HTTPException(404, f"Hoja '{sheet}' no encontrada")

    tbl = sm["table_name"]
    cols = json.loads(sm["columns_json"])
    num_cols = json.loads(sm["numeric_cols_json"])
    date_cols = json.loads(sm["date_cols_json"])
    column_types = json.loads(sm["column_types_json"])
    total_rows = sm["row_count"]
    mixed_column_count = sum(1 for item in column_types if item["type"] == "mixed")
    details = sheet_report(ccon, sm)

    if total_rows == 0 or len(cols) == 0:
        ccon.close()
        return {
            "metrics": [
                ["Registros", 0],
                ["Columnas", len(cols)],
                ["Columnas numéricas", len(num_cols)],
                ["Columnas mixtas", mixed_column_count],
            ],
            "chart": {
                "title": "Sin datos en la hoja",
                "description": "",
                "values": [],
                "other_details": [],
                "omitted_non_numeric": 0,
                "omitted_nulls": 0,
            },
            "details": details,
        }

    metrics = [
        ["Registros", total_rows],
        ["Columnas", len(cols)],
        ["Columnas mixtas", mixed_column_count],
    ]
    if stat_op != "count" and measure_col is not None and 0 <= measure_col < len(cols) and measure_col in num_cols:
        m_col_name = cols[measure_col]
        stats = ccon.execute(
            f"SELECT SUM(c{measure_col}), AVG(c{measure_col}), MIN(c{measure_col}), MAX(c{measure_col}) FROM {tbl} WHERE typeof(c{measure_col}) IN ('integer', 'real')"
        ).fetchone()
        if stats[1] is not None:
            metrics.extend([
                [f"Suma ({m_col_name})", stats[0]],
                [f"Promedio ({m_col_name})", stats[1]],
                [f"Rango ({m_col_name})", f"{stats[2]:,.2f} a {stats[3]:,.2f}"],
            ])
    else:
        metrics.append(["Columnas numéricas", len(num_cols)])

    values = []
    other_details = []
    values_total = 0
    other_total = 0
    chart_page_used = 0
    other_page_used = 0
    omitted_nulls = 0
    omitted_non_numeric = 0
    chart_title = "Distribución de datos"
    chart_desc = ""

    if category_col is not None and 0 <= category_col < len(cols):
        cat_name = cols[category_col]
        is_date = category_col in date_cols

        if is_date:
            if date_period == "year":
                grp_expr = f"substr(c{category_col}, 1, 4)"
            elif date_period == "month":
                grp_expr = f"substr(c{category_col}, 1, 7)"
            else:
                grp_expr = f"substr(c{category_col}, 1, 10)"
        else:
            grp_expr = f"c{category_col}"

        if stat_op == "count":
            sql_fn = "COUNT(1)"
            op_title = "Recuento de registros"
            where_calc = ""
        elif measure_col is not None and 0 <= measure_col < len(cols) and measure_col in num_cols:
            meas_name = cols[measure_col]
            omitted_nulls = ccon.execute(f"SELECT COUNT(1) FROM {tbl} WHERE c{measure_col} IS NULL").fetchone()[0]
            omitted_non_numeric = ccon.execute(f"SELECT COUNT(1) FROM {tbl} WHERE typeof(c{measure_col}) = 'text'").fetchone()[0]

            op_map = {
                "sum": (f"SUM(c{measure_col})", f"Suma de {meas_name}"),
                "avg": (f"AVG(c{measure_col})", f"Promedio de {meas_name}"),
                "min": (f"MIN(c{measure_col})", f"Valor mínimo de {meas_name}"),
                "max": (f"MAX(c{measure_col})", f"Valor máximo de {meas_name}"),
            }
            sql_fn, op_title = op_map.get(stat_op, (f"SUM(c{measure_col})", f"Suma de {meas_name}"))
            where_calc = f"WHERE typeof(c{measure_col}) IN ('integer', 'real')"
        else:
            sql_fn = "COUNT(1)"
            op_title = "Recuento de registros"
            where_calc = ""

        aggregation_op = stat_op if where_calc else "count"
        weight_expr = f"SUM(c{measure_col}) AS weighted_sum, COUNT(1) AS weight" if stat_op == "avg" and measure_col is not None and where_calc else "NULL AS weighted_sum, COUNT(1) AS weight"
        query = f"""
            SELECT {grp_expr} as label, {sql_fn} as val, {weight_expr}
            FROM {tbl}
            {where_calc}
            GROUP BY label
        """
        compact = chart_page is not None or other_page is not None
        if compact:
            group_total = ccon.execute(f"SELECT COUNT(*) FROM ({query})").fetchone()[0]
            order = "ORDER BY CAST(label AS TEXT)" if sort_chart == "alpha" else f"ORDER BY val {'ASC' if sort_chart == 'asc' else 'DESC'}, CAST(label AS TEXT)"
            ordered = f"SELECT * FROM ({query}) {order}"
            if group_total > 8 and sort_chart != "alpha":
                top_rows = ccon.execute(f"{ordered} LIMIT 7").fetchall()
                rest_query = f"SELECT * FROM ({ordered}) LIMIT -1 OFFSET 7"
                rest_stats = ccon.execute(
                    f"SELECT SUM(val), MIN(val), MAX(val), SUM(weighted_sum), SUM(weight) FROM ({rest_query})"
                ).fetchone()
                if aggregation_op == "min":
                    other_val = rest_stats[1]
                elif aggregation_op == "max":
                    other_val = rest_stats[2]
                elif aggregation_op == "avg":
                    other_val = rest_stats[3] / rest_stats[4] if rest_stats[4] else 0
                else:
                    other_val = rest_stats[0]
                raw_groups = top_rows
                other_total = group_total - 7
                other_page_used = min(max(other_page or 0, 0), max(0, (other_total - 1) // page_size))
                other_rows = ccon.execute(
                    f"{ordered} LIMIT ? OFFSET ?", (page_size, 7 + other_page_used * page_size)
                ).fetchall()
                other_details = [[_chart_group_label(row[0]), float(row[1])] for row in other_rows]
                values_total = 8
            else:
                values_total = group_total
                chart_page_used = min(max(chart_page or 0, 0), max(0, (group_total - 1) // page_size))
                raw_groups = ccon.execute(
                    f"{ordered} LIMIT ? OFFSET ?", (page_size, chart_page_used * page_size)
                ).fetchall()
        else:
            raw_groups = ccon.execute(query).fetchall()
        groups_list = []
        for r in raw_groups:
            lbl = _chart_group_label(r[0])
            val = float(r[1]) if r[1] is not None else 0.0
            groups_list.append([lbl, val, r[2], r[3]])

        if not compact:
            if sort_chart == "desc":
                groups_list.sort(key=lambda x: x[1], reverse=True)
            elif sort_chart == "asc":
                groups_list.sort(key=lambda x: x[1])
            else:
                groups_list.sort(key=lambda x: str(x[0]))

        if compact and other_total:
            values = [[x[0], x[1]] for x in groups_list] + [["Otros", round(other_val, 2)]]
        elif len(groups_list) > 8 and sort_chart != "alpha":
            top = groups_list[:7]
            rest = groups_list[7:]
            if aggregation_op == "min":
                other_val = min(x[1] for x in rest)
            elif aggregation_op == "max":
                other_val = max(x[1] for x in rest)
            elif aggregation_op == "avg":
                numerator = sum(x[2] for x in rest)
                denominator = sum(x[3] for x in rest)
                other_val = numerator / denominator if denominator else 0
            else:
                other_val = sum(x[1] for x in rest)
            values = [[x[0], x[1]] for x in top] + [["Otros", round(other_val, 2)]]
            other_details = [[x[0], x[1]] for x in rest]
            other_total = len(other_details)
            values_total = len(values)
        else:
            values = [[x[0], x[1]] for x in groups_list]
            if not compact:
                values_total = len(values)

        period_note = f" ({date_period})" if is_date else ""
        chart_title = f"{op_title} por {cat_name}{period_note}"
        included = total_rows - omitted_nulls - omitted_non_numeric if where_calc else total_rows
        chart_desc = f"Calculado con {included:,} de {total_rows:,} registros."

    elif stat_op == "count" or measure_col is None:
        values = [["Todos los registros", total_rows]]
        values_total = 1
        chart_title = "Recuento de registros"
        chart_desc = "Una fila equivale a un registro de la hoja."

    elif measure_col is not None and 0 <= measure_col < len(cols) and measure_col in num_cols:
        meas_name = cols[measure_col]
        stats = ccon.execute(
            f"SELECT MIN(c{measure_col}), MAX(c{measure_col}), COUNT(1) FROM {tbl} WHERE typeof(c{measure_col}) IN ('integer', 'real')"
        ).fetchone()
        min_v = stats[0]
        max_v = stats[1]
        cnt_v = stats[2]
        omitted_nulls = ccon.execute(f"SELECT COUNT(1) FROM {tbl} WHERE c{measure_col} IS NULL").fetchone()[0]
        omitted_non_numeric = ccon.execute(f"SELECT COUNT(1) FROM {tbl} WHERE typeof(c{measure_col}) = 'text'").fetchone()[0]

        if min_v is not None and max_v is not None and cnt_v > 0:
            bin_count = min(6, cnt_v)
            size = (max_v - min_v) / bin_count if max_v != min_v else 1.0
            bins = []
            for i in range(bin_count):
                b_from = min_v + size * i
                b_to = max_v if i == bin_count - 1 else min_v + size * (i + 1)
                b_cnt = ccon.execute(
                    f"SELECT COUNT(1) FROM {tbl} WHERE typeof(c{measure_col}) IN ('integer', 'real') AND c{measure_col} >= ? AND c{measure_col} {'<=' if i == bin_count - 1 else '<'} ?",
                    (b_from, b_to)
                ).fetchone()[0]
                bins.append([f"{b_from:,.2f} – {b_to:,.2f}", b_cnt])
            values = bins
            values_total = len(values)

        chart_title = f"Distribución de frecuencias: {meas_name}"
        chart_desc = "Cantidad de registros agrupados en intervalos numéricos."

    ccon.close()
    return {
        "metrics": metrics,
        "chart": {
            "title": chart_title,
            "description": chart_desc,
            "values": values,
            "other_details": other_details,
            "values_total": values_total,
            "other_total": other_total,
            "chart_page": chart_page_used,
            "other_page": other_page_used,
            "omitted_non_numeric": omitted_non_numeric,
            "omitted_nulls": omitted_nulls,
        },
        "details": details,
    }


def _chart_group_label(value) -> str:
    if value is None:
        return "(Sin dato)"
    label = str(value)
    return "(Sin dato) [texto]" if label == "(Sin dato)" else label


def get_workbook_report(vid: int) -> dict:
    version = get_version_row(vid)
    if not version:
        raise HTTPException(404, "Versión no encontrada")
    source = uploads_dir() / version["stored_path"]
    options = json.loads(version["import_options"]) if version["import_options"] else {}
    cache_path = build_cache_for_version(version["sha256"], source, options)
    return workbook_report(cache_path)


def delete_version(vid: int):
    with transaction.atomic():
        version = Version.objects.filter(pk=vid).first()
        if version is None:
            raise HTTPException(404, "Versión no encontrada")
        document_id = version.document_id
        if Version.objects.filter(
            document_id=document_id, version_number__gt=version.version_number
        ).exists():
            raise HTTPException(
                409,
                "No se puede eliminar una versión histórica porque se perdería el historial de cambios. Elimina primero las versiones posteriores.",
            )
        stored_path = version.stored_path
        sha = version.sha256
        version.delete()
        if not Version.objects.filter(document_id=document_id).exists():
            Document.objects.filter(pk=document_id).delete()

    pending = False
    for path in (uploads_dir() / stored_path, cache_dir() / f"{sha}.db"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("No se pudo limpiar el archivo de la versión eliminada: %s", path)
            pending = True
    return {"ok": True, "cleanup_pending": True} if pending else {"ok": True}


