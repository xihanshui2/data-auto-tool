"""规则配置页面：增删改查 TOML 规则。"""

from __future__ import annotations

import streamlit as st
from datetime import datetime, timezone

from core.models import CleanStep, Rule
from core.rules import delete_rule, load_rules, save_rule, validate_rule_data


def _safe_list(value: list[str] | None) -> list[str]:
    return value if value is not None else []


def render():
    st.header("规则配置")
    st.caption("按文件类型创建、编辑、删除数据处理规则。规则持久化为 TOML 文件。")

    # ── 规则列表 ───────────────────────────────────────────────────────────────
    rules = load_rules()

    if rules:
        st.subheader(f"现有规则 ({len(rules)} 条)")
        cols = st.columns([2, 2, 3, 2, 2, 1, 1])
        headers = ["名称", "文件类型", "拆分字段", "输出格式", "启用", "", ""]
        for c, h in zip(cols, headers):
            c.markdown(f"**{h}**")

        for rule in rules:
            cols = st.columns([2, 2, 3, 2, 2, 1, 1])
            cols[0].write(rule.name)
            cols[1].write(rule.file_type)
            cols[2].write(", ".join(rule.split_keys))
            cols[3].write(rule.output_format)
            cols[4].write("是" if rule.enabled else "否")

            edit_key = f"edit_{rule.name}"
            delete_key = f"delete_{rule.name}"

            if cols[5].button("编辑", key=edit_key):
                st.session_state["edit_rule_name"] = rule.name
                st.rerun()

            if cols[6].button("删除", key=delete_key):
                delete_rule(rule.name)
                st.success(f"已删除规则：{rule.name}")
                st.rerun()
    else:
        st.info("暂无规则，请通过下方表单创建。")

    st.divider()

    # ── 编辑/新建表单 ──────────────────────────────────────────────────────────
    edit_name = st.session_state.get("edit_rule_name")
    if edit_name:
        existing = next((r for r in rules if r.name == edit_name), None)
        st.subheader(f"编辑规则：{edit_name}")
    else:
        existing = None
        st.subheader("新建规则")

    with st.form("rule_form", clear_on_submit=False):
        # 基础信息
        name = st.text_input("规则名称 *", value=existing.name if existing else "")
        file_type = st.text_input(
            "文件类型 * (如 日报/周报/月报/明细)",
            value=existing.file_type if existing else "",
        )
        enabled = st.checkbox("启用", value=existing.enabled if existing else True)

        st.markdown("#### 数据源配置")
        sheet_names_str = st.text_input(
            "Sheet 名称列表（留空表示导入所有 Sheet，多个用逗号分隔）",
            value=",".join(existing.sheet_names) if existing and existing.sheet_names else "",
        )
        input_columns_str = st.text_input(
            "输入字段白名单（留空表示保留全部，多个用逗号分隔）",
            value=",".join(existing.input_columns) if existing and existing.input_columns else "",
        )

        st.markdown("#### 清洗步骤")
        all_steps = [step.value for step in CleanStep]
        default_steps = [s.value for s in existing.clean_steps] if existing else []
        clean_steps_selected = st.multiselect(
            "选择要执行的清洗步骤（按选择顺序执行）",
            options=all_steps,
            default=default_steps,
        )

        st.markdown("#### 字段映射（旧名 -> 新名）")
        field_mapping: dict[str, str] = {}
        if existing and existing.field_mapping:
            for idx, (old, new) in enumerate(existing.field_mapping.items()):
                cols = st.columns(2)
                old_val = cols[0].text_input(f"原字段 {idx+1}", value=old, key=f"fm_old_{idx}")
                new_val = cols[1].text_input(f"新字段 {idx+1}", value=new, key=f"fm_new_{idx}")
                if old_val and new_val:
                    field_mapping[old_val] = new_val
        else:
            for idx in range(3):
                cols = st.columns(2)
                old_val = cols[0].text_input(f"原字段 {idx+1}", key=f"fm_old_{idx}")
                new_val = cols[1].text_input(f"新字段 {idx+1}", key=f"fm_new_{idx}")
                if old_val and new_val:
                    field_mapping[old_val] = new_val

        st.markdown("#### 计算列（列名 -> DuckDB SQL 表达式）")
        computed_columns: dict[str, str] = {}
        if existing and existing.computed_columns:
            for idx, (col, expr) in enumerate(existing.computed_columns.items()):
                cols = st.columns(2)
                col_val = cols[0].text_input(f"列名 {idx+1}", value=col, key=f"cc_col_{idx}")
                expr_val = cols[1].text_input(f"表达式 {idx+1}", value=expr, key=f"cc_expr_{idx}")
                if col_val and expr_val:
                    computed_columns[col_val] = expr_val
        else:
            for idx in range(3):
                cols = st.columns(2)
                col_val = cols[0].text_input(f"列名 {idx+1}", key=f"cc_col_{idx}")
                expr_val = cols[1].text_input(f"表达式 {idx+1}", key=f"cc_expr_{idx}")
                if col_val and expr_val:
                    computed_columns[col_val] = expr_val

        st.markdown("#### 拆分与输出")
        split_keys_str = st.text_input(
            "拆分字段 *（多级用逗号分隔，如：地市,县）",
            value=",".join(existing.split_keys) if existing else "",
        )
        output_columns_str = st.text_input(
            "输出字段白名单（留空表示输出全部，多个用逗号分隔）",
            value=",".join(existing.output_columns) if existing and existing.output_columns else "",
        )
        output_format = st.selectbox(
            "输出格式",
            options=["excel", "csv", "parquet"],
            index=0 if not existing else ["excel", "csv", "parquet"].index(existing.output_format),
        )
        output_template = st.text_input(
            "文件名模板",
            value=existing.output_template if existing else "{date}_{file_type}_{last_split_value}",
        )
        output_dir = st.text_input(
            "输出目录（留空使用全局默认）",
            value=existing.output_dir if existing else "",
        )

        submitted = st.form_submit_button("保存规则")

        if submitted:
            # 解析列表字段
            sheet_names = [s.strip() for s in sheet_names_str.split(",") if s.strip()] or None
            input_columns = [s.strip() for s in input_columns_str.split(",") if s.strip()] or None
            split_keys = [s.strip() for s in split_keys_str.split(",") if s.strip()]
            output_columns = [s.strip() for s in output_columns_str.split(",") if s.strip()] or None
            clean_steps = [CleanStep(s) for s in clean_steps_selected]

            data = {
                "name": name,
                "file_type": file_type,
                "version": 1,
                "sheet_names": sheet_names,
                "input_columns": input_columns,
                "clean_steps": clean_steps,
                "field_mapping": field_mapping,
                "computed_columns": computed_columns,
                "split_keys": split_keys,
                "output_columns": output_columns,
                "output_format": output_format,
                "output_template": output_template,
                "output_dir": output_dir,
                "enabled": enabled,
                "created_at": existing.created_at if existing else datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }

            try:
                rule = validate_rule_data(data)
                save_rule(rule)
                st.success(f"规则 '{rule.name}' 保存成功！")
                if "edit_rule_name" in st.session_state:
                    del st.session_state["edit_rule_name"]
                st.rerun()
            except Exception as exc:
                st.error(f"保存失败：{exc}")

    # 取消编辑按钮
    if edit_name:
        if st.button("取消编辑"):
            if "edit_rule_name" in st.session_state:
                del st.session_state["edit_rule_name"]
            st.rerun()
