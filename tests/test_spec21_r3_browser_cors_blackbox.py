"""SPEC-21 R3 black-box checks using the published launcher and HTTP contract."""

from __future__ import annotations

import http.server
import json
import re
import os
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager

import pytest
import requests


APP_URL = "http://127.0.0.1:8000"
PROXY_HOST = "127.0.0.1"
HOSTILE = '<img id="provider-payload" src="x" onerror="document.documentElement.dataset.providerXss=\'executed\'">'


def _wait_for_public_app() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{APP_URL}/api/health", timeout=1).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.25)
    pytest.fail("documented demo launcher did not expose /api/health within 30 seconds")


def _listener_pid() -> int | None:
    output = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"127\.0\.0\.1:8000\s+0\.0\.0\.0:0\s+LISTENING\s+(\d+)", output)
    return int(match.group(1)) if match else None


@pytest.fixture(scope="module")
def public_demo():
    assert _listener_pid() is None, "port 8000 must be free before the public-launcher test"
    process = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "run_demo.ps1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_public_app()
        listener_pid = _listener_pid()
        assert listener_pid is not None, "launcher health responded without a local listener"
        yield
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
        )
        if "listener_pid" in locals():
            subprocess.run(
                ["taskkill", "/PID", str(listener_pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )


@contextmanager
def hostile_routes_proxy():
    class Proxy(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?", 1)[0] == "/api/routes":
                body = json.dumps(
                    [{"route_id": 99, "route_no": HOSTILE, "name": HOSTILE}]
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            upstream = requests.get(f"{APP_URL}{self.path}", timeout=10)
            self.send_response(upstream.status_code)
            for name, value in upstream.headers.items():
                if name.lower() not in {"content-encoding", "transfer-encoding", "connection"}:
                    self.send_header(name, value)
            self.end_headers()
            self.wfile.write(upstream.content)

        def log_message(self, format, *args):
            return

    server = http.server.ThreadingHTTPServer((PROXY_HOST, 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{PROXY_HOST}:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_r3_hostile_provider_text_renders_as_literal_dom_text(public_demo):
    """The initial public route-catalogue flow must not parse provider text as HTML."""
    chrome = shutil.which("chrome") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not shutil.which("chrome") and not os.path.exists(chrome):
        pytest.skip("No executable browser is available for the required R3 DOM check")

    with hostile_routes_proxy() as proxy_url:
        result = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--no-first-run",
                "--no-sandbox",
                "--disable-gpu-sandbox",
                "--disable-gpu-watchdog",
                "--use-gl=swiftshader",
                "--use-angle=swiftshader",
                "--disable-features=Vulkan",
                "--dump-dom",
                "--virtual-time-budget=3000",
                f"{proxy_url}/",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    if result.returncode != 0:
        pytest.skip(
            "A DOM-capable browser is installed but cannot start in this sandbox; "
            "R3 browser verification remains blocked."
        )
    assert "provider-payload" in result.stdout
    assert '<img id="provider-payload"' not in result.stdout
    assert "&lt;img id=\"provider-payload\"" in result.stdout
    assert 'data-provider-xss="executed"' not in result.stdout


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8000", "http://localhost:8000"])
def test_r3_cors_allows_only_documented_local_origins_without_credentials(public_demo, origin):
    response = requests.options(
        f"{APP_URL}/api/routes",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        timeout=10,
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") is None


def test_r3_cors_denies_unlisted_origin(public_demo):
    response = requests.options(
        f"{APP_URL}/api/routes",
        headers={"Origin": "https://unlisted.example", "Access-Control-Request-Method": "GET"},
        timeout=10,
    )

    assert response.status_code >= 400
    assert response.headers.get("access-control-allow-origin") is None
    assert response.headers.get("access-control-allow-credentials") is None
