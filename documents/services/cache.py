import json
import os
import tempfile
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from documents.services.parsing import infer_schema_type_info, read_sheets

CACHE_FORMAT_VERSION = 3


def _cache_valid(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(path)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(_sheets)")}
            version_row = connection.execute(
                "SELECT version FROM _cache_meta LIMIT 1"
            ).fetchone()
            return "column_types_json" in columns and bool(
                version_row and version_row[0] == CACHE_FORMAT_VERSION
            )
    except sqlite3.DatabaseError:
        return False


def _write_cache(cache_path: Path, path: Path, options: dict) -> None:
    sheets_dict, _ = read_sheets(path, options)
    con = sqlite3.connect(cache_path)
    try:
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA journal_mode = DELETE")

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS _sheets (
                sheet_name TEXT PRIMARY KEY,
                table_name TEXT NOT NULL,
                columns_json TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                numeric_cols_json TEXT NOT NULL,
                date_cols_json TEXT NOT NULL,
                column_types_json TEXT NOT NULL
            )
        """
        )
        con.execute("CREATE TABLE _cache_meta (version INTEGER NOT NULL)")
        con.execute("INSERT INTO _cache_meta VALUES (?)", (CACHE_FORMAT_VERSION,))

        for idx, (sname, df) in enumerate(sheets_dict.items()):
            tbl = f"sheet_{idx}"
            cols = list(df.columns)
            col_defs = ["row_idx INTEGER PRIMARY KEY"]
            num_cols = []
            date_cols = []
            column_types = []

            for i, c in enumerate(cols):
                type_info = infer_schema_type_info(df[c]) if not df.empty else {
                    "type": "empty",
                    "observed_types": [],
                }
                column_types.append(type_info)
                is_num = "number" in type_info["observed_types"]
                is_date = type_info["type"] == "date"

                if is_num:
                    num_cols.append(i)
                    col_defs.append(f"c{i} REAL")
                else:
                    col_defs.append(f"c{i} TEXT")
                if is_date:
                    date_cols.append(i)

            col_defs.append("__search TEXT")
            con.execute(f"CREATE TABLE {tbl} ({', '.join(col_defs)})")

            if not df.empty:
                insert_sql = f"INSERT INTO {tbl} VALUES ({', '.join(['?'] * (len(cols) + 2))})"
                rows_to_insert = []
                for r_idx, (_, row) in enumerate(df.iterrows(), start=1):
                    row_vals = [r_idx]
                    search_parts = []
                    for i, c in enumerate(cols):
                        val = row[c]
                        if pd.isna(val) or val is None:
                            row_vals.append(None)
                        else:
                            row_vals.append(val)
                            search_parts.append(str(val))
                    row_vals.append(" ".join(search_parts).lower())
                    rows_to_insert.append(row_vals)

                con.executemany(insert_sql, rows_to_insert)
                con.execute(f"CREATE INDEX idx_{tbl}_search ON {tbl}(__search)")

            con.execute(
                "INSERT INTO _sheets VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    sname,
                    tbl,
                    json.dumps(cols, ensure_ascii=False),
                    len(df),
                    json.dumps(num_cols),
                    json.dumps(date_cols),
                    json.dumps(column_types, ensure_ascii=False),
                ),
            )

        con.commit()
    finally:
        con.close()


def build_cache_for_version(sha256: str, path: Path, options: dict, cache_dir: Path) -> Path:
    """Build a derived cache off to the side and publish it as one file."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{sha256}.db"
    if _cache_valid(cache_path):
        return cache_path
    with tempfile.TemporaryDirectory(prefix=".cache-build-", dir=cache_dir) as building:
        candidate = Path(building) / f"{sha256}.db"
        _write_cache(candidate, path, options)
        if _cache_valid(cache_path):
            return cache_path
        try:
            os.replace(candidate, cache_path)
        except OSError:
            if _cache_valid(cache_path):
                return cache_path
            raise
    return cache_path
