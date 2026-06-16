"""Generate structured Excel error reports from pipeline failures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def generate_error_report(errors: list[dict], output_path: Path) -> None:
    """Write a two-sheet Excel error report to *output_path*.

    Parameters
    ----------
    errors:
        List of error dicts.  Expected keys (all optional):
        ``error_type``, ``table``, ``row_context``, ``reason``, ``suggestion``.
    output_path:
        Target ``.xlsx`` file path.

    Sheets
    ------
    1. **错误摘要** — aggregated counts by error type and table.
    2. **错误明细** — one row per original error dict.
    """
    # ── Sheet 1: 错误摘要 ─────────────────────────────────────────────────────
    summary_rows: list[dict[str, Any]] = []
    from collections import Counter

    type_counts = Counter(e.get("error_type", "未知") for e in errors)
    table_counts: dict[str, Counter] = {}
    for e in errors:
        et = e.get("error_type", "未知")
        tbl = e.get("table", "—")
        if et not in table_counts:
            table_counts[et] = Counter()
        table_counts[et][tbl] += 1

    for error_type, count in type_counts.most_common():
        involved = ", ".join(sorted(table_counts[error_type].keys()))
        summary_rows.append({
            "错误类型": error_type,
            "发生次数": count,
            "涉及文件/表": involved,
        })

    df_summary = pd.DataFrame(summary_rows)

    # ── Sheet 2: 错误明细 ─────────────────────────────────────────────────────
    detail_rows: list[dict[str, Any]] = []
    for e in errors:
        detail_rows.append({
            "表名": e.get("table", "—"),
            "行号/上下文": e.get("row_context", "—"),
            "错误原因": e.get("reason", "—"),
            "建议修复": e.get("suggestion", "—"),
        })

    df_detail = pd.DataFrame(detail_rows)

    # ── Write ─────────────────────────────────────────────────────────────────
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="错误摘要", index=False)
        df_detail.to_excel(writer, sheet_name="错误明细", index=False)
