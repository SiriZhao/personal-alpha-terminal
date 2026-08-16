# Personal Alpha Terminal 运维与恢复指南

## 正常每日操作

1. 先运行 `python main.py doctor` 检查环境。
2. 运行 `python main.py daily` 生成当日决策。
3. 运行 `python main.py cockpit --run-id <当日run_id>` 查看中文决策驾驶舱。
4. 只执行已接受的手动建议，不要使用任何自动下单功能。

## 程序打不开

1. 查看 `var/logs/terminal-heartbeat.json`。
2. 确认 Python 和依赖已安装。
3. 不要删除数据库重装。
4. 收集 `doctor` 输出和日志后排查。

## 数据更新失败

1. 检查 provider 状态：`python main.py data-provider status`。
2. 如果 provider 失败，确认 fallback 是否启用。
3. 不要用未来或手工编辑的数据覆盖正式 PIT 数据。

## daily 中断

1. 查看 `reports/evidence-bundles/<run_id>/run_manifest.json`。
2. 如果 bundle 是 `STAGED`，不要当作正式结果。
3. 修复后重新运行，旧 STAGED 记录保留作为证据。

## run bundle verify

`python main.py run-bundle verify <run_id>`

## ledger backup

`python main.py` 当前通过 `core/local_backup.py` 支持备份；备份写入 `var/backups` 或指定目录。备份不包含 secrets。

## restore

恢复前先保留当前数据库副本。使用备份验证哈希后再恢复；任何恢复都要有 provenance。

## 数据库损坏

1. 先备份。
2. 运行 `PRAGMA integrity_check`。
3. 如损坏，从最近有效备份恢复，不要删除真实用户 ledger。

## 如何确认今天不应交易

当 data gate、PIT、factor、alpha、risk 任一失败，或 cockpit 显示 `NO_ACTION`，不应交易。

## 如何更新软件

先在干净副本运行 `pytest -q`、`ruff check .`、strict mypy、secret scan，再更新。

## 如何回滚

保留旧 commit 和 release 包；回滚后重新验证数据库、ledger、run bundle replay。

## 如何收集诊断包

收集 `var/logs`、`doctor` 输出、最近 daily run certificate、bundle verify 输出。不要在诊断包中包含 token 或密钥。
