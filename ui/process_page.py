"""处理与归档页面：选择表、选择规则、执行流水线。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

from core.clean import clean_table
from core.db import get_con
from core.error_report import generate_error_report
from core.logger import ProcessingLogger
from core.models import Rule
from core.rules import load_rules
from core.split import split_by_columns
from core.validate import validate_against_rule


def _list_tables(con) -> list[str]:
    """Return all user tables in the DuckDB connection."""
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return sorted([r[0] for r in rows])


def _build_dir_tree(path: Path, prefix: str = "") -> str:
    """Recursively build a text tree of *path* for display."""
    lines: list[str] = []
    if not path.exists():
        return ""
    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir():
            extension = "    " if is_last else "│   "
            lines.append(_build_dir_tree(entry, prefix + extension))
    return "\n".join(lines)


def render():
    st.header("处理与归档")
    st.caption("选择已导入的表和处理规则，执行清洗、拆分与归档。")

    con = get_con("mallard_auto.duckdb")

    # ── 选择表 ───────────────────────────────────────────────────────────────
    tables = _list_tables(con)
    if not tables:
        st.warning("数据库中暂无表。请先前往「数据接入」页面上传或导入数据。")
        return

    selected_table = st.selectbox("选择待处理表", tables)

    # 预览表结构
    with st.expander("表结构预览"):
        try:
            schema = con.execute(f"DESCRIBE \"{selected_table}\"").fetchdf()
            st.dataframe(schema, use_container_width=True)
        except Exception as e:
            st.error(f"无法读取表结构: {e}")

    # ── 选择规则 ───────────────────────────────────────────────────────────────
    rules = load_rules()
    enabled_rules = [r for r in rules if r.enabled]
    if not enabled_rules:
        st.warning("暂无启用的规则。请先前往「规则配置」页面创建规则。")
        return

    rule_names = {f"{r.name} ({r.file_type})": r for r in enabled_rules}
    selected_rule_name = st.selectbox("选择处理规则", list(rule_names.keys()))
    selected_rule: Rule = rule_names[selected_rule_name]

    with st.expander("规则详情"):
        st.json(selected_rule.model_dump_for_toml())

    st.divider()

    # ── 执行流水线 ───────────────────────────────────────────────────────────
    logger = ProcessingLogger()
    progress_bar = st.progress(0.0)
    status_text = st.empty()

    if st.button("开始处理", type="primary"):
        steps = ["校验", "清洗", "拆分归档"]
        step_count = len(steps)

        try:
            # Step 1: Validation
            status_text.text("步骤 1/3: 校验规则...")
            progress_bar.progress(0.0)
            errors = validate_against_rule(con, selected_table, selected_rule)
            if errors:
                for err in errors:
                    logger.log("校验", "error", err)
                st.error("校验失败，请修正规则或数据后重试。")
                st.markdown(logger.to_markdown(), unsafe_allow_html=True)
                return
            logger.log("校验", "ok", "规则校验通过")

            # Step 2: Cleaning
            status_text.text("步骤 2/3: 清洗数据...")
            progress_bar.progress(1.0 / step_count)
            final_table, clean_report = clean_table(con, selected_table, selected_rule)
            logger.log("清洗", "ok", f"清洗完成，结果表: {final_table}")
            for step_info in clean_report.get("steps", []):
                logger.log(
                    "清洗子步骤",
                    "ok",
                    f"{step_info['step']} -> {step_info.get('table', 'N/A')}",
                )

            # Step 3: Split & Archive
            status_text.text("步骤 3/3: 拆分归档...")
            progress_bar.progress(2.0 / step_count)
            result_paths = split_by_columns(
                con, final_table, selected_rule, logger
            )
            logger.log("归档", "ok", f"共生成 {len(result_paths)} 个文件")

            progress_bar.progress(1.0)
            status_text.text("处理完成！")

            st.success("处理完成！")

            # Show logs
            with st.expander("处理日志", expanded=True):
                st.markdown(logger.to_markdown(), unsafe_allow_html=True)

            # Show output tree
            if result_paths:
                st.subheader("输出目录结构")
                # Find common parent of all outputs
                first_path = next(iter(result_paths.values()))
                tree_root = first_path.parent
                # Walk up to find the rule output dir root
                while tree_root.name not in (selected_rule.output_dir or "output"):
                    parent = tree_root.parent
                    if parent == tree_root:
                        break
                    tree_root = parent

                tree_text = _build_dir_tree(tree_root)
                st.code(tree_text or "（目录为空）", language="text")

                # Download buttons for each output
                st.subheader("下载输出文件")
                cols = st.columns(min(len(result_paths), 3))
                for idx, (combo, path) in enumerate(result_paths.items()):
                    with cols[idx % len(cols)]:
                        if path.exists():
                            with open(path, "rb") as f:
                                st.download_button(
                                    label=f"{combo}",
                                    data=f.read(),
                                    file_name=path.name,
                                    mime="application/octet-stream",
                                    key=f"dl_{idx}",
                                )

        except Exception as exc:
            logger.log("处理", "error", str(exc))
            st.error(f"处理过程中发生错误: {exc}")
            with st.expander("处理日志", expanded=True):
                st.markdown(logger.to_markdown(), unsafe_allow_html=True)

            # Generate error report Excel
            try:
                error_entries = [
                    {
                        "error_type": type(exc).__name__,
                        "table": selected_table,
                        "row_context": "—",
                        "reason": str(exc),
                        "suggestion": "请检查规则配置或数据格式",
                    }
                ]
                # Also include any validation errors that were already logged
                for entry in logger.entries:
                    if entry["status"] == "error":
                        error_entries.append(
                            {
                                "error_type": entry["step"],
                                "table": selected_table,
                                "row_context": "—",
                                "reason": entry["message"],
                                "suggestion": "请检查规则配置或数据格式",
                            }
                        )

                report_path = Path("output") / f"error_report_{selected_table}.xlsx"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                generate_error_report(error_entries, report_path)

                with open(report_path, "rb") as f:
                    st.download_button(
                        label="⬇ 下载错误报告 (Excel)",
                        data=f.read(),
                        file_name=report_path.name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="error_report_dl",
                    )
            except Exception as report_exc:
                st.warning(f"无法生成错误报告: {report_exc}")
