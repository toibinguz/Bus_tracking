import json
from pathlib import Path

import pytest

from scripts.hdfs_ingest_runner import closed_spool_files, upload_closed_spool

from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.hdfs_bronze_adapter import (
    adapt_sanitized_batch,
)
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.contract import (
    canonical_event_id,
)
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.spool import (
    hour_partition,
    load_receipt,
    write_closed_window,
    write_receipt,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hdfs_telemetry_v1.json"


def test_fixed_fixture_produces_stable_event_id_and_schema():
    record = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0]
    envelopes = adapt_sanitized_batch(
        [record],
        source_window_id="observed-2026-11-01T0005Z",
        provenance="observed",
        route_codes={1: "01"},
    )

    assert envelopes[0].event_id == "0ff9e4055234a38d0432f8d919663c3580d37906c89752961e77d959f8f158b6"
    assert json.loads(envelopes[0].to_json_line())["schema_version"] == "bus-telemetry.v1"
    assert envelopes[0].route_code == "01"


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


def test_adapter_rejects_route_outside_canonical_master():
    record = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0]
    with pytest.raises(ValueError, match="canonical_route_master"):
        adapt_sanitized_batch(
            [record],
            source_window_id="window",
            provenance="observed",
            route_codes={},
        )


def test_closed_spool_is_atomic_and_partitioned_in_hanoi_time(tmp_path):
    record = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0]
    envelope = adapt_sanitized_batch(
        [record],
        source_window_id="window",
        provenance="observed",
        route_codes={1: "01"},
    )[0]
    spool_file = write_closed_window([envelope], tmp_path)

    assert spool_file.suffix == ".jsonl"
    assert not list(spool_file.parent.glob("*.tmp"))
    assert "dt=2026-11-01" in str(spool_file)
    assert "hr=07" in str(spool_file)
    assert hour_partition(envelope.observed_at_epoch_ms) == ("2026-11-01", "07")


def test_receipt_is_written_only_as_explicit_upload_acknowledgement(tmp_path):
    spool_file = tmp_path / "ingest-fixture.jsonl"
    spool_file.write_text("{}\n", encoding="utf-8")
    assert load_receipt(spool_file) is None
    write_receipt(spool_file, "/bus-eta/v1/bronze/telemetry/x", "a" * 64)
    assert load_receipt(spool_file)["sha256"] == "a" * 64


def test_private_runner_selects_only_closed_spool_files(tmp_path):
    closed = tmp_path / "dt=2026-11-01" / "hr=07" / "ingest-closed.jsonl"
    closed.parent.mkdir(parents=True)
    closed.write_text("{}\n", encoding="utf-8")
    (closed.parent / "ingest-open.jsonl.tmp").write_text("{}\n", encoding="utf-8")

    uploaded: list[Path] = []

    class Uploader:
        def upload(self, spool_file):
            uploaded.append(Path(spool_file))
            return "/bus-eta/v1/bronze/telemetry/dt=2026-11-01/hr=07/ingest-closed.jsonl"

    assert closed_spool_files(tmp_path) == [closed]
    assert upload_closed_spool(tmp_path, Uploader()) == [
        "/bus-eta/v1/bronze/telemetry/dt=2026-11-01/hr=07/ingest-closed.jsonl"
    ]
    assert uploaded == [closed]


def test_private_runner_keeps_closed_spool_when_upload_is_not_acknowledged(tmp_path):
    closed = tmp_path / "dt=2026-11-01" / "hr=07" / "ingest-retry.jsonl"
    closed.parent.mkdir(parents=True)
    closed.write_text("{}\n", encoding="utf-8")

    class UnavailableUploader:
        def upload(self, spool_file):
            raise ConnectionError("namenode unavailable")

    with pytest.raises(ConnectionError, match="namenode unavailable"):
        upload_closed_spool(tmp_path, UnavailableUploader())

    assert closed.exists()
    assert load_receipt(closed) is None
