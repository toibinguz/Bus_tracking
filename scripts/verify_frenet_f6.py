"""Public exact parity check for the frozen SPEC-26 F6 SQLite slice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import worker_project_route


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def main(manifest_path: str, database_path: str) -> None:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    with sqlite3.connect(database_path) as connection:
        placeholders = ",".join("?" for _ in manifest["legacy_ping_ids"])
        source = connection.execute(
            "SELECT v.ping_id,v.vehicle_id,v.plate,v.route_id,v.device_update_time,v.device_epoch,"
            "v.direction,v.lat,v.lon,v.current_station_id,r.route_code,r.s_bus_m,r.cross_track_m,"
            "r.derived_speed_kmh,r.direction FROM vehicle_unique_pings v JOIN route_projected_telemetry r "
            "ON r.ping_id=v.ping_id WHERE v.ping_id IN (" + placeholders + ") ORDER BY r.device_epoch",
            manifest["legacy_ping_ids"],
        ).fetchall()
        shapes = {"go": [], "re": []}
        for _, direction, order, lat, lon, distance in connection.execute(
            "SELECT route_id,direction,point_order,lat,lon,cum_distance_m FROM canonical_shape_master "
            "WHERE route_id=? ORDER BY direction,point_order", (manifest["source_route_id"],)
        ):
            shapes[direction].append((order, lat, lon, distance))
        station_lookup = {(route_id, station_id): direction for route_id, station_id, direction in connection.execute(
            "SELECT route_id,station_id,MIN(direction) FROM canonical_station_master GROUP BY route_id,station_id "
            "HAVING COUNT(DISTINCT direction)=1"
        )}
    if digest(source) != manifest["source_slice_sha256"]:
        raise AssertionError("F6 source slice fingerprint changed")
    master_rows = [(manifest["source_route_id"], direction, *point) for direction, points in shapes.items() for point in points]
    if digest(master_rows) != manifest["canonical_master_sha256"]:
        raise AssertionError("F6 canonical master fingerprint changed")
    _, _, _, actual, _ = worker_project_route((database_path, manifest["source_route_id"], manifest["source_route_code"], shapes, station_lookup))
    selected = [list(row) for row in actual if row[0] in set(manifest["legacy_ping_ids"])]
    if selected != manifest["expected_rows"]:
        raise AssertionError("F6 SQLite adapter output differs from frozen legacy rows")
    print(json.dumps({"fixture": "F6", "rows": len(selected), "status": "pass"}))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_frenet_f6.py MANIFEST.json DATABASE.sqlite")
    main(sys.argv[1], sys.argv[2])
