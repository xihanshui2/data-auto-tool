import streamlit as st
import duckdb
import pandas as pd
import numpy as np
import json
import hashlib
import zipfile
import re
from io import BytesIO
import tempfile
import os
from pathlib import Path
from core.models import Rule
from core.sql_utils import quote_identifier

SMALL_THRESHOLD = 50 * 1024 * 1024   # 50 MB

SUPPORTED_EXTS = {".csv", ".xlsx", ".xls", ".parquet", ".json", ".zip"}


def _slug(value: str) -> str:
    """Convert a string to a safe table-name slug.

    - Lowercase
    - Replace non-alphanumeric chars with underscores
    - Collapse consecutive underscores
    - Strip leading/trailing underscores
    """
    slug = re.sub(r"[^a-z0-9一-鿿]+", "_", value.lower())
    slug = re.sub(r"_+", "_", slug)
    slug = slug.strip("_")
    if not slug:
        slug = "data"
    return slug


def _make_table_name(file_name: str, sheet_name: str | None = None) -> str:
    """Generate a unique table name from file name and optional sheet name.

    Format: {slug(file_stem)}_{slug(sheet_name)}_{hash_prefix} (sheet part omitted if None).
    hash_prefix is first 8 chars of SHA-256 of the original filename bytes.
    """
    hash_prefix = hashlib.sha256(file_name.encode("utf-8")).hexdigest()[:8]
    stem_slug = _slug(Path(file_name).stem)
    if sheet_name:
        sheet_slug = _slug(sheet_name)
        return f"{stem_slug}_{sheet_slug}_{hash_prefix}"
    return f"{stem_slug}_{hash_prefix}"


def _read_csv_with_fallback(buf: BytesIO) -> pd.DataFrame:
    """Try multiple encodings for CSV files, prioritising Chinese encodings."""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            buf.seek(0)
            return pd.read_csv(buf, encoding=enc, low_memory=False)
        except (UnicodeDecodeError, pd.errors.EmptyDataError):
            continue
    # Fallback to latin-1 (never fails, but may produce garbage)
    buf.seek(0)
    return pd.read_csv(buf, encoding="latin-1", low_memory=False)


def _pandas_ingest(con, data: bytes, ext: str, table: str, rule: Rule | None = None) -> str | None:
    """快速路径：从内存加载到 pandas，再推入 DuckDB。"""
    buf = BytesIO(data)
    if ext == ".csv":
        df = _read_csv_with_fallback(buf)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(buf)
    elif ext == ".parquet":
        df = pd.read_parquet(buf)
    elif ext == ".json":
        try:
            df = pd.read_json(buf)
        except:
            buf.seek(0)
            raw = json.load(buf)
            if isinstance(raw, list):
                df = pd.json_normalize(raw)
            elif isinstance(raw, dict):
                for key in raw:
                    if isinstance(raw[key], list):
                        df = pd.json_normalize(raw[key])
                        break
                else:
                    df = pd.json_normalize([raw])
    else:
        return None

    # Apply input column whitelist if rule specifies
    if rule and rule.input_columns:
        available = set(df.columns)
        keep = [c for c in rule.input_columns if c in available]
        if keep:
            df = df[keep]

    con.register("_tmp_ingest", df)
    quoted_cols = ", ".join(quote_identifier(c) for c in df.columns)
    con.execute(f'CREATE OR REPLACE TABLE {quote_identifier(table)} AS SELECT {quoted_cols} FROM _tmp_ingest')
    con.unregister("_tmp_ingest")
    return table


def _duckdb_ingest(con, data: bytes, ext: str, table: str, rule: Rule | None = None) -> str | None:
    """大文件路径：写入临时文件，让 DuckDB 直接从磁盘流式读取。"""
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    p = tmp_path.replace("'", "''")
    try:
        if ext == ".csv":
            con.execute(f"""
                CREATE OR REPLACE TABLE {quote_identifier(table)} AS
                SELECT * FROM read_csv_auto('{p}',
                    header        = true,
                    ignore_errors = true,
                    sample_size   = -1,
                    all_varchar   = false,
                    auto_detect   = true)
            """)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(tmp_path)
            if rule and rule.input_columns:
                available = set(df.columns)
                keep = [c for c in rule.input_columns if c in available]
                if keep:
                    df = df[keep]
            con.register("_tmp_ingest", df)
            quoted_cols = ", ".join(quote_identifier(c) for c in df.columns)
            con.execute(f'CREATE OR REPLACE TABLE {quote_identifier(table)} AS SELECT {quoted_cols} FROM _tmp_ingest')
            con.unregister("_tmp_ingest")
        elif ext == ".parquet":
            con.execute(f"""
                CREATE OR REPLACE TABLE {quote_identifier(table)} AS
                SELECT * FROM read_parquet('{p}')
            """)
        elif ext == ".json":
            con.execute(f"""
                CREATE OR REPLACE TABLE {quote_identifier(table)} AS
                SELECT * FROM read_json_auto('{p}',
                    auto_detect   = true,
                    sample_size   = -1,
                    ignore_errors = true)
            """)
        else:
            return None
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass
    return table


def ingest_excel_sheets(con, data: bytes, file_name: str, rule: Rule | None = None) -> list[str]:
    """Ingest a multi-sheet Excel file, creating one DuckDB table per sheet.

    Parameters
    ----------
    con:
        DuckDB connection.
    data:
        Raw bytes of the Excel file.
    file_name:
        Original file name (used for table naming and hash).
    rule:
        Optional Rule. If *rule.sheet_names* is non-empty, only those sheets
        are imported; otherwise all sheets are imported.

    Returns
    -------
    List of created table names.
    """
    tables: list[str] = []
    buf = BytesIO(data)
    xl = pd.ExcelFile(buf, engine="openpyxl")
    sheets = xl.sheet_names

    target_sheets = sheets
    if rule and rule.sheet_names:
        target_sheets = [s for s in sheets if s in rule.sheet_names]

    header_row = 0
    if rule and getattr(rule, "header_row", None) is not None:
        header_row = rule.header_row

    for sheet in target_sheets:
        df = pd.read_excel(xl, sheet_name=sheet, header=header_row)
        if df.empty:
            continue
        table = _make_table_name(file_name, sheet)

        if rule and rule.input_columns:
            available = set(df.columns)
            keep = [c for c in rule.input_columns if c in available]
            if keep:
                df = df[keep]

        con.register("_tmp_ingest", df)
        quoted_cols = ", ".join(quote_identifier(c) for c in df.columns)
        con.execute(f'CREATE OR REPLACE TABLE {quote_identifier(table)} AS SELECT {quoted_cols} FROM _tmp_ingest')
        con.unregister("_tmp_ingest")
        tables.append(table)

    return tables


def _decode_zip_name(name: bytes) -> str:
    """Try multiple encodings for ZIP member file names."""
    for enc in ("cp437", "gb18030", "gbk", "utf-8"):
        try:
            return name.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return name.decode("utf-8", errors="replace")


def ingest_uploaded(con, uf, rule: Rule | None = None) -> list[str] | str:
    """Dispatch uploaded file to the appropriate ingestion path.

    Returns a single table name (str) for simple files, or a list of table
    names for multi-sheet Excel / ZIP archives.
    """
    name = Path(uf.name)
    ext = name.suffix.lower()
    data = uf.read()
    size = len(data)

    # ZIP archive: extract to temp dir and recursively ingest inner files
    if ext == ".zip":
        tables: list[str] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with zipfile.ZipFile(BytesIO(data), "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    member_name = _decode_zip_name(info.filename.encode("utf-8") if isinstance(info.filename, str) else info.filename)
                    member_path = tmp_path / member_name
                    member_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(member_path, "wb") as dst:
                        dst.write(src.read())
                    # Recursively ingest supported files
                    inner_ext = member_path.suffix.lower()
                    if inner_ext in (".xlsx", ".xls"):
                        with open(member_path, "rb") as f:
                            inner_data = f.read()
                        sheet_tables = ingest_excel_sheets(con, inner_data, member_name, rule=rule)
                        tables.extend(sheet_tables)
                    elif inner_ext in SUPPORTED_EXTS - {".zip"}:
                        with open(member_path, "rb") as f:
                            inner_data = f.read()
                        table = _make_table_name(member_name)
                        if inner_ext in (".xlsx", ".xls") or len(inner_data) < SMALL_THRESHOLD:
                            result = _pandas_ingest(con, inner_data, inner_ext, table, rule=rule)
                        else:
                            result = _duckdb_ingest(con, inner_data, inner_ext, table, rule=rule)
                        if result:
                            tables.append(result)
        return tables

    # Multi-sheet Excel
    if ext in (".xlsx", ".xls"):
        return ingest_excel_sheets(con, data, uf.name, rule=rule)

    # Single-table file
    table = _make_table_name(uf.name)
    try:
        if ext in (".xlsx", ".xls") or size < SMALL_THRESHOLD:
            result = _pandas_ingest(con, data, ext, table, rule=rule)
        else:
            result = _duckdb_ingest(con, data, ext, table, rule=rule)
        return result if result else table
    except Exception as e:
        raise RuntimeError(f"导入失败 {uf.name}: {e}") from e


def ingest_file(con, path: Path, rule: Rule | None = None) -> str | None:
    """导入磁盘上已有的文件 —— 始终使用 DuckDB 原生方式（无需临时文件）。"""
    table = _make_table_name(path.name)
    ext = path.suffix.lower()
    p = str(path).replace("'", "''")
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(path)
            if rule and rule.input_columns:
                available = set(df.columns)
                keep = [c for c in rule.input_columns if c in available]
                if keep:
                    df = df[keep]
            con.register("_tmp_ingest", df)
            quoted_cols = ", ".join(quote_identifier(c) for c in df.columns)
            con.execute(f'CREATE OR REPLACE TABLE {quote_identifier(table)} AS SELECT {quoted_cols} FROM _tmp_ingest')
            con.unregister("_tmp_ingest")
        elif ext == ".csv":
            con.execute(f"""
                CREATE OR REPLACE TABLE {quote_identifier(table)} AS
                SELECT * FROM read_csv_auto('{p}',
                    header=true, ignore_errors=true,
                    sample_size=-1, auto_detect=true)
            """)
        elif ext == ".parquet":
            con.execute(f'CREATE OR REPLACE TABLE {quote_identifier(table)} AS SELECT * FROM read_parquet(\'{p}\')')
        elif ext == ".json":
            con.execute(f"""
                CREATE OR REPLACE TABLE {quote_identifier(table)} AS
                SELECT * FROM read_json_auto('{p}',
                    auto_detect=true, sample_size=-1, ignore_errors=true)
            """)
        else:
            return None
        return table
    except:
        return None


# ── Fingerprint helpers for deduplication ─────────────────────────────────────

def record_fingerprint(path: Path, log_path: Path) -> None:
    """Append a file fingerprint (name, size, mtime) to the JSONL log."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fp = {
        "name": path.name,
        "size": path.stat().st_size,
        "mtime": path.stat().st_mtime,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(fp, ensure_ascii=False) + "\n")


def is_new_file(path: Path, log_path: Path) -> bool:
    """Return True if *path* has not been recorded in the fingerprint log."""
    if not log_path.exists():
        return True
    current = {
        "name": path.name,
        "size": path.stat().st_size,
        "mtime": path.stat().st_mtime,
    }
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recorded = json.loads(line)
                if recorded == current:
                    return False
            except json.JSONDecodeError:
                continue
    return True
