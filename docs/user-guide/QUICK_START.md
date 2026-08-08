# 快速开始

适用版本：Personal Alpha Terminal 0.9.0 Research Preview。

1. 完整解压 portable ZIP，保留 `_internal` 等目录；不要从压缩软件预览窗口直接运行 EXE。
2. 双击 `PersonalAlphaTerminal.exe`，应用会直接进入 Dashboard。
3. 首页欢迎卡不会阻塞使用；可在设置中选择市场、数据源和 AI Provider。
4. 无 API Key 时保持“禁用 AI”或使用明确标识的 Mock；系统其余部分仍可运行。
5. 打开“数据源”，确认目标市场与资产类型是否为“可配置”。
6. 先运行数据质量检查，再使用研究模块。BLOCKED 状态下不要据此决策。
7. 在“系统诊断”查看数据库、数据源、AI、磁盘、日志和最近错误。
8. 在“系统诊断”创建首次手动备份。

用户数据默认目录是 `%LOCALAPPDATA%\PersonalAlphaTerminal`。关闭主程序后如仍有本地服务，运行 `Stop Personal Alpha Terminal.cmd`。

首页无行情不是故障：空数据库会明确提示“尚未导入可认证的市场数据”，不会填充虚构价格。首次真实数据接入请阅读 [DATA_SOURCE_GUIDE.md](DATA_SOURCE_GUIDE.md)。

本版本不自动交易，研究结论不构成投资建议。
