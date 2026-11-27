import json
from pathlib import Path

from modules.lakehouse.hdfs.contract import (
    canonical_event_id,
    envelope_from_sanitized_record,
)

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "hdfs_telemetry_v1.json"


def test_fixed_fixture_produces_stable_event_id_and_schema():
    record = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0]
    envelope = envelope_from_sanitized_record(
        record,
        source_name="busmap",
        source_window_id="observed-2026-11-01T0005Z",
        provenance="observed",
        route_code="01",
        source_record_id=record.get("ping_id"),
    )

    assert envelope.event_id == "0ff9e4055234a38d0432f8d919663c3580d37906c89752961e77d959f8f158b6"
    assert json.loads(envelope.to_json_line())["schema_version"] == "bus-telemetry.v1"
    assert envelope.route_code == "01"


def test_identity_is_not_changed_by_json_key_order():
    stable_id = canonical_event_id(
        source_name="busmap",
        source_record_id=None,
        route_id=1,
        vehicle_id=1101,
        observed_at_epoch_ms=1793491500000,
        lat=21.028511,
        lon=105.804817,
    )
    assert stable_id == canonical_event_id(
        vehicle_id=1101,
        source_name="busmap",
        source_record_id=None,
        route_id=1,
        observed_at_epoch_ms=1793491500000,
        lon=105.804817,
        lat=21.028511,
    )
