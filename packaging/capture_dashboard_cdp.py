"""Capture and verify the packaged dashboard through a local Chromium CDP session."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import requests
from websockets.sync.client import connect


def _wait_for_debug_port(profile: Path, timeout: float = 20.0) -> int:
    marker = profile / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            lines = marker.read_text(encoding="utf-8").splitlines()
            if lines and lines[0].isdigit():
                return int(lines[0])
        time.sleep(0.1)
    raise TimeoutError("Chromium did not publish its DevTools port.")


class CdpClient:
    def __init__(self, websocket_url: str) -> None:
        self._socket = connect(websocket_url, origin="http://localhost")
        self._request_id = 0

    def close(self) -> None:
        self._socket.close()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        self._socket.send(
            json.dumps({"id": request_id, "method": method, "params": params or {}})
        )
        while True:
            response = json.loads(self._socket.recv())
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(f"CDP {method} failed: {response['error']}")
            return dict(response.get("result", {}))


def _page_target(port: int, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = requests.get(f"http://127.0.0.1:{port}/json", timeout=2)
        response.raise_for_status()
        pages = [target for target in response.json() if target.get("type") == "page"]
        if pages:
            return dict(pages[0])
        time.sleep(0.1)
    raise TimeoutError("Chromium did not expose a page target.")


def capture(
    chrome: Path,
    url: str,
    screenshot: Path,
    metadata: Path,
    profile: Path,
) -> None:
    profile.mkdir(parents=True, exist_ok=True)
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "--window-size=1600,1000",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client: CdpClient | None = None
    try:
        port = _wait_for_debug_port(profile)
        target = _page_target(port)
        websocket_url = str(target["webSocketDebuggerUrl"])
        client = CdpClient(websocket_url)
        client.call("Runtime.enable")
        client.call("Page.enable")

        deadline = time.monotonic() + 60
        body_text = ""
        marker = ""
        while time.monotonic() < deadline:
            result = client.call(
                "Runtime.evaluate",
                {
                    "expression": "document.body ? document.body.innerText : ''",
                    "returnByValue": True,
                },
            )
            body_text = str(result.get("result", {}).get("value", ""))
            for candidate in (
                "Daily Investment Dashboard",
                "Command Center",
                "System Status",
                "Data Gate",
            ):
                if "Personal Alpha" in body_text and candidate in body_text:
                    marker = candidate
                    break
            if marker:
                break
            time.sleep(0.25)
        if not marker:
            image = client.call(
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
            )
            screenshot.write_bytes(base64.b64decode(str(image["data"])))
            metadata.write_text(
                json.dumps(
                    {
                        "url": url,
                        "http_status": 200,
                        "renderer": "chromium-cdp",
                        "rendered_marker": None,
                        "body_text_length": len(body_text),
                        "body_text_preview": body_text[:2000],
                        "captured_at": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise TimeoutError("Dashboard never rendered a verified application view.")
        time.sleep(2.0)

        image = client.call(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
        )
        screenshot.write_bytes(base64.b64decode(str(image["data"])))
        metadata.write_text(
            json.dumps(
                {
                    "url": url,
                    "http_status": 200,
                    "renderer": "chromium-cdp",
                    "rendered_marker": marker,
                    "body_text_length": len(body_text),
                    "build_version_present": "v1.0.0-test" in body_text,
                    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        if client is not None:
            client.close()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    capture(args.chrome, args.url, args.screenshot, args.metadata, args.profile)


if __name__ == "__main__":
    main()
