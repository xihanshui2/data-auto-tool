import streamlit as st
from pathlib import Path
from core.db import get_con
from core.ingest import ingest_uploaded, ingest_file
from core.watcher import scan_folder, mark_processed
from core.email import list_attachments, download_attachment
from core.rules import load_rules


def render():
    st.header("数据接入")

    # ── 规则选择（可选）─────────────────────────────────────────────────────────
    rules = load_rules()
    rule_names = ["（不使用规则）"] + [r.name for r in rules]
    selected_rule_name = st.selectbox("选择导入规则（可选）", rule_names)
    selected_rule = None
    if selected_rule_name != "（不使用规则）":
        selected_rule = next((r for r in rules if r.name == selected_rule_name), None)

    # ── Tab 布局：手动上传 / 文件夹扫描 / 邮件导入 ─────────────────────────────
    tab_upload, tab_folder, tab_email = st.tabs(["手动上传", "文件夹扫描", "邮件导入"])

    # ── 手动上传 ────────────────────────────────────────────────────────────────
    with tab_upload:
        st.subheader("手动上传文件")
        uploaded = st.file_uploader(
            "选择文件",
            type=["xlsx", "xls", "csv", "zip"],
            accept_multiple_files=True,
        )
        if uploaded:
            con = get_con("mallard_auto.duckdb")
            imported: list[str] = []
            for uf in uploaded:
                with st.spinner(f"正在导入 {uf.name} …"):
                    try:
                        result = ingest_uploaded(con, uf, rule=selected_rule)
                        if isinstance(result, list):
                            imported.extend(result)
                        else:
                            imported.append(result)
                    except Exception as e:
                        st.error(f"导入失败 {uf.name}: {e}")
            if imported:
                st.success(f"成功导入 {len(imported)} 个表：")
                st.write(imported)

    # ── 文件夹扫描 ───────────────────────────────────────────────────────────────
    with tab_folder:
        st.subheader("扫描文件夹自动导入")
        folder_path = st.text_input("文件夹路径", value="data/auto_input/")
        scan_btn = st.button("扫描并导入", key="folder_scan_btn")
        if scan_btn:
            target = Path(folder_path)
            if not target.exists():
                st.error(f"路径不存在：{folder_path}")
            else:
                new_files = scan_folder(target)
                if not new_files:
                    st.info("没有新文件需要导入（已全部处理过或文件夹为空）")
                else:
                    con = get_con("mallard_auto.duckdb")
                    imported: list[str] = []
                    failed: list[str] = []
                    for f in new_files:
                        with st.spinner(f"正在导入 {f.name} …"):
                            result = ingest_file(con, f, rule=selected_rule)
                            if result:
                                imported.append(result)
                            else:
                                failed.append(f.name)
                    mark_processed(new_files)
                    if imported:
                        st.success(f"成功导入 {len(imported)} 个表：")
                        st.write(imported)
                    if failed:
                        st.warning(f"以下文件导入失败：{failed}")

    # ── 邮件导入 ─────────────────────────────────────────────────────────────────
    with tab_email:
        st.subheader("从 IMAP 邮箱导入附件")
        with st.form("imap_form"):
            col1, col2 = st.columns(2)
            with col1:
                imap_server = st.text_input("IMAP 服务器", value="imap.qq.com")
                imap_username = st.text_input("用户名/邮箱")
            with col2:
                imap_port = st.number_input("端口", value=993, min_value=1, max_value=65535)
                imap_password = st.text_input("密码", type="password")
            list_btn = st.form_submit_button("列出附件")

        if list_btn:
            if not imap_username or not imap_password:
                st.error("请填写用户名和密码")
            else:
                imap_config = {
                    "server": imap_server,
                    "port": int(imap_port),
                    "username": imap_username,
                    "password": imap_password,
                }
                with st.spinner("正在连接邮箱 …"):
                    try:
                        attachments = list_attachments(imap_config)
                        st.session_state["imap_attachments"] = attachments
                        if not attachments:
                            st.info("未找到附件")
                        else:
                            st.success(f"找到 {len(attachments)} 个附件")
                    except Exception as e:
                        st.error(f"连接失败：{e}")
                        st.session_state["imap_attachments"] = []

        if "imap_attachments" in st.session_state and st.session_state["imap_attachments"]:
            attachments = st.session_state["imap_attachments"]
            st.write("---")
            st.write("选择要导入的附件：")
            selected_indices = []
            for i, att in enumerate(attachments):
                cols = st.columns([0.05, 0.25, 0.35, 0.20, 0.15])
                with cols[0]:
                    checked = st.checkbox("", key=f"att_chk_{i}")
                with cols[1]:
                    st.text(att["filename"])
                with cols[2]:
                    st.text(att["subject"])
                with cols[3]:
                    st.text(f"{att['size'] / 1024:.1f} KB")
                with cols[4]:
                    st.text(att["msg_id"])
                if checked:
                    selected_indices.append(i)

            if selected_indices and st.button("导入选中附件", key="email_import_btn"):
                con = get_con("mallard_auto.duckdb")
                imported: list[str] = []
                failed: list[str] = []
                imap_config = {
                    "server": imap_server,
                    "port": int(imap_port),
                    "username": imap_username,
                    "password": imap_password,
                }
                for idx in selected_indices:
                    att = attachments[idx]
                    with st.spinner(f"正在下载 {att['filename']} …"):
                        try:
                            data = download_attachment(imap_config, att["msg_id"], att["filename"])
                            from io import BytesIO

                            class _UploadedFile:
                                def __init__(self, name, data):
                                    self.name = name
                                    self._data = data

                                def read(self):
                                    return self._data

                            uf = _UploadedFile(att["filename"], data)
                            result = ingest_uploaded(con, uf, rule=selected_rule)
                            if isinstance(result, list):
                                imported.extend(result)
                            else:
                                imported.append(result)
                        except Exception as e:
                            failed.append(f"{att['filename']}: {e}")
                if imported:
                    st.success(f"成功导入 {len(imported)} 个表：")
                    st.write(imported)
                if failed:
                    st.warning(f"以下附件导入失败：{failed}")
