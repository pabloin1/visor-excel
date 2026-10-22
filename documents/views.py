import json

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from documents.services import history as workbook


class AppJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "item"):
            return obj.item()
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return super().default(obj)


def response(action):
    try:
        value = action()
        return JsonResponse(value, safe=not isinstance(value, list), encoder=AppJSONEncoder)
    except workbook.HTTPException as exc:
        return JsonResponse({"detail": exc.detail}, status=exc.status_code)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)


def integer(source, name, default=None, minimum=None, maximum=None):
    raw = source.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise workbook.HTTPException(400, f"El parámetro {name} debe ser un número entero.")
    if minimum is not None and value < minimum:
        raise workbook.HTTPException(400, f"El parámetro {name} debe ser mayor o igual a {minimum}.")
    if maximum is not None and value > maximum:
        raise workbook.HTTPException(400, f"El parámetro {name} debe ser menor o igual a {maximum}.")
    return value


@require_POST
def upload_file(request):
    def action():
        uploaded = request.FILES.get("file")
        if uploaded is None:
            raise workbook.HTTPException(400, "Seleccione un archivo Excel o CSV.")
        if uploaded.size > workbook.MAX_FILE_SIZE:
            raise workbook.HTTPException(413, "El archivo supera el tamaño máximo permitido de 50 MB.")
        return workbook.upload(
            filename=uploaded.name,
            content=uploaded,
            mode=request.POST.get("mode", ""),
            header_row=integer(request.POST, "header_row"),
            delimiter=request.POST.get("delimiter"),
            encoding=request.POST.get("encoding"),
            comparison_keys=request.POST.get("comparison_keys"),
            target_document_id=integer(request.POST, "target_document_id", minimum=1),
        )

    return response(action)


@require_GET
def documents(request):
    return response(workbook.list_documents)


@require_GET
def library(request):
    return response(lambda: workbook.list_library(
        q=request.GET.get("q", ""),
        sort=request.GET.get("sort", "recent"),
        page=integer(request.GET, "page", 0, 0),
        page_size=integer(request.GET, "page_size", 15, 1, 50),
    ))


@require_http_methods(["GET", "DELETE"])
def version(request, vid):
    if request.method == "DELETE":
        return response(lambda: workbook.delete_version(vid))
    return response(lambda: workbook.get_version(vid))


@require_GET
def version_rows(request, vid):
    return response(lambda: workbook.get_version_rows(
        vid=vid,
        sheet=request.GET.get("sheet", ""),
        page=integer(request.GET, "page", 0, 0),
        page_size=integer(request.GET, "page_size", 100, 1, 500),
        q=request.GET.get("q", ""),
        sort_col=integer(request.GET, "sort_col"),
        sort_dir=request.GET.get("sort_dir", "asc"),
        filters=request.GET.get("filters"),
    ))


@require_GET
def version_summary(request, vid):
    return response(lambda: workbook.get_version_summary(
        vid=vid,
        sheet=request.GET.get("sheet", ""),
        category_col=integer(request.GET, "category_col"),
        measure_col=integer(request.GET, "measure_col"),
        stat_op=request.GET.get("stat_op", "sum"),
        date_period=request.GET.get("date_period", "month"),
        sort_chart=request.GET.get("sort_chart", "desc"),
    ))


@require_GET
def version_changes(request, vid):
    return response(lambda: workbook.get_version_changes(
        vid=vid,
        sheet=request.GET.get("sheet"),
        kind=request.GET.get("kind", "updated"),
        page=integer(request.GET, "page", 0, 0),
        page_size=integer(request.GET, "page_size", 50, 1, 100),
    ))
