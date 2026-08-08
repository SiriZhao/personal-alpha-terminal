# Personal Alpha Terminal 0.9.0 Research Preview

## 便携版

先将 `PersonalAlphaTerminal-0.9.0-ResearchPreview-windows-x64.zip` 完整解压到普通文件夹，保留 `_internal` 等完整目录，然后双击 `PersonalAlphaTerminal.exe`。不能只复制单个 EXE，也不能从压缩软件预览窗口直接运行。

## 安装版

若交付目录包含 `PersonalAlphaTerminal-0.9.0-ResearchPreview-Setup.exe`，可双击按当前用户安装；无需管理员权限和外部 Python。若未包含，说明构建机没有可信 Inno Setup，安装器在本轮被环境阻塞。

首次启动会创建 `%LOCALAPPDATA%\PersonalAlphaTerminal`、初始化/迁移 SQLite、运行自检并直接打开 Dashboard。市场、数据源与 AI Provider 可在应用内设置；这些非关键配置不会阻塞进入。卸载默认保留该用户数据目录。

服务只监听 `127.0.0.1`。API Key 保存到 Windows Credential Manager，不进入安装目录。构建未签名，Windows SmartScreen 可能显示未知发布者；请先核对 `checksums\SHA256SUMS.txt`，不要关闭系统安全功能。

本软件只提供个人研究与风险分析，不自动交易，不构成投资建议。
