"""Server-rendered pages. JSON endpoints remain for existing API clients."""

import json
from pathlib import Path
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .forms import ComparisonKeysForm, DestinationSelectionForm, DocumentVersionsForm, LibraryForm, UploadDecisionForm, UploadForm, ViewerForm
from .models import Document, Version
from . import pending_uploads
from .services import history as workbook


HISTORY_PAGE_SIZE = 8
CHART_PAGE_SIZE = 10
OTHER_PAGE_SIZE = 10


def _service_error(exc):
    if exc.status_code == 404:
        raise Http404(exc.detail) from exc
    return HttpResponse(exc.detail, status=exc.status_code)


def _page_url(request, key, page, anchor=""):
    params = request.GET.copy()
    params[key] = str(page)
    suffix = f"#{anchor}" if anchor else ""
    return f"{request.path}?{params.urlencode()}{suffix}"


def _pager(request, key, page, total_pages, label="Paginación", anchor=""):
    return {
        "number": page + 1,
        "pages": total_pages,
        "label": label,
        "previous": _page_url(request, key, page - 1, anchor) if page > 0 else None,
        "next": _page_url(request, key, page + 1, anchor) if page + 1 < total_pages else None,
    }


@ensure_csrf_cookie
@require_GET
def library(request):
    form = LibraryForm(request.GET)
    if not form.is_valid():
        return HttpResponseBadRequest("Los parámetros de búsqueda no son válidos.")
    values = form.cleaned_data
    result = workbook.list_library(q=values["q"], sort=values["sort"], page=values["page"], page_size=10, version_limit=3)
    pages = max(1, (result["total"] + result["page_size"] - 1) // result["page_size"])
    if values["page"] >= pages:
        return redirect(f'{reverse("documents:library")}?{urlencode({"q": values["q"], "sort": values["sort"], "page": pages - 1})}')
    for item in result["items"]:
        item["file_type"] = Path(item["primary_filename"]).suffix.lstrip(".").upper() or "ARCHIVO"
        item["versions_url"] = f'{reverse("documents:document_versions", args=[item["id"]])}?{urlencode({"q": values["q"], "sort": values["sort"], "page": values["page"]})}'
        item["has_more_versions"] = item["version_count"] > len(item["versions"])
    return render(request, "documents/library.html", {
        "form": form,
        "items": result["items"],
        "total": result["total"],
        "pager": _pager(request, "page", values["page"], pages),
        "q": values["q"],
        "sort": values["sort"],
    })


@require_GET
def document_versions(request, doc_id):
    form = DocumentVersionsForm(request.GET)
    if not form.is_valid():
        return HttpResponseBadRequest("Los parámetros de consulta no son válidos.")
    values = form.cleaned_data
    document = get_object_or_404(Document, pk=doc_id)
    versions = document.versions.order_by("-version_number", "-id")
    page_obj = Paginator(versions, 10).get_page(values["versions_page"] + 1)
    library_url = f'{reverse("documents:library")}?{urlencode({"q": values["q"], "sort": values["sort"], "page": values["page"]})}'
    return render(request, "documents/document_versions.html", {
        "document": document,
        "versions": page_obj.object_list,
        "primary_id": versions.values_list("id", flat=True).first(),
        "total": page_obj.paginator.count,
        "library_url": library_url,
        "pager": _pager(request, "versions_page", page_obj.number - 1, page_obj.paginator.num_pages, "Páginas de versiones", "versions-list"),
    })


def _chart_items(chart):
    values = chart.get("values") or []
    maximum = max((abs(float(value)) for _, value in values), default=0)
    return [
        {"label": label, "value": value, "percent": round(abs(float(value)) * 100 / maximum) if maximum > 0 else 0,
         "negative": float(value) < 0}
        for label, value in values
    ]


def _change_records(records):
    prepared = []
    for record in records:
        prepared.append({
            "keys": list((record.get("keys") or {}).items()),
            "changes": record.get("changes"),
            "values": list((record.get("values") or {}).items()),
        })
    return prepared


def _schema_description(change):
    kind = change.get("kind")
    sheet = change.get("sheet", "")
    column = change.get("column", "")
    if kind == "sheet_added":
        return f"Se agregó la hoja «{sheet}»."
    if kind == "sheet_removed":
        return f"Se eliminó la hoja «{sheet}»."
    if kind == "column_added":
        return f"Se agregó la columna «{column}» en «{sheet}»."
    if kind == "column_removed":
        return f"Se eliminó la columna «{column}» en «{sheet}»."
    if kind == "possible_column_rename":
        return f'Posible renombre en «{sheet}»: «{change.get("from", "")}» → «{change.get("to", "")}».'
    if kind == "column_type_changed":
        return f'Cambió el tipo estimado de «{column}» en «{sheet}»: {change.get("from", "")} → {change.get("to", "")}.'
    if kind == "column_order_changed":
        return f"Cambió el orden de las columnas en «{sheet}»."
    return "Se detectó un cambio en la estructura."


@require_GET
def version(request, vid):
    try:
        version_data = workbook.get_version(vid)
        workbook_overview = workbook.get_workbook_report(vid) if request.GET.get("view", "summary") == "summary" else None
    except workbook.HTTPException as exc:
        return _service_error(exc)
    if workbook_overview:
        report_by_name = {item["name"]: item for item in workbook_overview["sheets"]}
        for item in version_data["sheets"]:
            detail = report_by_name.get(item["name"], {})
            item["suggested_category"] = detail.get("suggested_category")
            item["suggested_measure"] = detail.get("suggested_measure")
            item["measure_candidates"] = detail.get("measure_candidates", item["numeric_columns"])
    form = ViewerForm(request.GET, sheets=version_data["sheets"], history=version_data["change_history"])
    if not form.is_valid():
        return HttpResponseBadRequest("Los parámetros de consulta no son válidos.")
    values = form.cleaned_data
    selected_sheet = next((item for item in version_data["sheets"] if item["name"] == values["sheet"]), None)
    view = values["view"]
    context = {
        "file": version_data,
        "workbook_report": workbook_overview,
        "form": form,
        "view": view,
        "sheet": selected_sheet,
        "selected_sheet": values["sheet"],
        "selected_change": values["change"],
        "q": values["q"],
        "sort_dir": values["sort_dir"],
        "sort_col": values.get("sort_col", ""),
        "category_col": values["category_col"],
        "measure_col": values["measure_col"],
        "stat_op": values["stat_op"],
        "date_period": values["date_period"],
        "sort_chart": values["sort_chart"],
        "kind": values["kind"],
        "change_sheet": values["change_sheet"],
        "sheet_links": [
            {"name": item["name"], "url": f'{reverse("documents:version", args=[vid])}?{urlencode({"view": view, "sheet": item["name"]})}'}
            for item in version_data["sheets"]
        ],
        "view_links": [
            {"name": name, "label": label, "url": f'{reverse("documents:version", args=[vid])}?{urlencode({"view": name, "sheet": values["sheet"]})}'}
            for name, label in (("summary", "Resumen"), ("data", "Datos"), ("changes", "Cambios"))
            if name != "changes" or version_data["change_history"]
        ],
    }
    try:
        if view == "data" and selected_sheet:
            filters = {
                str(i): values[f"filter_{i}"]
                for i in range(len(selected_sheet["columns"])) if values.get(f"filter_{i}")
            }
            result = workbook.get_version_rows(
                vid, selected_sheet["name"], page=values["page"], page_size=25, q=values["q"],
                sort_col=int(values["sort_col"]) if values.get("sort_col") else None,
                sort_dir=values["sort_dir"], filters=json.dumps(filters) if filters else None,
            )
            if values["page"] >= result["total_pages"]:
                return redirect(_page_url(request, "page", result["total_pages"] - 1))
            context["rows"] = result
            context["pager"] = _pager(request, "page", values["page"], result["total_pages"], "Páginas de registros", "grid")
            context["filter_fields"] = [
                {"index": i, "label": label, "value": values.get(f"filter_{i}", "")}
                for i, label in enumerate(selected_sheet["columns"])
            ]
        elif view == "summary" and selected_sheet:
            result = workbook.get_version_summary(
                vid, selected_sheet["name"],
                category_col=int(values["category_col"]) if values["category_col"] else None,
                measure_col=int(values["measure_col"]) if values["measure_col"] else None,
                stat_op=values["stat_op"], date_period=values["date_period"], sort_chart=values["sort_chart"],
                chart_page=values["chart_page"], other_page=values["other_page"],
            )
            context["summary"] = result
            context["summary_metrics"] = [
                (label, f"{value:,.2f}" if label.startswith(("Suma (", "Promedio (")) and isinstance(value, (int, float)) else value)
                for label, value in result["metrics"]
            ]
            context["chart_items"] = _chart_items(result["chart"])
            chart_total_pages = max(1, (result["chart"].get("values_total", 0) + CHART_PAGE_SIZE - 1) // CHART_PAGE_SIZE)
            context["chart_pager"] = _pager(request, "chart_page", result["chart"].get("chart_page", 0), chart_total_pages, "Páginas del gráfico", "chart-results")
            context["other_details"] = result["chart"].get("other_details") or []
            context["other_count"] = result["chart"].get("other_total", 0)
            context["other_open"] = "other_page" in request.GET
            other_total_pages = max(1, (context["other_count"] + OTHER_PAGE_SIZE - 1) // OTHER_PAGE_SIZE)
            context["other_pager"] = _pager(request, "other_page", result["chart"].get("other_page", 0), other_total_pages, "Páginas del desglose de Otros", "other-details")
            context["category_options"] = [(str(i), name) for i, name in enumerate(selected_sheet["columns"])]
            context["measure_options"] = [(str(i), selected_sheet["columns"][i]) for i in selected_sheet.get("measure_candidates", selected_sheet["numeric_columns"])]
            context["is_date_category"] = values["category_col"] != "" and int(values["category_col"]) in selected_sheet["date_columns"]
        elif view == "changes":
            history = version_data["change_history"]
            for step in history:
                for schema_change in step.get("schema_changes", []):
                    schema_change["description"] = _schema_description(schema_change)
            change = next((item for item in history if str(item["id"]) == values["change"]), None)
            history_items = []
            for item in reversed(history):
                totals = {kind: sum(sheet.get(kind, 0) for sheet in item["sheets"]) for kind in ("added", "updated", "removed")}
                history_items.append({**item, "totals": totals})
            for index, item in enumerate(history_items):
                item["url"] = f'{reverse("documents:version", args=[vid])}?{urlencode({"view": "changes", "sheet": values["sheet"], "history_page": index // HISTORY_PAGE_SIZE, "change": item["id"]})}'
            selected_index = next((index for index, item in enumerate(history_items) if str(item["id"]) == values["change"]), 0)
            requested_page = values["history_page"] if "history_page" in request.GET else selected_index // HISTORY_PAGE_SIZE
            history_page = Paginator(history_items, HISTORY_PAGE_SIZE).get_page(requested_page + 1)
            context["history"] = list(history_page.object_list)
            context["history_total"] = len(history_items)
            if context["history"] and "history_page" in request.GET and all(str(item["id"]) != values["change"] for item in context["history"]):
                change = context["history"][0]
                values["change"] = str(change["id"])
                values["change_sheet"] = change["sheets"][0]["sheet"] if change["sheets"] else ""
                selected_summary = change["sheets"][0] if change["sheets"] else {}
                values["kind"] = next((kind for kind in ("updated", "added", "removed") if selected_summary.get(kind, 0)), "updated")
                values["change_page"] = 0
                context.update(selected_change=values["change"], change_sheet=values["change_sheet"], kind=values["kind"])
            def history_page_url(number):
                target = history_items[number * HISTORY_PAGE_SIZE]
                return f'{target["url"]}#history-steps'
            context["history_pager"] = {
                "number": history_page.number,
                "pages": history_page.paginator.num_pages,
                "label": "Páginas del historial de cambios",
                "previous": history_page_url(history_page.number - 2) if history_page.has_previous() else None,
                "next": history_page_url(history_page.number) if history_page.has_next() else None,
            }
            context["comparison"] = change
            if change:
                result = workbook.get_version_changes(
                    change["id"], sheet=values["change_sheet"] or None,
                    kind=values["kind"], page=values["change_page"], page_size=20,
                )
                if values["change_page"] >= result["total_pages"]:
                    return redirect(_page_url(request, "change_page", result["total_pages"] - 1))
                context["changes"] = result
                context["change_records"] = _change_records(result["records"])
                context["change_pager"] = _pager(request, "change_page", values["change_page"], result["total_pages"], "Páginas de cambios", "change-results")
                context["change_sheet_options"] = [item["sheet"] for item in change["sheets"]]
                context["change_sheet_summary"] = next((item for item in change["sheets"] if item["sheet"] == values["change_sheet"]), None)
    except workbook.HTTPException as exc:
        return _service_error(exc)
    return render(request, "documents/version.html", context)


def _upload_response(request, *, stage="file", form=None, result=None, error="", status=200):
    result = result or {}
    if stage in {"decision", "keys"}:
        for change in result.get("schema_comparison", {}).get("changes", []):
            change["description"] = _schema_description(change)
    target_id = request.GET.get("document_id") if request.method == "GET" else request.POST.get("document_id")
    target_document = Document.objects.filter(pk=target_id).first() if str(target_id or "").isdigit() else None
    if stage == "file" and target_document is None and form is not None:
        selected = form.data.get("document_id") if form.is_bound else None
        target_document = Document.objects.filter(pk=selected).first() if str(selected or "").isdigit() else None
    context = {
        "stage": stage, "form": form or UploadForm(), "result": result, "error": error,
        "filename": (pending_uploads.get(request) or ("", None))[0],
        "target_document": target_document,
    }
    if stage == "destination":
        query = request.GET.get("q", "").strip()[:120]
        try:
            requested_page = max(0, int(request.GET.get("page", "0")))
        except ValueError:
            requested_page = 0
        first_page = workbook.list_library(q=query, sort="recent", page=requested_page, page_size=10, version_limit=0)
        page_count = max(1, (first_page["total"] + 9) // 10)
        page = min(requested_page, page_count - 1)
        listing = first_page if page == requested_page else workbook.list_library(q=query, sort="recent", page=page, page_size=10, version_limit=0)
        def destination_url(number):
            return f'{reverse("documents:upload")}?{urlencode({"stage": "destination", "q": query, "page": number})}#destination-list'
        context.update(
            destination_items=listing["items"], destination_q=query,
            destination_pager={
                "number": page + 1, "pages": page_count, "label": "Páginas de documentos",
                "previous": destination_url(page - 1) if page else None,
                "next": destination_url(page + 1) if page + 1 < page_count else None,
            },
        )
    return render(request, "documents/upload.html", context, status=status)


def _upload_result(request, result):
    if result["status"] in {"created", "duplicate"}:
        target_id = request.session.get(pending_uploads.SESSION_KEY, {}).get("target_document_id")
        pending_uploads.clear(request)
        if result["status"] == "created":
            messages.success(request, "Archivo guardado en el historial.")
        elif target_id and Version.objects.filter(pk=result["version_id"]).exclude(document_id=target_id).exists():
            messages.warning(request, "Este archivo ya pertenece a otro documento; no se añadió a la tarjeta elegida.")
        else:
            messages.info(request, "Este archivo ya estaba en el historial.")
        return redirect("documents:version", vid=result["version_id"])
    if result["status"] == "name_match":
        return _upload_response(request, stage="decision", result=result)
    if result["status"] == "destination_required":
        return _upload_response(request, stage="destination", result=result)
    if result["status"] == "comparison_setup_required":
        return _upload_response(request, stage="keys", result=result)
    return _upload_response(request, error="No se pudo completar la carga.", status=400)


@require_http_methods(["GET", "POST"])
def upload(request):
    if request.method == "GET":
        if request.GET.get("stage") == "destination" and pending_uploads.get(request) is not None:
            return _upload_response(request, stage="destination")
        pending_uploads.clear(request)
        target_id = request.GET.get("document_id")
        if target_id is not None:
            if not target_id.isdigit():
                raise Http404("El documento de destino no existe.")
            get_object_or_404(Document, pk=target_id)
        return _upload_response(request)
    action = request.POST.get("action", "upload")
    if action == "cancel":
        pending_uploads.clear(request)
        return redirect("documents:library")
    if action == "upload":
        pending_uploads.clear(request)
        form = UploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return _upload_response(request, form=form)
        target = form.cleaned_data["document_id"]
        pending_uploads.stage(request, form.cleaned_data["file"], target_document_id=target.pk if target else None)
        try:
            mode = "new_version" if target else "choose_destination"
            return _upload_result(request, pending_uploads.process(request, workbook.upload, mode=mode))
        except workbook.HTTPException as exc:
            pending_uploads.clear(request)
            return _upload_response(request, form=form, error=exc.detail, status=exc.status_code)
    if pending_uploads.get(request) is None:
        return _upload_response(request, error="La carga pendiente caducó. Seleccione el archivo de nuevo.", status=400)
    if action not in {"new_document", "new_version", "select_document", "save_keys"}:
        return HttpResponseBadRequest("Acción de carga no válida.")
    try:
        if action == "select_document":
            selection = DestinationSelectionForm(request.POST)
            if not selection.is_valid():
                return _upload_response(request, stage="destination", error="Seleccione un documento válido.", status=400)
            pending_uploads.set_target(request, selection.cleaned_data["document_id"].pk)
            result = pending_uploads.process(request, workbook.upload, mode="new_version")
        elif action in {"new_document", "new_version"}:
            decision = UploadDecisionForm(request.POST)
            if not decision.is_valid():
                return HttpResponseBadRequest("Acción de carga no válida.")
            result = pending_uploads.process(request, workbook.upload, mode=decision.cleaned_data["action"])
        else:
            setup = pending_uploads.process(request, workbook.upload, mode="new_version")
            if setup["status"] != "comparison_setup_required":
                return _upload_result(request, setup)
            keys_form = ComparisonKeysForm(request.POST, sheets=setup["sheets"])
            if not keys_form.is_valid():
                errors = "; ".join(message for field in keys_form for message in field.errors)
                return _upload_response(request, stage="keys", result=setup, error=errors or "Seleccione columnas válidas.")
            result = pending_uploads.process(request, workbook.upload, mode="new_version", comparison_keys=json.dumps(keys_form.keys_by_sheet()))
        return _upload_result(request, result)
    except workbook.HTTPException as exc:
        stage = "keys" if action == "save_keys" else "destination" if action == "select_document" else "file"
        setup = None
        if stage == "keys":
            try:
                setup = pending_uploads.process(request, workbook.upload, mode="new_version")
            except workbook.HTTPException:
                pending_uploads.clear(request)
                stage = "file"
        return _upload_response(request, stage=stage, result=setup, error=exc.detail, status=exc.status_code)


@require_http_methods(["GET", "POST"])
def delete_version(request, vid):
    version = get_object_or_404(Version.objects.select_related("document"), pk=vid)
    if request.method == "POST":
        try:
            result = workbook.delete_version(vid)
        except workbook.HTTPException as exc:
            return _service_error(exc)
        messages.success(request, "Versión eliminada." if not result.get("cleanup_pending") else "Versión eliminada. Hay archivos pendientes de limpieza.")
        return redirect("documents:library")
    protected = Version.objects.filter(
        document_id=version.document_id, version_number__gt=version.version_number
    ).exists()
    return render(request, "documents/delete.html", {"version": version, "protected": protected})
