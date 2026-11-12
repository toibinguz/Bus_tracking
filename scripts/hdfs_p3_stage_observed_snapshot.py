"""Export a bounded observed snapshot and station reference for HDFS P3A."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(database, output_dir, route_code, train_date, test_date):
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    pings = conn.execute(
        """select route_code,route_id,vehicle_id,device_update_time,device_epoch,direction,
                  s_bus_m,cross_track_m,derived_speed_kmh
             from route_projected_telemetry
             where route_code=? and substr(device_update_time,1,10) in (?,?)
             order by direction,vehicle_id,device_epoch""",
        (route_code, train_date, test_date),
    ).fetchall()
    if not pings:
        raise SystemExit("no observed pings for requested route/dates")
    if train_date >= test_date or {p['device_update_time'][:10] for p in pings} != {train_date, test_date}:
        raise SystemExit('both dates must have observed data and train_date < test_date')
    route_id = pings[0]["route_id"]
    stations = conn.execute(
        """select route_code,direction,station_order,station_id,station_name,cum_distance_m
             from canonical_station_master where route_code=? order by direction,station_order""",
        (route_code,),
    ).fetchall()
    shapes = dict(conn.execute('select direction,max(cum_distance_m) from canonical_shape_master where route_code=? group by direction', (route_code,)).fetchall())
    conn.close()
    ping_path, station_path = target / "observed_projected.jsonl", target / "stations.json"
    ping_path.write_text("".join(json.dumps(dict(row), separators=(",", ":")) + "\n" for row in pings), encoding="utf-8")
    station_path.write_text(json.dumps([dict(row) for row in stations], separators=(",", ":")), encoding="utf-8")
    manifest = {"provenance":"observed", "route_code":route_code, "route_id":route_id,
                "train_date":train_date, "test_date":test_date, "ping_count":len(pings),
                "observed_sha256":digest(ping_path), "stations_sha256":digest(station_path),
                "shape_lengths_m":shapes, "source_database":str(Path(database).resolve()),
                "selection":{"table":"route_projected_telemetry", "route_code":route_code, "dates":[train_date,test_date]}}
    manifest['source_window_id'] = 'observed-snapshot-' + manifest['observed_sha256']
    (target / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
