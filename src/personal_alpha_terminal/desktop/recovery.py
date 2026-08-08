from __future__ import annotations

from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True, slots=True)
class RecoveryStatus:
    stage: str
    error_type: str
    guidance: str


def recovery_html(status: RecoveryStatus) -> bytes:
    stage = escape(status.stage)
    error_type = escape(status.error_type)
    guidance = escape(status.guidance)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Personal Alpha Terminal · System Status</title>
<style>
body{{margin:0;background:#0b1020;color:#e8edf8;font:15px/1.6 system-ui,sans-serif}}
main{{max-width:860px;margin:8vh auto;padding:32px}}
.card{{background:#141b2d;border:1px solid #2b3855;border-radius:18px;padding:28px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:24px 0}}
.metric{{background:#0f1628;border-radius:12px;padding:16px;color:#aebbd2}}
.metric b{{display:block;color:#f3f6fc;font-size:20px}}
.blocked{{color:#ffbd7a}}code{{color:#9fb7ff}}p{{color:#b7c2d7}}
</style></head><body><main><div class="card">
<small>RESEARCH PREVIEW · SAFE STARTUP</small>
<h1>Personal Alpha Terminal</h1>
<p>主界面资源或运行环境不完整。系统已进入本地安全诊断模式，而不是返回 500。</p>
<div class="grid"><div class="metric">Database<b>Warning</b></div>
<div class="metric">Data Gate<b class="blocked">BLOCKED</b></div>
<div class="metric">AI<b>Disabled</b></div></div>
<h2>System Status</h2><p>阶段：<code>{stage}</code><br>
错误类型：<code>{error_type}</code></p><p>{guidance}</p>
<p>当前页面不包含市场结论，不会生成排名、仓位或调仓清单。</p>
</div></main></body></html>""".encode()


def build_recovery_server(
    host: str,
    port: int,
    status: RecoveryStatus,
) -> ThreadingHTTPServer:
    payload = recovery_html(status)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/_stcore/health":
                body = b"ok"
                content_type = "text/plain; charset=utf-8"
            else:
                body = payload
                content_type = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)
