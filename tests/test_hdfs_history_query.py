from datetime import date
import pytest
from http.server import HTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

from scripts.hdfs_history_server import handler_for

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_query import validate_request
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_query import validate_snapshot_id


@pytest.mark.parametrize('snapshot_id',[None,'latest','../_runs','a'*63,'g'*64])
def test_snapshot_identity_must_be_explicit_hash(snapshot_id):
    with pytest.raises(ValueError):
        validate_snapshot_id(snapshot_id)


def test_valid_inclusive_month():
    assert validate_request("08A", "2026-11-01", "2026-12-01") == (date(2026, 11, 1), date(2026, 12, 1))


@pytest.mark.parametrize("route,start,end", [
    ("08A'; DROP", "2026-11-01", "2026-11-02"),
    ("08A", "2026-11-01", "2026-12-02"),
    ("08A", "2026-11-02", "2026-11-01"),
    ("08A", "not-a-date", "2026-11-01"),
])
def test_invalid_requests(route, start, end):
    with pytest.raises(ValueError):
        validate_request(route, start, end)


def test_http_validation_and_unavailable():
    server = HTTPServer(("127.0.0.1", 0), handler_for(object()))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/api/history/route-speed"
    try:
        with pytest.raises(HTTPError) as invalid:
            urlopen(base + "?route_code=08A&date_from=2026-10-01", timeout=5)
        assert invalid.value.code == 400
        with pytest.raises(HTTPError) as invalid_snapshot:
            urlopen(base + '?route_code=08A&date_from=2026-10-01&date_to=2026-10-02&snapshot_id=latest',timeout=5)
        assert invalid_snapshot.value.code == 400
        with patch('scripts.hdfs_history_server.query_snapshot_speed',return_value={'snapshot_id':'a'*64}) as snapshot_query:
            response = urlopen(base + '?route_code=08A&date_from=2026-10-01&date_to=2026-10-02&snapshot_id='+'a'*64,timeout=5)
            assert response.status == 200
            snapshot_query.assert_called_once()
        with patch("scripts.hdfs_history_server.query_route_speed", side_effect=RuntimeError("offline")):
            with pytest.raises(HTTPError) as unavailable:
                urlopen(base + "?route_code=08A&date_from=2026-10-01&date_to=2026-10-02", timeout=5)
        assert unavailable.value.code == 503
        assert b'hdfs_unavailable' in unavailable.value.read()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
