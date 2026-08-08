# Windows console packaging

验证运行时：Python 3.14.3、PyInstaller 6.21.0、Textual 8.2.8、Rich 15.0.0、Typer 0.27.0。

```powershell
$env:PAT_BUILD_PYTHON = ".\.venv\Scripts\python.exe"
.\packaging\build_console_preview.ps1 -Version 1.1.0-console-preview
```

构建采用 console-enabled PyInstaller one-folder，不使用 `--windowed`，也不打包 Streamlit/Plotly 作为默认 UI。脚本在项目内的中文空格测试路径中执行 `doctor` 和 TUI smoke，再生成 ZIP 与 SHA256。

独立全新 Windows VM 和商业代码签名不在本地 smoke test 能力范围内，不能标记为已通过。
