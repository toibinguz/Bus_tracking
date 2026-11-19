import copy
import json
from pathlib import Path

from scripts.hdfs_p3b_scale import synthetic_event


def test_deterministic_synthetic_identity_and_preservation():
    sources = json.loads(Path("tests/fixtures/hdfs_p2/p2_replayed_observed.json").read_text())
    original = copy.deepcopy(sources)
    first = synthetic_event(sources[0], 0, 42, "test")
    assert first == synthetic_event(sources[0], 0, 42, "test")
    assert first["provenance"] == "synthetic_scale"
    assert first["event_id"] != sources[0]["event_id"]
    for changed in [synthetic_event(sources[0], 1, 42, "test"), synthetic_event(sources[0], 0, 43, "test"), synthetic_event(sources[0], 0, 42, "other")]:
        assert changed["event_id"] != first["event_id"]
    for key in ("lat", "lon", "observed_at_epoch_ms", "received_at_epoch_ms", "route_code"):
        assert first[key] == sources[0][key]
    second = synthetic_event(sources[1], 0, 42, "test")
    assert second["vehicle_id"] == first["vehicle_id"]
    assert second["observed_at_epoch_ms"]-first["observed_at_epoch_ms"] == sources[1]["observed_at_epoch_ms"]-sources[0]["observed_at_epoch_ms"]
    assert sources == original


def test_tiling_unique_events_does_not_expand_source_duplicates():
    sources = json.loads(Path("tests/fixtures/hdfs_p2/p2_replayed_observed.json").read_text())
    unique = {row["event_id"]: row for row in sources}
    generated = [synthetic_event(row, tile, 42, "bounded") for tile in range(3) for row in unique.values()]
    assert len(sources) == 5 and len(unique) == 4
    assert len({row["event_id"] for row in generated}) == 12
    assert len({row["vehicle_id"] for row in generated}) == 3
    assert {row["provenance"] for row in generated} == {"synthetic_scale"}
