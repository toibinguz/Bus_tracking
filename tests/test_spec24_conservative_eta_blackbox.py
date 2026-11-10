"""Public-contract acceptance checks for SPEC-24.

These checks intentionally use only the documented ASGI application and its
HTTP/OpenAPI surface.  They do not import ETA-policy, model, or UI modules.
"""

from __future__ import annotations

import importlib
import math

import pytest
from fastapi.testclient import TestClient


APP_MODULE = "module_3_bus_eta_prediction.step_3_5_web_demo.app"
PREDICTION_SOURCES = {"ml_calibrated", "baseline_fallback"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = importlib.import_module(APP_MODULE).app
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def public_eta_response(client: TestClient) -> dict:
    """Obtain one ETA response entirely through the public route catalogue."""
    routes = client.get("/api/routes")
    assert routes.status_code == 200, routes.text
    assert routes.json(), "public route catalogue is unexpectedly empty"

    route = routes.json()[0]
    stations = client.get(
        "/api/route-stations", params={"route": route["route_no"], "direction": 0}
    )
    assert stations.status_code == 200, stations.text
    assert stations.json()["stations"], "public route has no stations"

    response = client.get(
        "/api/station-eta",
        params={
            "route": route["route_no"],
            "direction": 0,
            "station_order": stations.json()["stations"][0]["station_order"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_spec24_openapi_removes_arriving_now_and_eta_bus_status(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()
    bus_schema = openapi["components"]["schemas"]["ApproachingBusDTO"]

    assert "status" not in bus_schema["properties"]
    assert "ARRIVING_NOW" not in str(openapi)


def test_spec24_openapi_exposes_conservative_debug_contract_and_sources(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    bus = schemas["ApproachingBusDTO"]["properties"]
    safe_window = schemas["SafeWindowDTO"]["properties"]

    assert {"prediction_source", "safe_window", "display_eta_minutes", "display_text"} <= set(bus)
    assert {"p10_seconds", "p50_seconds", "p90_seconds", "buffer_seconds", "conservative_eta_seconds"} <= set(safe_window)
    assert PREDICTION_SOURCES <= set(bus["prediction_source"].get("enum", ()))


def test_spec24_every_public_approaching_bus_obeys_conservative_math(
    public_eta_response: dict,
) -> None:
    assert public_eta_response["approaching_count"] == len(public_eta_response["buses"])
    for bus in public_eta_response["buses"]:
        window = bus["safe_window"]
        t50 = window["p50_seconds"]
        buffer_seconds = window["buffer_seconds"]
        conservative_seconds = window["conservative_eta_seconds"]

        assert "status" not in bus
        assert bus["prediction_source"] in PREDICTION_SOURCES
        assert buffer_seconds >= 0
        assert conservative_seconds >= t50
        assert bus["eta_seconds"] == pytest.approx(conservative_seconds)
        assert bus["display_eta_minutes"] == math.ceil(conservative_seconds / 60)
        assert window["display_eta_minutes"] == bus["display_eta_minutes"]
        expected_text = "~1 phút" if bus["display_eta_minutes"] == 1 else f"{bus['display_eta_minutes']} phút"
        assert bus["display_text"] == expected_text


def test_spec24_empty_eta_response_is_truthful_not_a_fabricated_headway(
    public_eta_response: dict,
) -> None:
    if public_eta_response["buses"]:
        pytest.skip("this public query has approaching buses; it is not an empty-state case")

    message = public_eta_response["message"].strip()
    assert message
    assert "10-15" not in message
    assert "10–15" not in message
    assert "~10" not in message


def test_spec24_passenger_debug_are_client_presentation_not_api_modes(client: TestClient) -> None:
    """The HTTP contract supplies one forecast; a UI mode cannot alter it."""
    operation = client.get("/openapi.json").json()["paths"]["/api/station-eta"]["get"]
    parameter_names = {parameter["name"] for parameter in operation["parameters"]}
    assert "mode" not in parameter_names

    page = client.get("/")
    assert page.status_code == 200
    assert "Passenger" in page.text
    assert "Debug" in page.text

