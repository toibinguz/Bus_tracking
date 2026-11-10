"""Public JSON input/output runner for the SPEC-26 projection contract."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary import (
    ProjectableEvent,
    project_route_events,
)


def main(input_path: str, output_path: str) -> None:
    fixture = json.loads(Path(input_path).read_text(encoding="utf-8"))
    events = [ProjectableEvent(**event) for event in fixture["events"]]
    station_lookup = {
        (int(item["route_id"]), int(item["station_id"])): item["direction"]
        for item in fixture.get("station_direction_lookup", [])
    }
    accepted, diagnostics = project_route_events(
        events,
        fixture["shape_by_direction"],
        station_lookup,
    )
    Path(output_path).write_text(
        json.dumps(
            {"accepted": [asdict(event) for event in accepted], "diagnostics": diagnostics},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: project_frenet_fixture.py INPUT.json OUTPUT.json")
    main(sys.argv[1], sys.argv[2])
