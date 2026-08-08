# DeepSeek 配置

在“设置 → AI Provider”选择 DeepSeek，并配置：

- API Key：保存到 Windows Credential Manager；
- Base URL：默认 `https://api.deepseek.com`，必须使用 HTTPS；
- Model：使用账户实际可用的模型名称；
- Temperature：研究摘要建议从较低值开始；
- 请求超时与最大重试次数：按网络条件调整。

保存后先运行 Provider 配置检查，再用不含持仓隐私的研究证据生成测试报告。没有密钥时无需重复配置，选择“禁用 AI”即可继续使用其他模块。

如果连接失败，依次检查 HTTPS、模型权限、额度、系统时间和代理设置。系统不会自动创建、购买或打印 API Key。
