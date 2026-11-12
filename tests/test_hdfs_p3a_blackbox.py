"""External HTTP contract checks; run against the live HDFS history service.

Run explicitly with HDFS_P3A_LIVE=1; no implementation imports or mocks.
"""

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("HDFS_P3A_LIVE") != "1", reason="requires live Docker HDFS history API"
)
BASE = os.environ.get("HDFS_P3A_URL", "http://127.0.0.1:8090")
ENDPOINT = "/api/history/route-speed"


def request(query, path=ENDPOINT):
    try:
        response = urlopen(BASE + path + "?" + query, timeout=45)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


@pytest.mark.parametrize("parameters", [
    [("route_code", "08A"), ("date_from", "2026-10-08")],
    [("route_code", "08A"), ("route_code", "27"), ("date_from", "2026-10-08"), ("date_to", "2026-10-08")],
    [("route_code", "08A'; DROP"), ("date_from", "2026-10-08"), ("date_to", "2026-10-08")],
    [("route_code", "08A"), ("date_from", "2026-10-09"), ("date_to", "2026-10-08")],
    [("route_code", "08A"), ("date_from", "2026-10-01"), ("date_to", "2026-11-01")],
    [("route_code", "08A"), ("date_from", "2026-02-30"), ("date_to", "2026-03-01")],
    [("route_code", ""), ("date_from", "2026-10-08"), ("date_to", "2026-10-08")],
    [("route_code", "08A"), ("date_from", "2026-10-08"), ("date_to", "2026-10-08"), ("sql", "select 1")],
])
def test_invalid_contract(parameters):
    status, payload = request(urlencode(parameters))
    assert status == 400, payload
    assert "error" in payload


def test_published_fixture_aggregate():
    status, payload = request(urlencode({
        "route_code": "08A", "date_from": "2026-10-08", "date_to": "2026-10-08",
    }))
    assert status == 200, payload
    assert payload["storage"] == "hdfs-silver"
    assert payload["route_code"] == "08A"
    assert payload["rows"] == [{"dt": "2026-10-08", "ping_count": 4, "avg_speed_kmh": pytest.approx(16.53)}]
    assert payload["generated_at"]


def test_missing_route_has_empty_rows():
    status, payload = request(urlencode({
        "route_code": "NO_SUCH_ROUTE", "date_from": "2026-10-08", "date_to": "2026-10-08",
    }))
    assert status == 200, payload
    assert payload["rows"] == []
    assert payload["storage"] == "hdfs-silver"


def test_unknown_endpoint():
    status, payload = request("", path="/api/history/not-an-endpoint")
    assert status == 404, payload
