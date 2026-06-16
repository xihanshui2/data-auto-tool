import streamlit as st
import pandas as pd
import duckdb

@st.cache_data(ttl=300, show_spinner=False)
def get_table_metadata(_con, table: str) -> dict:
    """不将数据加载到内存，仅检索表结构和行数。"""
    info = _con.execute(f'DESCRIBE "{table}"').fetchall()

    num_cols, cat_cols, date_cols = [], [], []

    for col_name, col_type, null_val, key, def_val, extra in info:
        ct = col_type.upper()
        if any(t in ct for t in ['INT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC']):
            num_cols.append(col_name)
        elif any(t in ct for t in ['DATE', 'TIME', 'TIMESTAMP']):
            date_cols.append(col_name)
        else:
            cat_cols.append(col_name)

    row_count = _con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    return {
        "columns": [r[0] for r in info],
        "num_cols": num_cols,
        "cat_cols": cat_cols,
        "date_cols": date_cols,
        "row_count": row_count
    }

@st.cache_data(ttl=300, show_spinner=False)
def load_preview(_con, table: str, n: int = 100) -> pd.DataFrame:
    """只取前 N 行预览 —— 即使是大表也很快。"""
    return _con.execute(f'SELECT * FROM "{table}" LIMIT {n}').df()

@st.cache_data(ttl=300, show_spinner=False)
def load_row_count(table: str) -> int:
    """不拉取整张表，仅统计行数。"""
    from core.db import get_con
    _con = get_con("mallard_auto.duckdb")
    return _con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

def smart_summary_native(con, table_name: str, meta: dict) -> str:
    """完全在数据库引擎内分析数据集统计信息。"""
    rows = meta["row_count"]
    cols = len(meta["columns"])

    label = "✨ 清洗后的数据集" if table_name.endswith("_cleaned") else "数据集"
    lines = [f"{label} <b>{table_name}</b> 包含 <b>{rows:,} 行</b>和 <b>{cols} 列</b>。"]

    parts = []
    if meta["num_cols"]:  parts.append(f"{len(meta['num_cols'])} 个数值列")
    if meta["cat_cols"]:  parts.append(f"{len(meta['cat_cols'])} 个分类列")
    if meta["date_cols"]: parts.append(f"{len(meta['date_cols'])} 个日期时间列")
    if parts: lines.append(f"列类型：{', '.join(parts)}。")

    if rows > 0:
        null_selects = [f'SUM(CASE WHEN "{c}" IS NULL THEN 1 ELSE 0 END) AS "{c}"' for c in meta["columns"]]
        null_query = f'SELECT {",".join(null_selects)} FROM "{table_name}"'
        null_counts = con.execute(null_query).fetchone()

        dirty = []
        for col_name, null_count in zip(meta["columns"], null_counts):
            if null_count > 0:
                dirty.append((col_name, round(null_count / rows * 100, 1)))

        dirty = sorted(dirty, key=lambda x: x[1], reverse=True)

        if not dirty:
            lines.append("✅ <b>没有缺失值</b> —— 该数据集很干净。")
        else:
            alerts = [f"<b>{c}</b> ({v}%)" for c, v in dirty[:3]]
            lines.append(f"⚠️ <b>检测到脏数据</b>，位于：{', '.join(alerts)}。")

    return " ".join(lines)
