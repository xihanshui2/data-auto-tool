import streamlit as st
import importlib
from pathlib import Path

from core.db import get_con

st.set_page_config(page_title="MALLARD 自动化处理", page_icon="🦆", layout="wide")

# ── 加载 CSS ──────────────────────────────────────────────────────────────────
_css_path = Path(__file__).parent / "config" / "styles.css"
if _css_path.exists():
    st.markdown(f"<style>{_css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

# ── 数据库连接 ────────────────────────────────────────────────────────────────
con = get_con("mallard_auto.duckdb")

# ── 侧边栏导航 ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🦆 MALLARD 自动化")
    st.caption("本地数据自动化处理")
    st.divider()
    page = st.radio("页面", ["规则配置", "数据接入", "处理与归档"])

# ── 页面路由 ──────────────────────────────────────────────────────────────────
_page_map = {
    "规则配置": "ui.rules_page",
    "数据接入": "ui.ingest_page",
    "处理与归档": "ui.process_page",
}

_mod_name = _page_map.get(page)
_placeholder = True

if _mod_name:
    try:
        _mod = importlib.import_module(_mod_name)
        if hasattr(_mod, "render"):
            _mod.render()
            _placeholder = False
    except Exception as _e:
        st.error(f"加载页面失败: {_e}")

if _placeholder:
    st.info("页面建设中")
