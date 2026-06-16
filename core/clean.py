"""Rule-driven DuckDB cleaning pipeline.

All SQL identifiers are quoted via :func:`core.sql_utils.quote_identifier`.
"""

from __future__ import annotations

import re
from typing import Any

import duckdb
import pandas as pd

from core.models import CleanStep, Rule
from core.sql_utils import quote_identifier


def _get_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Return column names for *table* from DuckDB DESCRIBE."""
    return [r[0] for r in con.execute(f"DESCRIBE {quote_identifier(table)}").fetchall()]


def apply_input_columns(
    con: duckdb.DuckDBPyConnection,
    table: str,
    input_columns: list[str] | None,
) -> str:
    """Project *table* to only *input_columns*.

    If *input_columns* is ``None`` or empty, return the original table name.
    Otherwise create ``{table}_projected`` and return its name.
    """
    if not input_columns:
        return table

    projected = f"{table}_projected"
    cols = ", ".join(quote_identifier(c) for c in input_columns)
    con.execute(
        f"CREATE OR REPLACE TABLE {quote_identifier(projected)} AS SELECT {cols} FROM {quote_identifier(table)}"
    )
    return projected


def _drop_empty_columns(
    con: duckdb.DuckDBPyConnection,
    table: str,
    report: dict[str, Any],
) -> str:
    """Remove columns where every value is NULL."""
    columns = _get_columns(con, table)
    valid_columns: list[str] = []
    empty_cols: list[str] = []

    for col in columns:
        non_null = con.execute(
            f"SELECT count({quote_identifier(col)}) FROM {quote_identifier(table)}"
        ).fetchone()[0]
        if non_null == 0:
            empty_cols.append(col)
        else:
            valid_columns.append(col)

    report["empty_cols_removed"].extend(empty_cols)

    if not empty_cols:
        return table

    out = f"{table}_noempty"
    cols = ", ".join(quote_identifier(c) for c in valid_columns)
    con.execute(
        f"CREATE OR REPLACE TABLE {quote_identifier(out)} AS SELECT {cols} FROM {quote_identifier(table)}"
    )
    return out


def _deduplicate(
    con: duckdb.DuckDBPyConnection,
    table: str,
    report: dict[str, Any],
) -> str:
    """Remove fully duplicate rows via ``SELECT DISTINCT *``."""
    rows_before = con.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(table)}"
    ).fetchone()[0]

    out = f"{table}_dedup"
    con.execute(
        f"CREATE OR REPLACE TABLE {quote_identifier(out)} AS SELECT DISTINCT * FROM {quote_identifier(table)}"
    )

    rows_after = con.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(out)}"
    ).fetchone()[0]
    report["duplicates_removed"] = rows_before - rows_after
    return out


def _infer_types(
    con: duckdb.DuckDBPyConnection,
    table: str,
    report: dict[str, Any],
) -> str:
    """Detect VARCHAR columns that look numeric and cast them."""
    columns = _get_columns(con, table)
    select_exprs: list[str] = []
    cast_cols: list[str] = []

    for col in columns:
        col_type = con.execute(
            f"SELECT typeof({quote_identifier(col)}) FROM {quote_identifier(table)} LIMIT 1"
        ).fetchone()[0]

        if col_type == "VARCHAR":
            total_not_null, castable = con.execute(
                f"""
                SELECT
                    COUNT({quote_identifier(col)}),
                    COUNT(TRY_CAST(REPLACE(REPLACE({quote_identifier(col)}, ',', ''), ' ', '') AS DOUBLE))
                FROM {quote_identifier(table)}
                """
            ).fetchone()

            if total_not_null and (castable / total_not_null) >= 0.5:
                expr = (
                    f"TRY_CAST(REPLACE(REPLACE({quote_identifier(col)}, ',', ''), ' ', '') AS DOUBLE) "
                    f"AS {quote_identifier(col)}"
                )
                select_exprs.append(expr)
                cast_cols.append(col)
                continue

        select_exprs.append(quote_identifier(col))

    report["force_cast_cols"].extend(cast_cols)

    if not cast_cols:
        return table

    out = f"{table}_typed"
    select_clause = ", ".join(select_exprs)
    con.execute(
        f"CREATE OR REPLACE TABLE {quote_identifier(out)} AS SELECT {select_clause} FROM {quote_identifier(table)}"
    )
    return out


def _wide_to_long_step(
    con: duckdb.DuckDBPyConnection,
    table: str,
    _report: dict[str, Any],
) -> str:
    """Run the existing wide-to-long logic and return the new table name."""
    from core.clean import wide_to_long as _wtl

    long_name, did_melt = _wtl(con, table)
    if did_melt:
        return long_name
    return table


def apply_clean_steps(
    con: duckdb.DuckDBPyConnection,
    table: str,
    clean_steps: list[CleanStep],
) -> str:
    """Execute *clean_steps* in order, each producing a new table.

    Returns the final table name.
    """
    report: dict[str, Any] = {
        "empty_cols_removed": [],
        "duplicates_removed": 0,
        "force_cast_cols": [],
    }

    current = table
    step_dispatch = {
        CleanStep.drop_empty_columns: _drop_empty_columns,
        CleanStep.deduplicate: _deduplicate,
        CleanStep.infer_types: _infer_types,
        CleanStep.wide_to_long: _wide_to_long_step,
    }

    for step in clean_steps:
        handler = step_dispatch.get(step)
        if handler is None:
            raise ValueError(f"未知的清洗步骤: {step}")
        current = handler(con, current, report)

    return current


def apply_field_mapping(
    con: duckdb.DuckDBPyConnection,
    table: str,
    field_mapping: dict[str, str],
) -> str:
    """Rename columns according to *field_mapping* (old -> new).

    Uses ``ALTER TABLE ... RENAME COLUMN`` when possible; falls back to a
    ``SELECT`` projection if renaming would create conflicts.
    """
    if not field_mapping:
        return table

    existing = set(_get_columns(con, table))
    new_names = set(field_mapping.values())

    # If any target name already exists as a *different* column, use projection
    conflict = (new_names & existing) - set(field_mapping.keys())
    if conflict:
        # Build projection: apply mapping, keep unmapped columns as-is
        projection: dict[str, str] = {}
        for col in existing:
            projection[col] = field_mapping.get(col, col)
        out = f"{table}_renamed"
        select_exprs = ", ".join(
            f"{quote_identifier(src)} AS {quote_identifier(dst)}"
            for src, dst in projection.items()
        )
        con.execute(
            f"CREATE OR REPLACE TABLE {quote_identifier(out)} AS SELECT {select_exprs} FROM {quote_identifier(table)}"
        )
        return out

    # Safe to use ALTER TABLE RENAME COLUMN
    for old, new in field_mapping.items():
        if old == new:
            continue
        con.execute(
            f"ALTER TABLE {quote_identifier(table)} RENAME COLUMN {quote_identifier(old)} TO {quote_identifier(new)}"
        )
    return table


def apply_computed_columns(
    con: duckdb.DuckDBPyConnection,
    table: str,
    computed_columns: dict[str, str],
) -> str:
    """Add computed columns via SQL expressions.

    If ``ALTER TABLE ... ADD COLUMN`` fails (e.g. expression references a
    column that was just renamed), fall back to ``SELECT *`` projection.
    """
    if not computed_columns:
        return table

    # Try ALTER TABLE ADD COLUMN first
    for new_col, expr in computed_columns.items():
        try:
            con.execute(
                f"ALTER TABLE {quote_identifier(table)} ADD COLUMN {quote_identifier(new_col)} AS {expr}"
            )
        except Exception:
            # Fall back to SELECT projection
            out = f"{table}_computed"
            existing = _get_columns(con, table)
            # Exclude columns that are about to be added as computed
            # (they might already exist if a previous ALTER succeeded)
            existing = [c for c in existing if c not in computed_columns]
            select_exprs = ", ".join(quote_identifier(c) for c in existing)
            computed_exprs = ", ".join(
                f"{expr} AS {quote_identifier(col)}"
                for col, expr in computed_columns.items()
            )
            full_select = f"{select_exprs}, {computed_exprs}" if select_exprs else computed_exprs
            con.execute(
                f"CREATE OR REPLACE TABLE {quote_identifier(out)} AS SELECT {full_select} FROM {quote_identifier(table)}"
            )
            return out

    return table


def clean_table(
    con: duckdb.DuckDBPyConnection,
    table: str,
    rule: Rule,
) -> tuple[str, dict[str, Any]]:
    """Orchestrate the full cleaning pipeline for *table* according to *rule*.

    Execution order:
        1. input projection
        2. clean steps (in order)
        3. field mapping
        4. computed columns

    Returns
    -------
    (final_table_name, report_dict)
    """
    report: dict[str, Any] = {
        "original_table": table,
        "steps": [],
    }

    # 1. Input projection
    current = apply_input_columns(con, table, rule.input_columns)
    if current != table:
        report["steps"].append({"step": "input_projection", "status": "ok", "table": current})

    # 2. Clean steps
    if rule.clean_steps:
        current = apply_clean_steps(con, current, rule.clean_steps)
        report["steps"].append({"step": "clean_steps", "status": "ok", "table": current})

    # 3. Field mapping
    if rule.field_mapping:
        current = apply_field_mapping(con, current, rule.field_mapping)
        report["steps"].append({"step": "field_mapping", "status": "ok", "table": current})

    # 4. Computed columns
    if rule.computed_columns:
        current = apply_computed_columns(con, current, rule.computed_columns)
        report["steps"].append({"step": "computed_columns", "status": "ok", "table": current})

    report["final_table"] = current
    return current, report


# ── Legacy helpers kept for backward compatibility ──────────────────────────

def aggressive_numeric_inference(df: pd.DataFrame, threshold: float = 0.80) -> pd.DataFrame:
    for col in df.select_dtypes("object").columns:
        cleaned = df[col].astype(str).str.replace(",", "").str.strip()
        if pd.to_numeric(cleaned, errors="coerce").notna().sum() / max(len(df), 1) >= threshold:
            df[col] = pd.to_numeric(cleaned, errors="coerce")
    return df


def deep_clean_native(con, table: str) -> tuple[str, dict]:
    cleaned_name = f"{table}_cleaned"

    rows_before = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    columns = [r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()]
    cols_before = len(columns)

    report = {
        "rows_before": rows_before, "cols_before": cols_before,
        "empty_cols_removed": [], "force_cast_cols": [],
        "inferred_cols": [], "duplicates_removed": 0,
    }

    valid_columns = []
    for col in columns:
        non_null_count = con.execute(f'SELECT count("{col}") FROM "{table}"').fetchone()[0]

        if non_null_count == 0:
            report["empty_cols_removed"].append(col)
        else:
            valid_columns.append(col)

    select_exprs = []

    for col in valid_columns:
        col_type = con.execute(f'SELECT typeof("{col}") FROM "{table}" LIMIT 1').fetchone()[0]

        if col_type == 'VARCHAR':
            cast_query = f"""
            SELECT
                COUNT("{col}") as total_non_null,
                COUNT(TRY_CAST(REPLACE(REPLACE("{col}", ',', ''), ' ', '') AS DOUBLE)) as castable
            FROM "{table}"
            """
            total_not_null, castable = con.execute(cast_query).fetchone()

            if total_not_null > 0 and (castable / total_not_null) >= 0.5:
                select_exprs.append(f'TRY_CAST(REPLACE(REPLACE("{col}", ',', ''), ' ', '') AS DOUBLE) AS "{col}"')
                report["force_cast_cols"].append(col)
            else:
                select_exprs.append(f'"{col}"')
        else:
            select_exprs.append(f'"{col}"')

    select_clause = ",\n        ".join(select_exprs)

    clean_query = f"""
    CREATE OR REPLACE TABLE "{cleaned_name}" AS
    SELECT DISTINCT
        {select_clause}
    FROM "{table}"
    """
    con.execute(clean_query)

    rows_after = con.execute(f'SELECT COUNT(*) FROM "{cleaned_name}"').fetchone()[0]

    report["rows_after"] = rows_after
    report["cols_after"] = len(valid_columns)
    report["duplicates_removed"] = rows_before - rows_after

    return cleaned_name, report


def wide_to_long(con, table: str) -> tuple[str, bool]:
    """
    检测宽格式表（日期作为列标题），并将其 melt 为长格式。
    返回：(结果表名, 是否执行了 melt)
    """
    df = con.execute(f'SELECT * FROM "{table}"').df()

    date_pattern = re.compile(
        r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})'
        r'|(\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})'
        r'|(\d{1,2}\s+\w+\s+\d{4})'
    )

    date_cols = [c for c in df.columns if date_pattern.search(str(c).replace(" ", ""))]

    if len(date_cols) < 3:
        return table, False

    id_vars = [c for c in df.columns if c not in date_cols]

    df_long = df.melt(id_vars=id_vars, value_vars=date_cols,
                      var_name="date", value_name="value")

    df_long["date"] = pd.to_datetime(
        df_long["date"].str.replace(r'\s+', '', regex=True),
        dayfirst=True, errors="coerce"
    )

    df_long["value"] = pd.to_numeric(
        df_long["value"].astype(str).str.replace(",", "").str.strip(),
        errors="coerce"
    )

    df_long = df_long.sort_values(["date"] + id_vars).reset_index(drop=True)

    long_name = f"{table}_long"
    con.register("_tmp_long", df_long)
    con.execute(f'CREATE OR REPLACE TABLE "{long_name}" AS SELECT * FROM _tmp_long')
    con.unregister("_tmp_long")

    return long_name, True
