"""Folder watcher with fingerprint-based deduplication."""

from __future__ import annotations

import json
from pathlib import Path

from core.ingest import is_new_file, record_fingerprint

SUPPORTED_EXTS = {".csv", ".xlsx", ".xls", ".parquet", ".json", ".zip"}


def scan_folder(path: Path, processed_log: Path = Path("config/processed_files.jsonl")) -> list[Path]:
    """Return files in *path* that are supported and not yet processed.

    Parameters
    ----------
    path:
        Directory to scan.
    processed_log:
        JSONL file storing fingerprints of already-imported files.

    Returns
    -------
    List of :class:`Path` objects ready for ingestion.
    """
    if not path.exists():
        return []

    candidates: list[Path] = []
    for item in path.rglob("*"):
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTS:
            if is_new_file(item, processed_log):
                candidates.append(item)
    return candidates


def mark_processed(paths: list[Path], processed_log: Path = Path("config/processed_files.jsonl")) -> None:
    """Append fingerprints for *paths* to the processed log."""
    for p in paths:
        record_fingerprint(p, processed_log)
