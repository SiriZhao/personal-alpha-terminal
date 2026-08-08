# 故障排查

## 无法启动

1. 查看 `%LOCALAPPDATA%\PersonalAlphaTerminal\boot.log` 与 `startup-status.json`。
2. 确认磁盘可写且空间充足。
3. 运行 `PersonalAlphaTerminal.exe --stop` 清理仍存活的本应用实例；启动器会校验进程身份。
4. 不要手工删除数据库。先在“系统诊断”导出脱敏诊断包。

## 页面空白或无行情

空数据库会显示空状态。进入“数据源”查看 capability 和质量门禁；不要导入未经认证的 Demo 数据冒充真实行情。

## 数据质量 BLOCKED

查看阻塞原因：常见原因包括时间戳缺失、来源冲突、单位未知、OHLC 异常、重复日期、复权冲突或非交易日数据。修复原始数据后重新运行 Validation，不要绕过门禁。

## 数据库锁定

先关闭重复窗口和后台进程，等待当前任务完成，再重启。系统使用单实例和事务；持续锁定时导出诊断包。

## AI 失败

未配置是正常状态。检查 Provider、HTTPS Base URL、模型名、超时、额度和 Credential Manager。密钥不得粘贴到日志或问题反馈。

## SmartScreen

个人预览版未商业签名，Windows 可能显示未知发布者。先核对 `SHA256SUMS.txt`，不要关闭 SmartScreen 或防病毒功能。
