import tempfile
import os
from io import BytesIO
import pandas as pd

def export_table(con, table: str, fmt: str) -> bytes:
    """将数据直接从 DuckDB 引擎导出到磁盘（Excel 除外）。"""
    if fmt == "Excel":
        buf = BytesIO()
        df_temp = con.execute(f'SELECT * FROM "{table}"').df()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df_temp.to_excel(w, index=False)
        return buf.getvalue()

    ext_map = {"CSV": ".csv", "Parquet": ".parquet", "JSON": ".json"}
    ext = ext_map[fmt]

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        p = tmp_path.replace("'", "''")
        if fmt == "CSV":
            con.execute(f"COPY \"{table}\" TO '{p}' (HEADER, FORMAT CSV)")
        elif fmt == "Parquet":
            con.execute(f"COPY \"{table}\" TO '{p}' (FORMAT PARQUET)")
        elif fmt == "JSON":
            con.execute(f"COPY \"{table}\" TO '{p}' (FORMAT JSON, ARRAY TRUE)")

        with open(tmp_path, "rb") as f:
            data = f.read()
        return data
    finally:
        try: os.unlink(tmp_path)
        except: pass
