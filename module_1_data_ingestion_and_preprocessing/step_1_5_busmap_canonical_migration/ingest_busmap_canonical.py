"""
Step 1.5: Ingest BusMap Native Spatial Master (Routes, Shapes, Stations).
Populates:
- canonical_route_master
- canonical_shape_master
- canonical_station_master
From hanoi_bus_data/
"""

import json
import sqlite3
import math
import sys
import os
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
from config.system_config import DEFAULT_DB_PATH, METERS_PER_DEG_LON_EQUATOR, METERS_PER_DEG_LAT

DB_PATH = BASE_DIR / DEFAULT_DB_PATH
DATA_DIR = BASE_DIR / "data" / "ground_truth" / "busmap_canonical"
if not DATA_DIR.exists():
    DATA_DIR = BASE_DIR / "hanoi_bus_data"

ROUTES_GEOJSON = DATA_DIR / "hanoi_bus_routes.geojson"
STATIONS_GEOJSON = DATA_DIR / "hanoi_bus_stations.geojson"
ROUTEINFO_JSON = DATA_DIR / "hn.routeinfo.json"
ROUTES_JSON = DATA_DIR / "hn.routes.json"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def project_station_to_shape(
    lat: float, lon: float,
    poly: List[Tuple[float, float, float]],
    min_s: float = 0.0,
    prev_lat: Optional[float] = None,
    prev_lon: Optional[float] = None
) -> Tuple[float, float]:
    """
    Project station point onto polyline [lat, lon, cum_distance_m] with progressive forward search corridor.
    Enforces non-decreasing 1D station progress (s_k >= s_{k-1} + 15m) and prevents jumping to return loops.
    """
    if not poly:
        return 0.0, 999999.0

    min_d = 999999.0
    best_s = min_s
    tolerance = 40.0
    lower_s = max(0.0, min_s - tolerance)

    flight_dist = haversine_m(prev_lat, prev_lon, lat, lon) if (prev_lat is not None and prev_lon is not None) else 1000.0
    upper_s = min_s + max(4000.0, 3.0 * flight_dist)

    # First pass: exact orthogonal vector projection within progressive forward corridor [lower_s, upper_s]
    mean_lat = sum(p[0] for p in poly) / len(poly)
    kx = METERS_PER_DEG_LON_EQUATOR * math.cos(math.radians(mean_lat))
    ky = METERS_PER_DEG_LAT
    px = lon * kx
    py = lat * ky

    for i in range(len(poly) - 1):
        p1 = poly[i]
        p2 = poly[i + 1]

        if max(p1[2], p2[2]) < lower_s or min(p1[2], p2[2]) > upper_s:
            continue

        x1_m, y1_m = p1[1] * kx, p1[0] * ky
        x2_m, y2_m = p2[1] * kx, p2[0] * ky
        dx = x2_m - x1_m
        dy = y2_m - y1_m
        seg_len_sq = dx * dx + dy * dy

        if seg_len_sq < 1e-6:
            d1 = math.hypot(px - x1_m, py - y1_m)
            if d1 < min_d and p1[2] >= lower_s:
                min_d = d1
                best_s = p1[2]
            continue

        t = max(0.0, min(1.0, ((px - x1_m) * dx + (py - y1_m) * dy) / seg_len_sq))
        d_proj = math.hypot(px - (x1_m + t * dx), py - (y1_m + t * dy))
        s_proj = p1[2] + t * (p2[2] - p1[2])

        if s_proj >= lower_s and d_proj < min_d:
            min_d = d_proj
            best_s = s_proj

    # Second pass: if no good snap found within corridor (d > 200m), search without upper_s
    if min_d > 200.0:
        for i in range(len(poly) - 1):
            p1 = poly[i]
            p2 = poly[i + 1]
            if max(p1[2], p2[2]) < lower_s:
                continue
            x1_m, y1_m = p1[1] * kx, p1[0] * ky
            x2_m, y2_m = p2[1] * kx, p2[0] * ky
            dx = x2_m - x1_m
            dy = y2_m - y1_m
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq < 1e-6:
                continue
            t = max(0.0, min(1.0, ((px - x1_m) * dx + (py - y1_m) * dy) / seg_len_sq))
            d_proj = math.hypot(px - (x1_m + t * dx), py - (y1_m + t * dy))
            s_proj = p1[2] + t * (p2[2] - p1[2])
            if s_proj >= lower_s and d_proj < min_d:
                min_d = d_proj
                best_s = s_proj

    best_s = max(min_s + 15.0, best_s)
    return round(best_s, 1), round(min_d, 1)


def init_canonical_schema(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS canonical_route_master (
        route_id INTEGER PRIMARY KEY,
        route_code TEXT NOT NULL,
        route_name TEXT NOT NULL,
        company_name TEXT,
        operation_time TEXT,
        headway TEXT,
        total_trips INTEGER,
        point_count_go INTEGER,
        point_count_re INTEGER,
        station_count_go INTEGER,
        station_count_re INTEGER
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_code ON canonical_route_master(route_code);")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS canonical_shape_master (
        route_id INTEGER NOT NULL,
        route_code TEXT NOT NULL,
        direction TEXT NOT NULL,
        point_order INTEGER NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        cum_distance_m REAL NOT NULL,
        PRIMARY KEY (route_id, direction, point_order)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_csm_route_dir ON canonical_shape_master(route_id, direction);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_csm_code_dir ON canonical_shape_master(route_code, direction);")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS canonical_station_master (
        station_id INTEGER NOT NULL,
        route_id INTEGER NOT NULL,
        route_code TEXT NOT NULL,
        direction TEXT NOT NULL,
        station_order INTEGER NOT NULL,
        station_name TEXT NOT NULL,
        address TEXT,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        cum_distance_m REAL NOT NULL,
        snap_dist_m REAL NOT NULL,
        PRIMARY KEY (route_id, direction, station_order)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cstat_route_dir ON canonical_station_master(route_id, direction);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cstat_code_dir ON canonical_station_master(route_code, direction);")

    conn.commit()


def ingest_routes_and_shapes(conn: sqlite3.Connection) -> Dict[Tuple[int, str], List[Tuple[float, float, float]]]:
    """Ingest routes metadata and shapes with cumulative distance."""
    cur = conn.cursor()

    # Load metadata
    routeinfo_map = {}
    if ROUTEINFO_JSON.exists():
        with open(ROUTEINFO_JSON, "r", encoding="utf-8") as f:
            for item in json.load(f):
                routeinfo_map[item["RouteId"]] = item

    print(f"Loading {ROUTES_GEOJSON}...")
    with open(ROUTES_GEOJSON, "r", encoding="utf-8") as f:
        routes_geojson = json.load(f)

    cur.execute("DELETE FROM canonical_shape_master;")
    cur.execute("DELETE FROM canonical_route_master;")

    shapes_cache = {}
    shape_records = []
    routes_records = {}

    for feat in routes_geojson.get("features", []):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])

        r_id = props.get("RouteId")
        r_code = props.get("RouteNo", "").strip().upper()
        r_name = props.get("RouteName", "")
        # Direction: 0 -> "go", 1 -> "re"
        bm_dir = props.get("Direction", 0)
        d_str = "go" if bm_dir == 0 else "re"

        if not r_id or not coords:
            continue

        # Correctly pair polylines for loop routes E11 and E11CT
        # BusMap Direction 0 (248 pts) corresponds to stations Direction 1 ("re")
        # BusMap Direction 1 (235 pts, reversed) corresponds to stations Direction 0 ("go")
        if r_code in ("E11", "E11CT"):
            if bm_dir == 1:
                d_str = "go"
                coords = list(reversed(coords))
            else:
                d_str = "re"

        # Route 123 go: BusMap Direction 0 concatenated an out-and-back loop (65km).
        # Replace 123 go with the clean reverse of direction 1 (re, 23.7km, 250 pts).
        if r_code == "123" and bm_dir == 0:
            # Find coords of 123 direction 1
            for feat2 in routes_geojson.get("features", []):
                p2 = feat2.get("properties", {})
                if p2.get("RouteNo", "").strip().upper() == "123" and p2.get("Direction") == 1:
                    coords = list(reversed(feat2.get("geometry", {}).get("coordinates", [])))
                    break

        # Compute cumulative distance
        cum_dist = 0.0
        poly_with_s = []

        for idx, pt in enumerate(coords):
            lon, lat = pt[0], pt[1]
            if idx > 0:
                prev_lat, prev_lon = poly_with_s[-1][0], poly_with_s[-1][1]
                cum_dist += haversine_m(prev_lat, prev_lon, lat, lon)

            poly_with_s.append((lat, lon, round(cum_dist, 1)))
            shape_records.append((
                r_id, r_code, d_str, idx, lat, lon, round(cum_dist, 1)
            ))

        shapes_cache[(r_id, d_str)] = poly_with_s

        # Route master record
        if r_id not in routes_records:
            info = routeinfo_map.get(r_id, {})
            routes_records[r_id] = {
                "route_id": r_id,
                "route_code": r_code,
                "route_name": r_name,
                "company_name": info.get("CompanyName") or props.get("CompanyName", ""),
                "operation_time": info.get("OperationTime") or props.get("OperationTime", ""),
                "headway": info.get("Headway") or props.get("Headway", ""),
                "total_trips": info.get("TotalTrip") or props.get("TotalTrip"),
                "point_count_go": 0,
                "point_count_re": 0,
                "station_count_go": 0,
                "station_count_re": 0
            }

        if d_str == "go":
            routes_records[r_id]["point_count_go"] = len(coords)
            routes_records[r_id]["station_count_go"] = props.get("StationCount", 0)
        else:
            routes_records[r_id]["point_count_re"] = len(coords)
            routes_records[r_id]["station_count_re"] = props.get("StationCount", 0)

    # Insert shapes
    cur.executemany("""
    INSERT INTO canonical_shape_master (
        route_id, route_code, direction, point_order, lat, lon, cum_distance_m
    ) VALUES (?, ?, ?, ?, ?, ?, ?);
    """, shape_records)

    # Insert routes
    cur.executemany("""
    INSERT INTO canonical_route_master (
        route_id, route_code, route_name, company_name, operation_time, headway,
        total_trips, point_count_go, point_count_re, station_count_go, station_count_re
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, [(
        r["route_id"], r["route_code"], r["route_name"], r["company_name"],
        r["operation_time"], r["headway"], r["total_trips"],
        r["point_count_go"], r["point_count_re"],
        r["station_count_go"], r["station_count_re"]
    ) for r in routes_records.values()])

    conn.commit()
    print(f"Ingested {len(routes_records)} canonical routes and {len(shape_records):,} shape points.")
    return shapes_cache


def ingest_stations(conn: sqlite3.Connection, shapes_cache: Dict[Tuple[int, str], List[Tuple[float, float, float]]]):
    """Ingest stations and project them onto canonical shape polylines."""
    cur = conn.cursor()

    print(f"Loading {STATIONS_GEOJSON}...")
    with open(STATIONS_GEOJSON, "r", encoding="utf-8") as f:
        stations_geojson = json.load(f)

    cur.execute("DELETE FROM canonical_station_master;")

    # Fetch route codes mapping
    cur.execute("SELECT route_id, route_code FROM canonical_route_master;")
    route_codes = dict(cur.fetchall())

    station_records = []
    snap_distances = []

    # Group stations by (route_id, direction) to project strictly monotonically
    stations_by_route_dir = {}

    for feat in stations_geojson.get("features", []):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])

        if not coords or len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        st_id = props.get("StationId")
        r_id = props.get("RouteId")
        st_order = props.get("StationOrder", 0)
        st_name = props.get("StationName", "")
        address = props.get("Address", "")
        bm_dir = props.get("StationDirection", 0)
        d_str = "go" if bm_dir == 0 else "re"
        r_code = route_codes.get(r_id, f"R_{r_id}")

        stations_by_route_dir.setdefault((r_id, d_str), []).append({
            "st_id": st_id, "r_id": r_id, "r_code": r_code, "d_str": d_str,
            "st_order": st_order, "st_name": st_name, "address": address,
            "lat": lat, "lon": lon
        })

    for (r_id, d_str), st_list in stations_by_route_dir.items():
        st_list.sort(key=lambda x: x["st_order"])
        poly = shapes_cache.get((r_id, d_str), [])

        curr_s = 0.0
        prev_lat, prev_lon = None, None
        for idx, item in enumerate(st_list):
            if idx == 0:
                s_station = 0.0
                d_snap = haversine_m(item["lat"], item["lon"], poly[0][0], poly[0][1]) if poly else 0.0
            else:
                s_station, d_snap = project_station_to_shape(
                    item["lat"], item["lon"], poly, min_s=curr_s,
                    prev_lat=prev_lat, prev_lon=prev_lon
                )

            curr_s = s_station
            prev_lat, prev_lon = item["lat"], item["lon"]
            station_records.append((
                item["st_id"], item["r_id"], item["r_code"], item["d_str"],
                item["st_order"], item["st_name"], item["address"],
                item["lat"], item["lon"], s_station, d_snap
            ))
            if d_snap < 500:
                snap_distances.append(d_snap)

    cur.executemany("""
    INSERT INTO canonical_station_master (
        station_id, route_id, route_code, direction, station_order, station_name,
        address, lat, lon, cum_distance_m, snap_dist_m
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, station_records)

    conn.commit()

    snap_distances.sort()
    med_snap = snap_distances[len(snap_distances) // 2] if snap_distances else 0
    p90_snap = snap_distances[int(len(snap_distances) * 0.9)] if snap_distances else 0

    print(f"Ingested {len(station_records):,} canonical stations.")
    print(f"Station Snap-to-Route Metrics: Median = {med_snap:.1f}m, P90 = {p90_snap:.1f}m")


def main():
    print("=" * 80)
    print("INGESTING BUSMAP NATIVE CANONICAL GROUND TRUTH")
    print("=" * 80)
    t0 = time.time()

    conn = sqlite3.connect(DB_PATH)
    init_canonical_schema(conn)

    shapes_cache = ingest_routes_and_shapes(conn)
    ingest_stations(conn, shapes_cache)

    conn.close()
    print(f"Completed in {time.time() - t0:.2f}s.")
    print("=" * 80)


if __name__ == "__main__":
    main()

