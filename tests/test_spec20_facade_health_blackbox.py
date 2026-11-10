"""Black-box acceptance checks for SPEC-20.

These tests use only the public ASGI application and HTTP/OpenAPI contracts.
They deliberately make no assertions about module internals or imports.
"""

from __future__ import annotations

import importlib
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


APP_MODULE = "module_3_bus_eta_prediction.step_3_5_web_demo.app"
EXPECTED_HEALTH = {
    "status": "healthy",
    "healthy": True,
    "provider": "busmap",
    "mode": "busmap_discrete_only",
    "upstream": "https://api.busmap.city/v2/public/busmap/route_bus_gps",
}
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client() -> TestClient:
    """F-01: importing the documented ASGI app must be sufficient to start it."""
    app = importlib.import_module(APP_MODULE).app
    with TestClient(app) as test_client:
        yield test_client


def test_f01_app_import_and_startup(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200


def test_f02_f03_health_contract_is_identical_on_both_paths(client: TestClient) -> None:
    legacy = client.get("/api/health")
    versioned = client.get("/api/v1/health")

    assert legacy.status_code == 200
    assert versioned.status_code == 200
    assert legacy.json() == EXPECTED_HEALTH
    assert versioned.json() == legacy.json()


def test_f04_declared_http_surface_exposes_existing_busmap_routes(client: TestClient) -> None:
    """Exercise public route discovery and stable valid/invalid route semantics.

    The exact catalog contents are data-dependent, so a route obtained from the
    public catalog is used for subsequent requests.  No test fixture accesses
    the database or service object.
    """
    openapi = client.get("/openapi.json").json()
    paths = openapi["paths"]
    expected_paths = {
        "/api/routes",
        "/api/live-vehicles",
        "/api/route-shape",
        "/api/route-stations",
        "/api/station-eta",
    }
    assert expected_paths <= set(paths)

    routes_response = client.get("/api/routes")
    assert routes_response.status_code == 200
    routes = routes_response.json()
    assert isinstance(routes, list) and routes
    route = routes[0]
    assert {"route_id", "route_no", "name"} <= set(route)

    route_code = route["route_no"]
    valid_common = {"route": route_code, "direction": 0}
    shape = client.get("/api/route-shape", params=valid_common)
    stations = client.get("/api/route-stations", params=valid_common)
    live = client.get("/api/live-vehicles", params=valid_common)
    for response in (shape, stations, live):
        assert response.status_code == 200, response.text

    assert {"route_id", "route_code", "direction"} <= set(shape.json())
    station_payload = stations.json()
    assert {"route_id", "route_code", "direction", "stations"} <= set(station_payload)
    assert {"route_id", "direction", "count", "timestamp", "vehicles"} <= set(live.json())

    invalid_route = client.get("/api/route-shape", params={"route": "__no_such_route__", "direction": 0})
    assert invalid_route.status_code in {400, 404}

    stations_list = station_payload["stations"]
    if stations_list:
        order = stations_list[0]["station_order"]
        eta = client.get("/api/station-eta", params={**valid_common, "station_order": order})
        assert eta.status_code == 200, eta.text
        assert {"route_id", "route_code", "direction", "target_station", "approaching_count", "buses"} <= set(eta.json())


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def test_f05_launcher_accepts_existing_server_health() -> None:
    """Run the public launcher while a compatible server is already on port 8000."""
    if _port_is_open(8000):
        pytest.skip("port 8000 is already in use; launcher must be tested in an isolated run")

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            f"{APP_MODULE}:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if _port_is_open(8000):
                break
            time.sleep(0.2)
        else:
            pytest.fail("server did not start within 30 seconds")

        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "run_demo.ps1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
