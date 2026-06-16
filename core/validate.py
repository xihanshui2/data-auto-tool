"""Pre-execution validation of rules against actual DuckDB tables."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from core.models import Rule
from core.sql_utils import quote_identifier


def _get_column_names(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    """Return a set of column names (case-sensitive) for *table*."""
    rows = con.execute(f"DESCRIBE {quote_identifier(table)}").fetchall()
    return {r[0] for r in rows}


def _ci_lookup(name: str, available: set[str]) -> str | None:
    """Case-insensitive lookup: return exact match if found, else None."""
    if name in available:
        return name
    lower_map = {c.lower(): c for c in available}
    return lower_map.get(name.lower())


def validate_against_rule(
    con: duckdb.DuckDBPyConnection,
    table: str,
    rule: Rule,
) -> list[str]:
    """Validate *rule* against the schema of *table*.

    Checks performed:

    1. ``split_keys`` exist in the table (case-insensitive).
    2. ``field_mapping`` keys exist in the table (case-insensitive).
    3. ``computed_columns`` SQL expressions can be parsed by DuckDB
       (dry-run via ``SELECT {expr} LIMIT 0``).
    4. ``output_columns`` (if set) exist after cleaning.
    5. ``output_dir`` is writable; created if it does not exist.

    Returns
    -------
    List of human-readable error strings.  Empty list means pass.
    """
    errors: list[str] = []
    columns = _get_column_names(con, table)

    # 1. split_keys
    for key in rule.split_keys:
        exact = _ci_lookup(key, columns)
        if exact is None:
            errors.append(f"拆分字段 '{key}' 不存在于表 {table}")

    # 2. field_mapping keys
    for old_name in rule.field_mapping:
        exact = _ci_lookup(old_name, columns)
        if exact is None:
            errors.append(f"字段映射源列 '{old_name}' 不存在于表 {table}")

    # 3. computed_columns dry-run
    for new_col, expr in rule.computed_columns.items():
        try:
            con.execute(f"SELECT {expr} LIMIT 0")
        except Exception as exc:
            errors.append(
                f"计算列 '{new_col}' 表达式语法错误: {exc}"
            )

    # 4. output_columns (check against *projected* columns if input_columns is set)
    if rule.output_columns:
        effective_columns = set(rule.output_columns)
        # Also add computed columns since they will exist after cleaning
        effective_columns |= set(rule.computed_columns.keys())
        # And field mapping targets
        effective_columns |= set(rule.field_mapping.values())

        for col in rule.output_columns:
            # output_columns may reference original names or mapped names
            # We check against the post-cleaning effective set
            in_original = _ci_lookup(col, columns) is not None
            in_mapping = col in rule.field_mapping.values()
            in_computed = col in rule.computed_columns
            if not (in_original or in_mapping or in_computed):
                errors.append(f"输出字段 '{col}' 在清洗后不存在于表")

    # 5. output_dir writable
    out_dir = rule.output_dir or "output"
    out_path = Path(out_dir)
    try:
        out_path.mkdir(parents=True, exist_ok=True)
        # Try a test write
        test_file = out_path / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
    except OSError as exc:
        errors.append(f"输出目录不可写: {out_dir} ({exc})")

    return errors
