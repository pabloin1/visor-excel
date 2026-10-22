"""Descriptive Excel reports built from the rebuildable sheet cache."""

import json
import re
import sqlite3
from contextlib import closing


IDENTIFIER_NAME = re.compile(
    r"(^|[\W_])(id|folio|clave|c[oó]digo|identificador|uuid|curp|rfc)([\W_]|$)",
    re.IGNORECASE,
)


def _display_date(value):
    if isinstance(value, str) and value.endswith(" 00:00:00"):
        return value[:10]
    return value


def sheet_report(connection: sqlite3.Connection, sheet: sqlite3.Row) -> dict:
    columns = json.loads(sheet["columns_json"])
    types = json.loads(sheet["column_types_json"])
    numeric = set(json.loads(sheet["numeric_cols_json"]))
    dates = set(json.loads(sheet["date_cols_json"]))
    total = sheet["row_count"]
    table = sheet["table_name"]  # Generated internally as sheet_N.
    fields = []
    missing_cells = 0
    for index, name in enumerate(columns):
        field = f"c{index}"
        count = connection.execute(
            f"SELECT COUNT({field}), COUNT(DISTINCT {field}), "
            f"SUM(CASE WHEN typeof({field}) IN ('integer', 'real') THEN 1 ELSE 0 END), "
            f"MIN({field}), MAX({field}) FROM {table}"
        ).fetchone()
        present, distinct, valid_numbers, minimum, maximum = count
        missing = total - present
        missing_cells += missing
        unique_ratio = distinct / present if present else 0
        identifier = bool(IDENTIFIER_NAME.search(name)) or (
            index not in numeric and index not in dates and present >= 10 and unique_ratio >= 0.95
        )
        item = {
            "index": index, "name": name, "type": types[index]["type"],
            "present": present, "missing": missing, "distinct": distinct,
            "identifier": identifier,
        }
        if index in dates:
            item["kind"] = "date"
            item["minimum"] = _display_date(minimum)
            item["maximum"] = _display_date(maximum)
        elif index in numeric:
            item["kind"] = "number"
            item["valid"] = valid_numbers or 0
            item["non_numeric"] = present - item["valid"]
            if item["valid"] and not identifier:
                stats = connection.execute(
                    f"SELECT SUM({field}), AVG({field}), MIN({field}), MAX({field}) "
                    f"FROM {table} WHERE typeof({field}) IN ('integer', 'real')"
                ).fetchone()
                item.update(sum=stats[0], average=stats[1], minimum=stats[2], maximum=stats[3])
        else:
            item["kind"] = "category"
            if not identifier and present:
                item["top_values"] = [
                    {"label": str(label), "count": count, "percent": round(count * 100 / total, 1)}
                    for label, count in connection.execute(
                        f"SELECT {field}, COUNT(*) AS n FROM {table} "
                        f"WHERE {field} IS NOT NULL GROUP BY {field} ORDER BY n DESC, {field} LIMIT 3"
                    )
                ]
        fields.append(item)

    if columns and total:
        if len(columns) <= 500:
            missing_predicate = " OR ".join(f"c{i} IS NULL" for i in range(len(columns)))
            rows_with_missing = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {missing_predicate}"
            ).fetchone()[0]
        else:
            selected = ", ".join(f"c{i}" for i in range(len(columns)))
            rows_with_missing = sum(
                any(value is None for value in row)
                for row in connection.execute(f"SELECT {selected} FROM {table}")
            )
    else:
        rows_with_missing = 0
    mixed = sum(item["type"] == "mixed" for item in fields)
    usable_categories = [item for item in fields if item["kind"] in ("category", "date")
                         and not item["identifier"] and 1 < item["distinct"] <= max(12, total // 2)]
    measures = [item for item in fields if item["kind"] == "number" and not item["identifier"] and item["valid"]]
    return {
        "name": sheet["sheet_name"], "rows": total, "columns": len(columns),
        "missing_cells": missing_cells, "rows_with_missing": rows_with_missing,
        "mixed_columns": mixed, "empty": total == 0,
        "needs_review": total == 0 or missing_cells > 0 or mixed > 0,
        "numeric_fields": [item for item in fields if item["kind"] == "number"],
        "categorical_fields": [item for item in fields if item["kind"] == "category"],
        "date_fields": [item for item in fields if item["kind"] == "date"],
        "suggested_category": usable_categories[0]["index"] if usable_categories else None,
        "suggested_measure": measures[0]["index"] if measures else None,
        "measure_candidates": [item["index"] for item in measures],
    }


def workbook_report(cache_path) -> dict:
    with closing(sqlite3.connect(cache_path)) as connection:
        connection.row_factory = sqlite3.Row
        sheet_rows = connection.execute("SELECT * FROM _sheets").fetchall()
        sheets = [sheet_report(connection, sheet) for sheet in sheet_rows]
    return {
        "sheet_count": len(sheets),
        "total_rows": sum(sheet["rows"] for sheet in sheets),
        "empty_sheets": sum(sheet["empty"] for sheet in sheets),
        "sheets_with_observations": sum(sheet["needs_review"] for sheet in sheets),
        "sheets": sheets,
    }
