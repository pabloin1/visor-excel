"""Comparison services for spreadsheet versions stored in SQLite caches."""

import json
import sqlite3
from pathlib import Path


def comparison_setup(previous: dict, current: dict) -> list[dict]:
    previous_sheets = {sheet["name"]: sheet for sheet in previous.get("sheets", [])}
    current_sheets = {sheet["name"]: sheet for sheet in current.get("sheets", [])}
    result = []
    for name in sorted(previous_sheets.keys() & current_sheets.keys()):
        old_columns = [column["name"] for column in previous_sheets[name].get("columns", [])]
        new_columns = [column["name"] for column in current_sheets[name].get("columns", [])]
        if not old_columns or not new_columns:
            continue
        result.append({
            "name": name,
            "previous_columns": old_columns,
            "current_columns": new_columns,
            "available_keys": [column for column in old_columns if column in new_columns],
        })
    return result


def normalized_row_keys(raw_keys, previous_profile: dict, current_profile: dict) -> dict[str, list[str]]:
    if isinstance(raw_keys, str):
        try:
            raw_keys = json.loads(raw_keys)
        except json.JSONDecodeError as e:
            raise ValueError("No se pudo interpretar la selección de columnas clave.") from e
    if not isinstance(raw_keys, dict):
        raise ValueError("Selecciona una o más columnas clave para cada hoja.")

    setup = {sheet["name"]: sheet for sheet in comparison_setup(previous_profile, current_profile)}
    normalized = {}
    for sheet_name, key_columns in raw_keys.items():
        if sheet_name not in setup:
            raise ValueError(f"La hoja '{sheet_name}' no puede compararse entre estas versiones.")
        available = setup[sheet_name]["available_keys"]
        if not available and key_columns == []:
            normalized[sheet_name] = []
            continue
        if (
            not isinstance(key_columns, list)
            or not key_columns
            or any(not isinstance(key, str) for key in key_columns)
        ):
            raise ValueError(f"Selecciona al menos una columna clave para la hoja '{sheet_name}'.")
        if len(set(key_columns)) != len(key_columns) or any(key not in available for key in key_columns):
            raise ValueError(f"Las columnas clave de la hoja '{sheet_name}' no son válidas.")
        normalized[sheet_name] = key_columns

    for sheet_name in setup:
        if not setup[sheet_name]["available_keys"]:
            normalized.setdefault(sheet_name, [])
        elif sheet_name not in normalized:
            raise ValueError(f"Selecciona columnas clave para la hoja '{sheet_name}'.")
    return normalized


def _quoted_table(table_name: str) -> str:
    if not table_name.startswith("sheet_") or not table_name[6:].isdigit():
        raise ValueError("La caché contiene un nombre de hoja no válido.")
    return f'"{table_name}"'


def _duplicate_key_count(con, database: str, table: str, key_indexes: list[int]) -> int:
    fields = ", ".join(f"c{index}" for index in key_indexes)
    return con.execute(
        f"""SELECT COUNT(1) FROM (
                SELECT 1 FROM {database}.{_quoted_table(table)}
                GROUP BY {fields} HAVING COUNT(1) > 1
            )"""
    ).fetchone()[0]


def compare_cached_versions(
    previous_sha: str,
    current_sha: str,
    keys_by_sheet: dict,
    cache_dir: Path,
    previous_cache_dir: Path | None = None,
) -> dict:
    """Compara snapshots en SQLite y devuelve conteos de filas por hoja."""
    current_cache = cache_dir / f"{current_sha}.db"
    previous_cache = (previous_cache_dir or cache_dir) / f"{previous_sha}.db"
    con = sqlite3.connect(current_cache)
    con.row_factory = sqlite3.Row
    try:
        con.execute("ATTACH DATABASE ? AS old_db", (str(previous_cache),))
        current_sheets = {
            row["sheet_name"]: dict(row)
            for row in con.execute("SELECT * FROM main._sheets").fetchall()
        }
        previous_sheets = {
            row["sheet_name"]: dict(row)
            for row in con.execute("SELECT * FROM old_db._sheets").fetchall()
        }
        summaries = []

        for sheet_name in sorted(previous_sheets.keys() | current_sheets.keys()):
            old = previous_sheets.get(sheet_name)
            new = current_sheets.get(sheet_name)
            if old is None:
                summaries.append({
                    "sheet": sheet_name, "key_columns": [], "added": new["row_count"],
                    "updated": 0, "removed": 0, "previous_rows": 0,
                    "current_rows": new["row_count"], "status": "sheet_added",
                })
                continue
            if new is None:
                summaries.append({
                    "sheet": sheet_name, "key_columns": [], "added": 0,
                    "updated": 0, "removed": old["row_count"],
                    "previous_rows": old["row_count"], "current_rows": 0,
                    "status": "sheet_removed",
                })
                continue

            old_count = old["row_count"]
            new_count = new["row_count"]
            key_names = keys_by_sheet.get(sheet_name, [])
            if not old_count or not new_count:
                summaries.append({
                    "sheet": sheet_name, "key_columns": key_names,
                    "added": new_count, "updated": 0, "removed": old_count,
                    "previous_rows": old_count, "current_rows": new_count,
                    "status": "compared",
                })
                continue
            if not key_names:
                old_columns = json.loads(old["columns_json"])
                new_columns = json.loads(new["columns_json"])
                if set(old_columns) & set(new_columns):
                    raise ValueError(f"Faltan columnas clave para comparar la hoja '{sheet_name}'.")
                summaries.append({
                    "sheet": sheet_name, "key_columns": [],
                    "added": new_count, "updated": 0, "removed": old_count,
                    "previous_rows": old_count, "current_rows": new_count,
                    "status": "no_common_columns",
                })
                continue

            old_columns = json.loads(old["columns_json"])
            new_columns = json.loads(new["columns_json"])
            old_indexes = {name: index for index, name in enumerate(old_columns)}
            new_indexes = {name: index for index, name in enumerate(new_columns)}
            if any(name not in old_indexes or name not in new_indexes for name in key_names):
                raise ValueError(f"Las columnas clave de la hoja '{sheet_name}' ya no coinciden.")
            old_table = _quoted_table(old["table_name"])
            new_table = _quoted_table(new["table_name"])
            old_key_indexes = [old_indexes[name] for name in key_names]
            new_key_indexes = [new_indexes[name] for name in key_names]
            if _duplicate_key_count(con, "old_db", old["table_name"], old_key_indexes):
                raise ValueError(
                    f"Las columnas clave elegidas no identifican filas únicas en la versión anterior de '{sheet_name}'."
                )
            if _duplicate_key_count(con, "main", new["table_name"], new_key_indexes):
                raise ValueError(
                    f"Las columnas clave elegidas no identifican filas únicas en el archivo nuevo de '{sheet_name}'."
                )

            join_condition = " AND ".join(
                f"o.c{old_index} IS n.c{new_index}"
                for old_index, new_index in zip(old_key_indexes, new_key_indexes)
            )
            added = con.execute(
                f"""SELECT COUNT(1) FROM main.{new_table} n
                    WHERE NOT EXISTS (
                        SELECT 1 FROM old_db.{old_table} o WHERE {join_condition}
                    )"""
            ).fetchone()[0]
            removed = con.execute(
                f"""SELECT COUNT(1) FROM old_db.{old_table} o
                    WHERE NOT EXISTS (
                        SELECT 1 FROM main.{new_table} n WHERE {join_condition}
                    )"""
            ).fetchone()[0]
            comparable = [
                (name, old_indexes[name], new_indexes[name])
                for name in old_indexes.keys() & new_indexes.keys()
                if name not in key_names
            ]
            changed_condition = " OR ".join(
                f"o.c{old_index} IS NOT n.c{new_index}"
                for _, old_index, new_index in comparable
            )
            updated = 0
            if changed_condition:
                updated = con.execute(
                    f"""SELECT COUNT(1) FROM old_db.{old_table} o
                        JOIN main.{new_table} n ON {join_condition}
                        WHERE {changed_condition}"""
                ).fetchone()[0]
            summaries.append({
                "sheet": sheet_name,
                "key_columns": key_names,
                "added": added,
                "updated": updated,
                "removed": removed,
                "previous_rows": old_count,
                "current_rows": new_count,
                "status": "compared",
            })

        return {"sheets": summaries}
    finally:
        con.close()


def get_cached_change_records(
    previous_sha: str,
    current_sha: str,
    sheet_name: str,
    key_names: list[str],
    kind: str,
    page: int,
    page_size: int,
    cache_dir: Path,
) -> tuple[int, list[dict]]:
    current_cache = cache_dir / f"{current_sha}.db"
    previous_cache = cache_dir / f"{previous_sha}.db"
    con = sqlite3.connect(current_cache)
    con.row_factory = sqlite3.Row
    try:
        con.execute("ATTACH DATABASE ? AS old_db", (str(previous_cache),))
        current = con.execute(
            "SELECT * FROM main._sheets WHERE sheet_name = ?", (sheet_name,)
        ).fetchone()
        previous = con.execute(
            "SELECT * FROM old_db._sheets WHERE sheet_name = ?", (sheet_name,)
        ).fetchone()
        if (
            not current or not previous or not current["row_count"]
            or not previous["row_count"] or not key_names
        ):
            source = current if kind == "added" else previous if kind == "removed" else None
            if not source:
                return 0, []
            database = "main" if kind == "added" else "old_db"
            table = _quoted_table(source["table_name"])
            columns = json.loads(source["columns_json"])
            count = source["row_count"]
            select_values = ", ".join(f"r.c{i} AS v{i}" for i in range(len(columns)))
            query = f"""SELECT r.row_idx, {select_values}
                FROM {database}.{table} r
                ORDER BY r.row_idx LIMIT ? OFFSET ?"""
            records = []
            for row in con.execute(query, (page_size, page * page_size)).fetchall():
                values = {name: row[f"v{i}"] for i, name in enumerate(columns)}
                records.append({"keys": {}, "values": values})
            return count, records

        old_columns = json.loads(previous["columns_json"])
        new_columns = json.loads(current["columns_json"])
        old_indexes = {name: index for index, name in enumerate(old_columns)}
        new_indexes = {name: index for index, name in enumerate(new_columns)}
        old_table = _quoted_table(previous["table_name"])
        new_table = _quoted_table(current["table_name"])
        old_key_indexes = [old_indexes[name] for name in key_names]
        new_key_indexes = [new_indexes[name] for name in key_names]
        join_condition = " AND ".join(
            f"o.c{old_index} IS n.c{new_index}"
            for old_index, new_index in zip(old_key_indexes, new_key_indexes)
        )

        if kind == "added":
            count = con.execute(
                f"""SELECT COUNT(1) FROM main.{new_table} n WHERE NOT EXISTS (
                    SELECT 1 FROM old_db.{old_table} o WHERE {join_condition})"""
            ).fetchone()[0]
            data_indexes = list(range(len(new_columns)))
            select_values = ", ".join(f"n.c{i} AS v{i}" for i in data_indexes)
            query = f"""SELECT n.row_idx, {select_values}
                FROM main.{new_table} n WHERE NOT EXISTS (
                    SELECT 1 FROM old_db.{old_table} o WHERE {join_condition})
                ORDER BY n.row_idx LIMIT ? OFFSET ?"""
        elif kind == "removed":
            count = con.execute(
                f"""SELECT COUNT(1) FROM old_db.{old_table} o WHERE NOT EXISTS (
                    SELECT 1 FROM main.{new_table} n WHERE {join_condition})"""
            ).fetchone()[0]
            data_indexes = list(range(len(old_columns)))
            select_values = ", ".join(f"o.c{i} AS v{i}" for i in data_indexes)
            query = f"""SELECT o.row_idx, {select_values}
                FROM old_db.{old_table} o WHERE NOT EXISTS (
                    SELECT 1 FROM main.{new_table} n WHERE {join_condition})
                ORDER BY o.row_idx LIMIT ? OFFSET ?"""
        else:
            comparable = [
                (name, old_indexes[name], new_indexes[name])
                for name in old_indexes.keys() & new_indexes.keys()
                if name not in key_names
            ]
            changed_condition = " OR ".join(
                f"o.c{old_index} IS NOT n.c{new_index}"
                for _, old_index, new_index in comparable
            )
            if not changed_condition:
                return 0, []
            count = con.execute(
                f"""SELECT COUNT(1) FROM old_db.{old_table} o
                    JOIN main.{new_table} n ON {join_condition}
                    WHERE {changed_condition}"""
            ).fetchone()[0]
            select_values = [f"n.c{new_indexes[key]} AS k{i}" for i, key in enumerate(key_names)]
            for i, (_, old_index, new_index) in enumerate(comparable):
                select_values.extend([
                    f"o.c{old_index} AS old{i}",
                    f"n.c{new_index} AS new{i}",
                ])
            query = f"""SELECT n.row_idx, {", ".join(select_values)}
                FROM old_db.{old_table} o
                JOIN main.{new_table} n ON {join_condition}
                WHERE {changed_condition}
                ORDER BY n.row_idx LIMIT ? OFFSET ?"""

        records = []
        for row in con.execute(query, (page_size, page * page_size)).fetchall():
            if kind in ("added", "removed"):
                columns = new_columns if kind == "added" else old_columns
                values = {name: row[f"v{i}"] for i, name in enumerate(columns)}
                keys = {name: values.get(name) for name in key_names}
                records.append({"keys": keys, "values": values})
            else:
                keys = {name: row[f"k{i}"] for i, name in enumerate(key_names)}
                changes = []
                for i, (name, _, _) in enumerate(comparable):
                    old_value, new_value = row[f"old{i}"], row[f"new{i}"]
                    if old_value != new_value:
                        changes.append({"column": name, "old": old_value, "new": new_value})
                records.append({"keys": keys, "changes": changes})
        return count, records
    finally:
        con.close()
