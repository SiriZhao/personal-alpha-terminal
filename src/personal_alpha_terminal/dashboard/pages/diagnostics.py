from __future__ import annotations

from pathlib import Path

import streamlit as st

from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.diagnostics import (
    collect_diagnostics,
    create_diagnostic_bundle,
)
from personal_alpha_terminal.core.local_backup import (
    create_local_backup,
    list_backups,
    stage_restore,
)
from personal_alpha_terminal.core.product import default_application_data_dir
from personal_alpha_terminal.dashboard.components import page_header
from personal_alpha_terminal.dashboard.runtime import database_ready
from personal_alpha_terminal.dashboard.status import module_statuses

page_header("系统诊断", "查看本地运行状态，导出自动脱敏诊断包并管理个人预览备份。")
settings = get_settings()
root = default_application_data_dir()
summary = collect_diagnostics(settings, application_root=root)

metrics = st.columns(4)
metrics[0].metric("应用版本", summary.application)
metrics[1].metric("数据库", f"{summary.database_backend} · {summary.database_status}")
metrics[2].metric("AI Provider", summary.ai_provider_status)
metrics[3].metric("可用磁盘", f"{summary.free_disk_bytes / (1024**3):.1f} GB")

with st.expander("路径与环境", expanded=True):
    st.code(
        "\n".join(
            (
                f"Python: {summary.python_version}",
                f"Bundled runtime: {summary.bundled_runtime}",
                f"Data: {summary.data_directory}",
                f"Logs: {summary.log_directory}",
                f"Config: {summary.configuration_path}",
                f"Checked: {summary.checked_at}",
            )
        ),
        language=None,
    )
    if summary.latest_error:
        st.warning(f"最近错误：{summary.latest_error}")
    else:
        st.caption("最近日志中没有发现 ERROR/CRITICAL。")

st.subheader("模块状态")
st.dataframe(
    [
        {"模块": item.name, "状态": item.status, "说明": item.reason}
        for item in module_statuses(settings, database_ready=database_ready())
    ],
    width="stretch",
    hide_index=True,
)

diagnostic_columns = st.columns(2)
if diagnostic_columns[0].button("一键导出诊断包", type="primary", width="stretch"):
    archive = create_diagnostic_bundle(
        settings,
        application_root=root,
        output_directory=root / "diagnostics",
    )
    st.session_state["diagnostic_archive"] = str(archive)
archive_value = st.session_state.get("diagnostic_archive")
if isinstance(archive_value, str) and Path(archive_value).is_file():
    archive_path = Path(archive_value)
    diagnostic_columns[1].download_button(
        "下载脱敏诊断包",
        data=archive_path.read_bytes(),
        file_name=archive_path.name,
        mime="application/zip",
        width="stretch",
    )
st.caption("诊断包不包含数据库、API Key、Token 或精确持仓金额。")

st.subheader("本地备份与恢复")
backup_root = root / "backups"
if st.button("立即创建完整性校验备份"):
    try:
        created = create_local_backup(
            settings,
            application_root=root,
            backup_directory=backup_root,
        )
        st.success(f"备份已创建：{created.name}")
    except Exception as error:
        st.error(f"备份失败：{type(error).__name__}。请查看日志和磁盘空间。")

backups = list_backups(backup_root)
if backups:
    selected = st.selectbox(
        "备份列表",
        options=backups,
        format_func=lambda item: f"{item.archive.name} · {'有效' if item.valid else '无效'}",
    )
    st.write(
        f"创建时间：{selected.created_at} · 后端：{selected.database_backend} · "
        f"文件：{', '.join(selected.files)}"
    )
    if selected.issues:
        st.error("；".join(selected.issues))
    if st.button("恢复预览并安排下次启动恢复", disabled=not selected.valid):
        request = stage_restore(selected.archive, application_root=root)
        st.warning(f"恢复已安排：{request.name}。请正常关闭并重新启动程序。恢复前会自动保留安全快照。")
else:
    st.info("尚无本地备份。首次启动和每日启动会尝试创建一次备份。")

st.caption("API 密钥不进入普通备份。恢复在下次启动、数据库尚未打开时执行。")
