"""Validated inputs for the server-rendered document interface."""

from pathlib import Path

from django import forms

from .models import Document
from .services.history import MAX_FILE_SIZE


class LibraryForm(forms.Form):
    q = forms.CharField(required=False, max_length=120)
    sort = forms.ChoiceField(
        required=False,
        choices=(("recent", "Actualización más reciente"), ("name", "Nombre"), ("rows", "Más registros")),
    )
    page = forms.IntegerField(required=False, min_value=0)

    def clean(self):
        data = super().clean()
        data["sort"] = data.get("sort") or "recent"
        data["page"] = data.get("page") or 0
        return data


class DocumentVersionsForm(LibraryForm):
    versions_page = forms.IntegerField(required=False, min_value=0)

    def clean(self):
        data = super().clean()
        data["versions_page"] = data.get("versions_page") or 0
        return data


class UploadForm(forms.Form):
    file = forms.FileField(label="Archivo Excel")
    document_id = forms.ModelChoiceField(queryset=Document.objects.all(), required=False, widget=forms.HiddenInput)

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if Path(uploaded.name).suffix.lower() not in {".xlsx", ".xls"}:
            raise forms.ValidationError("Seleccione un archivo Excel .xlsx o .xls.")
        if uploaded.size == 0:
            raise forms.ValidationError("El archivo está vacío.")
        if uploaded.size > MAX_FILE_SIZE:
            raise forms.ValidationError("El archivo supera el máximo de 50 MB.")
        return uploaded


class UploadDecisionForm(forms.Form):
    action = forms.ChoiceField(choices=(("new_document", "Documento nuevo"), ("new_version", "Nueva versión")))


class DestinationSelectionForm(forms.Form):
    document_id = forms.ModelChoiceField(queryset=Document.objects.all(), error_messages={
        "required": "Seleccione un documento existente.",
        "invalid_choice": "El documento elegido ya no existe.",
    })


class ComparisonKeysForm(forms.Form):
    action = forms.ChoiceField(choices=(("save_keys", "Guardar comparación"),))

    def __init__(self, data, *, sheets):
        super().__init__(data)
        self.sheets = sheets
        for index, sheet in enumerate(sheets):
            choices = [(column, column) for column in sheet["available_keys"]]
            self.fields[f"keys_{index}"] = forms.MultipleChoiceField(
                required=bool(choices), choices=choices, widget=forms.CheckboxSelectMultiple,
                error_messages={"required": f'Seleccione al menos una clave para «{sheet["name"]}».'},
            )

    def keys_by_sheet(self):
        return {
            sheet["name"]: self.cleaned_data[f"keys_{index}"]
            for index, sheet in enumerate(self.sheets)
        }

    def clean(self):
        data = super().clean()
        for index, _ in enumerate(self.sheets):
            selected = data.get(f"keys_{index}", [])
            if len(selected) != len(set(selected)):
                self.add_error(f"keys_{index}", "Seleccione cada columna una sola vez.")
        return data


class ViewerForm(forms.Form):
    view = forms.ChoiceField(required=False, choices=(("summary", "Resumen"), ("data", "Datos"), ("changes", "Cambios")))
    sheet = forms.ChoiceField(required=False)
    q = forms.CharField(required=False, max_length=120)
    page = forms.IntegerField(required=False, min_value=0)
    chart_page = forms.IntegerField(required=False, min_value=0)
    other_page = forms.IntegerField(required=False, min_value=0)
    sort_col = forms.ChoiceField(required=False)
    sort_dir = forms.ChoiceField(required=False, choices=(("asc", "Ascendente"), ("desc", "Descendente")))
    category_col = forms.ChoiceField(required=False)
    measure_col = forms.ChoiceField(required=False)
    stat_op = forms.ChoiceField(required=False, choices=(("sum", "Suma"), ("avg", "Promedio"), ("min", "Mínimo"), ("max", "Máximo"), ("count", "Recuento")))
    date_period = forms.ChoiceField(required=False, choices=(("raw", "Día exacto"), ("month", "Mes"), ("year", "Año")))
    sort_chart = forms.ChoiceField(required=False, choices=(("desc", "Mayor a menor"), ("asc", "Menor a mayor"), ("alpha", "Alfabético o cronológico")))
    change = forms.ChoiceField(required=False)
    change_sheet = forms.ChoiceField(required=False)
    kind = forms.ChoiceField(required=False, choices=(("added", "Agregados"), ("updated", "Actualizados"), ("removed", "Eliminados")))
    change_page = forms.IntegerField(required=False, min_value=0)
    history_page = forms.IntegerField(required=False, min_value=0)

    def __init__(self, data, *, sheets, history):
        super().__init__(data)
        self.sheets = sheets
        self.history = history
        self.fields["sheet"].choices = [(item["name"], item["name"]) for item in sheets]
        requested_sheet = data.get("sheet") if data else None
        self.selected_sheet = next((item for item in sheets if item["name"] == requested_sheet), sheets[0] if sheets else None)
        columns = self.selected_sheet["columns"] if self.selected_sheet else []
        numeric = self.selected_sheet.get("measure_candidates", self.selected_sheet["numeric_columns"]) if self.selected_sheet else []
        self.fields["sort_col"].choices = [("", "Sin orden adicional")] + [(str(i), name) for i, name in enumerate(columns)]
        self.fields["category_col"].choices = [("", "Sin agrupación")] + [(str(i), name) for i, name in enumerate(columns)]
        self.fields["measure_col"].choices = [("", "Recuento de registros")] + [(str(i), columns[i]) for i in numeric]
        for i, _ in enumerate(columns):
            self.fields[f"filter_{i}"] = forms.CharField(required=False, max_length=120)

        self.fields["change"].choices = [(str(item["id"]), f'v{item["previous_version"]} a v{item["version_number"]}') for item in history]
        requested_change = data.get("change") if data else None
        self.selected_change = next((item for item in history if str(item["id"]) == requested_change), history[-1] if history else None)
        self.fields["change_sheet"].choices = [
            (item["sheet"], item["sheet"]) for item in (self.selected_change or {}).get("sheets", [])
        ]

    def clean(self):
        data = super().clean()
        data["view"] = data.get("view") or "summary"
        data["sheet"] = data.get("sheet") or (self.selected_sheet["name"] if self.selected_sheet else "")
        data["page"] = data.get("page") or 0
        data["chart_page"] = data.get("chart_page") or 0
        data["other_page"] = data.get("other_page") or 0
        data["sort_dir"] = data.get("sort_dir") or "asc"
        data["change_page"] = data.get("change_page") or 0
        data["history_page"] = data.get("history_page") or 0
        data["change"] = data.get("change") or (str(self.selected_change["id"]) if self.selected_change else "")
        data["change_sheet"] = data.get("change_sheet") or (self.fields["change_sheet"].choices[0][0] if self.fields["change_sheet"].choices else "")
        data["date_period"] = data.get("date_period") or "month"
        data["stat_op"] = data.get("stat_op") or "sum"
        data["sort_chart"] = data.get("sort_chart") or "desc"
        selected_summary = next(
            (item for item in (self.selected_change or {}).get("sheets", []) if item["sheet"] == data["change_sheet"]),
            None,
        )
        data["kind"] = data.get("kind") or next(
            (kind for kind in ("updated", "added", "removed") if selected_summary and selected_summary.get(kind, 0) > 0),
            "updated",
        )
        if self.selected_sheet:
            numeric = self.selected_sheet.get("measure_candidates", self.selected_sheet["numeric_columns"])
            if "category_col" not in self.data:
                suggested = self.selected_sheet.get("suggested_category")
                data["category_col"] = str(suggested) if suggested is not None else ""
            if "measure_col" not in self.data:
                suggested = self.selected_sheet.get("suggested_measure")
                data["measure_col"] = str(suggested) if suggested is not None else ""
            if not data.get("measure_col"):
                data["stat_op"] = "count"
            if "sort_chart" not in self.data and data.get("category_col"):
                if int(data["category_col"]) in self.selected_sheet["date_columns"]:
                    data["sort_chart"] = "alpha"
        return data
