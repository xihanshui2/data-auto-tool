"""Multi-level column-based splitting and file export.

Uses DuckDB for grouping and either DuckDB COPY (CSV/Parquet) or
pandas+openpyxl (Excel) for output.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from core.archive import build_archive_path, ensure_dirs, select_output_columns
from core.logger import ProcessingLogger
from core.models import Rule
from core.sql_utils import quote_identifier


def split_by_columns(
    con: duckdb.DuckDBPyConnection,
    source_table: str,
    rule: Rule,
    logger: ProcessingLogger,
    base_output_dir: Path | None = None,
) -> dict[str, Path]:
    """Split *source_table* by *rule.split_keys* and write to archive files.

    Parameters
    ----------
    con:
        DuckDB connection.
    source_table:
        Table name to read from.
    rule:
        Rule containing ``split_keys``, ``output_format``, ``output_template``,
        ``output_dir``, ``output_columns``.
    logger:
        Logger for warnings and progress.
    base_output_dir:
        Root output directory.  Defaults to ``Path(".")`` (current working dir).

    Returns
    -------
    Mapping from ``"val1/val2/..."`` combo string to the written :class:`Path`.

    Notes
    -----
    - Rows with any NULL or blank split-key value are written to a
      ``未分类`` folder.
    - Split depth is capped at 4; extra levels trigger a logger warning.
    - Excel output uses ``con.execute(...).df().to_excel(...)`` because
      DuckDB does not natively support ``COPY ... TO ... (FORMAT XLSX)``.
    """
    if base_output_dir is None:
        base_output_dir = Path(".")

    if len(rule.split_keys) > 4:
        logger.log(
            "split",
            "warn",
            f"split_keys 超过 4 级，已截断为前 4 级: {rule.split_keys[:4]}",
        )

    # Build the base query with output column selection
    base_query = select_output_columns(con, source_table, rule.output_columns)

    # Discover unique combinations
    keys_quoted = ", ".join(quote_identifier(k) for k in rule.split_keys)
    group_sql = f"SELECT {keys_quoted}, COUNT(*) FROM {quote_identifier(source_table)} GROUP BY {keys_quoted}"
    combos = con.execute(group_sql).fetchall()

    date_str = date.today().isoformat()
    result: dict[str, Path] = {}

    for combo in combos:
        values = list(combo[:-1])  # all but the count column
        count = combo[-1]

        # Check for NULL/blank values
        if any(v is None or str(v).strip() == "" for v in values):
            folder_label = "未分类"
            safe_values = [folder_label]
        else:
            safe_values = [str(v).strip() for v in values]

        combo_str = "/".join(safe_values)

        # Build archive path
        path = build_archive_path(base_output_dir, rule, safe_values, date_str)
        ensure_dirs(path)

        # Build WHERE clause for this combo
        where_clauses = []
        for key, val in zip(rule.split_keys, values):
            if val is None:
                where_clauses.append(f"{quote_identifier(key)} IS NULL")
            else:
                # Escape single quotes in value
                safe_val = str(val).replace("'", "''")
                where_clauses.append(f"{quote_identifier(key)} = '{safe_val}'")

        where_sql = " AND ".join(where_clauses)
        query = f"{base_query} WHERE {where_sql}"

        # Export based on format
        if rule.output_format == "excel":
            df = con.execute(query).df()
            df.to_excel(path, engine="openpyxl", index=False)
        elif rule.output_format == "csv":
            copy_sql = f"COPY ({query}) TO '{str(path).replace(chr(39), chr(39)+chr(39))}' (HEADER, FORMAT CSV)"
            con.execute(copy_sql)
        elif rule.output_format == "parquet":
            copy_sql = f"COPY ({query}) TO '{str(path).replace(chr(39), chr(39)+chr(39))}' (FORMAT PARQUET)"
            con.execute(copy_sql)
        else:
            raise ValueError(f"不支持的输出格式: {rule.output_format}")

        logger.log(
            "split",
            "ok",
            f"写入 {combo_str}: {count} 行 -> {path}",
        )
        result[combo_str] = path

    return result
