import json
from pathlib import Path

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.p2_transform import (
    p2_job_key,
    project_distinct_envelopes,
    validate_envelope,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "hdfs_p2"


def test_p2_fixture_has_one_duplicate_and_accepted_spec26_projection():
    values = json.loads((FIXTURE_ROOT / "p2_replayed_observed.json").read_text(encoding="utf-8"))
    reference = json.loads((FIXTURE_ROOT / "reference_bundle.json").read_text(encoding="utf-8"))
    manifest = json.loads((FIXTURE_ROOT / "p2_fixture_manifest.json").read_text(encoding="utf-8"))

    rows, diagnostics = project_distinct_envelopes([validate_envelope(value) for value in values], reference)

    assert len(values) == manifest["raw_row_count"]
    assert len({value["event_id"] for value in values}) == manifest["distinct_event_count"]
    assert sum(value["event_id"] == manifest["duplicate_event_id"] for value in values) == 2
    assert diagnostics == {}
    assert len(rows) == manifest["accepted_row_count"]
    assert [
        {field: row[field] for field in expected}
        for expected, row in zip(manifest["expected_projection"], rows, strict=True)
    ] == manifest["expected_projection"]


def test_p2_job_key_is_stable_and_changes_with_input_hash():
    arguments = {
        "bronze_path": "hdfs://namenode:8020/bus-eta/v1/bronze/fixture.jsonl",
        "bronze_sha256": "a" * 64,
        "source_window_id": "fixture-window",
        "reference_sha256": "b" * 64,
        "source_revision_sha256": "c" * 64,
    }
    assert p2_job_key(**arguments) == p2_job_key(**arguments)
    assert p2_job_key(**arguments) != p2_job_key(**{**arguments, "bronze_sha256": "d" * 64})
