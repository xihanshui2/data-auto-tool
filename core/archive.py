"""Archive path building and directory creation utilities.

Handles safe filename/path segments, Windows path length limits, and
placeholder substitution in output templates.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import duckdb

from core.models import AppConfig, Rule
from core.sql_utils import quote_identifier


# Characters forbidden in Windows filenames
_WINDOWS_FORBIDDEN = re.compile(r'[<>"/\\|?*]')


def _safe_segment(value: str, max_len: int = 50) -> str:
    """Sanitize a single path segment for Windows compatibility.

    - Replaces forbidden characters with ``_``.
    - Strips leading/trailing spaces and dots.
    - Truncates to *max_len* characters.
    - Falls back to ``"_"`` if the result is empty.
    """
    cleaned = _WINDOWS_FORBIDDEN.sub("_", value)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        cleaned = "_"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned


def build_archive_path(
    base: Path,
    rule: Rule,
    split_values: list[str],
    date_str: str,
) -> Path:
    """Build the full output path for a given split combination.

    Parameters
    ----------
    base:
        Root output directory (e.g. ``Path("output")``).
    rule:
        The rule governing output format, template, and directory.
    split_values:
        Ordered values for each level of ``rule.split_keys``.
    date_str:
        ISO date string (``YYYY-MM-DD``) for the ``{date}`` placeholder.

    Returns
    -------
    A :class:`Path` pointing to the final file (not yet created).

    Notes
    -----
    - ``split_values`` depth is capped at 4; extra levels are dropped and
      a warning is logged via the caller.
    - The filename template supports ``{date}``, ``{file_type}``,
      ``{last_split_value}``.
    """
    # Determine output root
    out_dir = rule.output_dir or AppConfig().default_output_dir
    root = base / out_dir

    # Cap depth at 4
    effective_values = split_values[:4]
    if len(split_values) > 4:
        # Caller should log a warning; we just truncate here
        pass

    # Build nested directory
    current = root
    for val in effective_values:
        current = current / _safe_segment(val)

    # Build filename from template
    last_value = _safe_segment(effective_values[-1]) if effective_values else "未分类"
    filename = (
        rule.output_template
        .replace("{date}", date_str)
        .replace("{file_type}", _safe_segment(rule.file_type))
        .replace("{last_split_value}", last_value)
    )

    # Add extension if not present
    ext_map = {"excel": "xlsx", "csv": "csv", "parquet": "parquet"}
    ext = ext_map.get(rule.output_format, "xlsx")
    if not filename.lower().endswith(f".{ext}"):
        filename = f"{filename}.{ext}"

    return current / filename


def ensure_dirs(path: Path) -> None:
    """Recursively create parent directories for *path*.

    On Windows, if the absolute path exceeds ~240 characters, the
    ``\\\\?\\`` prefix is applied to bypass the legacy MAX_PATH limit.
    """
    target = path.resolve()
    if os.name == "nt" and len(str(target)) > 240:
        # Use extended-length path prefix on Windows
        target = Path(f"\\\\?\\{target}")
    target.parent.mkdir(parents=True, exist_ok=True)


def select_output_columns(
    con: duckdb.DuckDBPyConnection,
    table: str,
    output_columns: list[str] | None,
) -> str:
    """Return a query string that selects only *output_columns* in order.

    If *output_columns* is ``None`` or empty, returns ``SELECT * FROM ...``.
    """
    if not output_columns:
        return f"SELECT * FROM {quote_identifier(table)}"
    cols = ", ".join(quote_identifier(c) for c in output_columns)
    return f"SELECT {cols} FROM {quote_identifier(table)}"
