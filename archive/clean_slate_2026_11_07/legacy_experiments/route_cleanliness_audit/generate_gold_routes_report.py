"""
Interactive HTML Visualizer & Validation Suite for Canonical BusMap Master Routes.
Generates reports/gold_routes_audit_report.html with multi-layer overlays:
- Canonical Centerlines (go & re)
- OpenStreetMap Ground Truth Polyline Overlay (amber dashed)
- Canonical Stations with click-to-fly
- High-Density Operational Telemetry Pings with Snap-to-Route perpendicular vectors
- Vehicle Fleet filters & KPI cards
"""

import json
import sqlite3
import math
import os
import sys
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = Path("data/hanoi_bus_system.db")
OSM_PATH = Path("archive/legacy_dumps/osm/raw/hanoi_all_bus_routes_raw.json")
OUTPUT_HTML = Path("reports/gold_routes_audit_report.html")

CANONICAL_AUDITED_ROUTES = [
    "22A", "02", "27", "99", "38", "123", "122", "BRT01", "E05", "26", "11", "05", "19",
    "56B", "146", "37", "01", "34", "92", "08A", "E06", "17", "64", "E04"
]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def min_dist_point_to_polyline(lat: float, lon: float, poly: list) -> float:
    if not poly:
        return 999999.0
    min_d = 999999.0
    step = max(1, len(poly) // 40)
    best_idx = 0
    for i in range(0, len(poly), step):
        d = haversine_m(lat, lon, poly[i][0], poly[i][1])
        if d < min_d:
            min_d = d
            best_idx = i

    start_i = max(0, best_idx - step * 2)
    end_i = min(len(poly) - 1, best_idx + step * 2)
    for i in range(start_i, end_i):
        p1 = poly[i]
        p2 = poly[i + 1]
        d1 = haversine_m(lat, lon, p1[0], p1[1])
        d2 = haversine_m(lat, lon, p2[0], p2[1])
        dmid = haversine_m(lat, lon, (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        min_d = min(min_d, d1, d2, dmid)
    return min_d


def load_osm_routes():
    if not OSM_PATH.exists():
        return {}
    with open(OSM_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes = {el["id"]: (el["lat"], el["lon"]) for el in data["elements"] if el["type"] == "node"}
    ways = {el["id"]: el.get("nodes", []) for el in data["elements"] if el["type"] == "way"}

    osm_routes = {}
    for el in data["elements"]:
        if el["type"] == "relation":
            tags = el.get("tags", {})
            ref = tags.get("ref", "").strip().upper()
            if not ref:
                continue
            poly = []
            for m in el.get("members", []):
                if m.get("type") == "way" and m.get("ref") in ways:
                    for nid in ways[m["ref"]]:
                        if nid in nodes:
                            poly.append(nodes[nid])
            if poly:
                if ref not in osm_routes:
                    osm_routes[ref] = []
                osm_routes[ref].append({
                    "id": el["id"],
                    "name": tags.get("name", ""),
                    "polyline": poly
                })
    return osm_routes


def sample_evenly(lst: list, max_n: int) -> list:
    if len(lst) <= max_n:
        return lst
    step = len(lst) / max_n
    return [lst[int(i * step)] for i in range(max_n)]


def find_nearest_centerline_point(lat: float, lon: float, centerline: list):
    min_d = 999999.0
    best_pt = [lat, lon]
    for pt in centerline:
        d = haversine_m(lat, lon, pt[0], pt[1])
        if d < min_d:
            min_d = d
            best_pt = [pt[0], pt[1]]
    return best_pt


def build_gold_routes_data(conn: sqlite3.Connection, osm_routes: dict) -> dict:
    cur = conn.cursor()
    
    cur.execute("SELECT route_code, route_name FROM canonical_route_master")
    route_names = dict(cur.fetchall())

    data_by_route_dir = {}
    routes_summary = []

    print(f"Processing {len(CANONICAL_AUDITED_ROUTES)} Canonical Audited Routes...")

    for r_idx, r_code in enumerate(CANONICAL_AUDITED_ROUTES, 1):
        r_name = route_names.get(r_code, f"Tuyến {r_code}")
        print(f"[{r_idx:02d}/{len(CANONICAL_AUDITED_ROUTES)}] Processing Route {r_code:<6} ({r_name})...")

        for d_str in ["go", "re"]:
            key = f"{r_code}_{d_str}"
            d_label = "Chiều Đi" if d_str == "go" else "Chiều Về"

            # 1. Fetch Canonical Centerline
            cur.execute("""
                SELECT point_order, lat, lon, cum_distance_m
                FROM canonical_shape_master
                WHERE route_code = ? AND direction = ?
                ORDER BY point_order;
            """, (r_code, d_str))
            tb_rows = cur.fetchall()
            if not tb_rows:
                continue

            centerline = [[r[1], r[2], round(r[3], 1)] for r in tb_rows]
            max_s_m = centerline[-1][2] if centerline else 0.0

            # 2. Match Best OSM Polyline
            osm_cands = osm_routes.get(r_code, [])
            best_osm_poly = []
            best_osm_med = 999.0
            if osm_cands:
                tb_pts = [(r[0], r[1]) for r in centerline[::max(1, len(centerline) // 25)]]
                for cand in osm_cands:
                    poly = cand["polyline"]
                    dists = [min_dist_point_to_polyline(lat, lon, poly) for lat, lon in tb_pts]
                    dists.sort()
                    med = dists[len(dists) // 2]
                    if med < best_osm_med:
                        best_osm_med = med
                        best_osm_poly = sample_evenly(poly, 350)

            # 3. Fetch Canonical Stations
            cur.execute("""
                SELECT station_order, station_name, lat, lon, cum_distance_m
                FROM canonical_station_master
                WHERE route_code = ? AND direction = ?
                ORDER BY station_order;
            """, (r_code, d_str))
            st_rows = cur.fetchall()
            stations = []
            prev_s = 0.0
            for r in st_rows:
                s_cur = round(r[4], 1)
                delta_s = round(s_cur - prev_s, 1) if stations else 0.0
                prev_s = s_cur
                stations.append({
                    "order": r[0],
                    "name": r[1],
                    "lat": r[2],
                    "lon": r[3],
                    "s": s_cur,
                    "delta_s": delta_s
                })

            # 4. Fetch Vehicle Operational Classifications
            cur.execute("""
                SELECT vehicle_id, plate,
                       COUNT(1) as total,
                       MIN(s_bus_m) as s_min,
                       MAX(s_bus_m) as s_max,
                       AVG(cross_track_m) as avg_dperp,
                       SUM(CASE WHEN cross_track_m <= 30 THEN 1 ELSE 0 END) as in_lane
                FROM route_projected_telemetry
                WHERE route_code = ? AND direction = ?
                GROUP BY vehicle_id, plate
                ORDER BY total DESC;
            """, (r_code, d_str))
            veh_rows = cur.fetchall()
            vehicles = []
            depot_vehicles = set()
            for vid, plate, total, s_min, s_max, avg_d, in_lane in veh_rows:
                span = s_max - s_min
                in_lane_pct = round(in_lane * 100.0 / total, 1) if total > 0 else 0
                if span < 1000 and total >= 50:
                    cat = "depot_dwell"
                    status_label = "Nghỉ tour / Đỗ gara"
                    depot_vehicles.add(vid)
                elif in_lane_pct >= 85:
                    cat = "gold_active"
                    status_label = "Chuẩn làn cao (>85%)"
                else:
                    cat = "normal_active"
                    status_label = "Đang chạy tuyến"

                vehicles.append({
                    "vid": vid,
                    "plate": plate or f"ID-{vid}",
                    "total": total,
                    "span": round(span, 0),
                    "in_lane_pct": in_lane_pct,
                    "avg_dperp": round(avg_d, 1),
                    "category": cat,
                    "status_label": status_label
                })

            # 5. Fetch Stratified Operational Telemetry Pings
            cur.execute("""
                SELECT ping_id, vehicle_id, plate, lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, device_update_time
                FROM route_projected_telemetry
                WHERE route_code = ? AND direction = ?
                ORDER BY s_bus_m ASC, device_epoch ASC;
            """, (r_code, d_str))
            raw_pings = cur.fetchall()
            total_pings_db = len(raw_pings)

            operational_pings = []
            for p in raw_pings:
                vid = p[1]
                s = p[5]
                speed = p[7]
                if vid in depot_vehicles:
                    continue
                if (s < 300.0 or s > (max_s_m - 300.0)) and (speed is not None and speed < 5.0):
                    continue
                operational_pings.append(p)

            op_count = len(operational_pings)
            
            if op_count > 0:
                dperps = sorted([p[6] for p in operational_pings])
                med_d = round(dperps[len(dperps) // 2], 1)
                p90_d = round(dperps[int(len(dperps) * 0.9)], 1)
                in_15 = sum(1 for d in dperps if d <= 15.0)
                in_30 = sum(1 for d in dperps if d <= 30.0)
                in_50 = sum(1 for d in dperps if d <= 50.0)
                out_50 = op_count - in_50
                in_lane_30m_pct = round(in_30 / op_count * 100, 1)
                in_lane_15m_pct = round(in_15 / op_count * 100, 1)
                outliers_pct = round(out_50 / op_count * 100, 1)
            else:
                med_d = 0.0
                p90_d = 0.0
                in_lane_30m_pct = 0.0
                in_lane_15m_pct = 0.0
                outliers_pct = 0.0

            sampled_raw = sample_evenly(operational_pings, 1200)
            
            sampled_pings = []
            for p in sampled_raw:
                lat, lon = p[3], p[4]
                nearest_pt = find_nearest_centerline_point(lat, lon, centerline)
                sampled_pings.append([
                    p[0],
                    p[1],
                    p[2] or f"ID-{p[1]}",
                    round(lat, 6),
                    round(lon, 6),
                    round(p[5], 1),
                    round(p[6], 1),
                    round(p[7], 1) if p[7] is not None else 0.0,
                    p[8],
                    round(nearest_pt[0], 6),
                    round(nearest_pt[1], 6)
                ])

            data_by_route_dir[key] = {
                "route_code": r_code,
                "route_name": r_name,
                "direction": d_str,
                "direction_label": d_label,
                "total_pings_db": total_pings_db,
                "operational_pings_cnt": op_count,
                "rendered_pings_cnt": len(sampled_pings),
                "in_lane_30m_pct": in_lane_30m_pct,
                "in_lane_15m_pct": in_lane_15m_pct,
                "outliers_pct": outliers_pct,
                "median_d_perp": med_d,
                "p90_d_perp": p90_d,
                "osm_median_m": round(best_osm_med, 1) if best_osm_med < 900 else None,
                "max_s_m": round(max_s_m, 0),
                "centerline": centerline,
                "osm_polyline": best_osm_poly,
                "stations": stations,
                "vehicles": vehicles,
                "pings": sampled_pings
            }

        routes_summary.append({
            "code": r_code,
            "name": r_name,
            "go_pings": data_by_route_dir.get(f"{r_code}_go", {}).get("total_pings_db", 0),
            "re_pings": data_by_route_dir.get(f"{r_code}_re", {}).get("total_pings_db", 0),
            "go_in_lane": data_by_route_dir.get(f"{r_code}_go", {}).get("in_lane_30m_pct", 0),
            "re_in_lane": data_by_route_dir.get(f"{r_code}_re", {}).get("in_lane_30m_pct", 0),
            "go_med_d": data_by_route_dir.get(f"{r_code}_go", {}).get("median_d_perp", 0),
            "re_med_d": data_by_route_dir.get(f"{r_code}_re", {}).get("median_d_perp", 0),
            "osm_go": data_by_route_dir.get(f"{r_code}_go", {}).get("osm_median_m", None),
            "osm_re": data_by_route_dir.get(f"{r_code}_re", {}).get("osm_median_m", None)
        })

    return {
        "routes_summary": routes_summary,
        "data_by_route_dir": data_by_route_dir
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Hanoi Bus - Canonical Ground Truth Spatial Validation Suite</title>
    <!-- Leaflet & Bootstrap CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />

    <style>
        :root {
            --bg-dark: #0f172a;
            --bg-card: rgba(30, 41, 59, 0.85);
            --bg-card-border: rgba(255, 255, 255, 0.08);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-gold: #fbbf24;
            --accent-blue: #38bdf8;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-purple: #a855f7;
        }
        body, html {
            height: 100%;
            margin: 0;
            padding: 0;
            background-color: var(--bg-dark);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            overflow: hidden;
        }
        .mono {
            font-family: 'JetBrains Mono', monospace;
        }
        #top-navbar {
            height: 64px;
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--bg-card-border);
            z-index: 1050;
            position: relative;
        }
        .brand-badge {
            background: linear-gradient(135deg, #f59e0b, #d97706);
            color: #000;
            font-weight: 800;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
            padding: 3px 8px;
            border-radius: 4px;
        }
        #workspace-container {
            height: calc(100vh - 64px);
            display: flex;
            position: relative;
        }
        #sidebar {
            width: 440px;
            height: 100%;
            background: rgba(15, 23, 42, 0.96);
            border-right: 1px solid var(--bg-card-border);
            display: flex;
            flex-direction: column;
            z-index: 1000;
            overflow-y: auto;
            transition: width 0.3s ease;
        }
        #sidebar::-webkit-scrollbar {
            width: 6px;
        }
        #sidebar::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.15);
            border-radius: 3px;
        }
        #map-container {
            flex: 1;
            height: 100%;
            position: relative;
            background: #020617;
        }
        #map {
            width: 100%;
            height: 100%;
        }
        .metric-card {
            background: var(--bg-card);
            border: 1px solid var(--bg-card-border);
            border-radius: 10px;
            padding: 12px 14px;
            position: relative;
            overflow: hidden;
        }
        .metric-card .metric-val {
            font-size: 1.35rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }
        .metric-card .metric-label {
            font-size: 0.72rem;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.05em;
        }
        .custom-select-dark {
            background-color: #1e293b;
            color: #f8fafc;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 600;
            padding: 6px 10px;
        }
        .custom-select-dark:focus {
            background-color: #1e293b;
            color: #fff;
            border-color: var(--accent-gold);
            box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.25);
        }
        .btn-direction {
            background: #1e293b;
            color: #94a3b8;
            border: 1px solid rgba(255, 255, 255, 0.1);
            font-size: 0.8rem;
            font-weight: 600;
            padding: 6px 14px;
            transition: all 0.2s ease;
        }
        .btn-direction.active {
            background: #2563eb;
            color: #ffffff;
            border-color: #3b82f6;
            box-shadow: 0 0 10px rgba(37, 99, 235, 0.4);
        }
        .toggle-badge {
            cursor: pointer;
            user-select: none;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            border: 1px solid rgba(255, 255, 255, 0.1);
            background: rgba(30, 41, 59, 0.6);
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }
        .toggle-badge.active {
            background: rgba(255, 255, 255, 0.12);
            border-color: rgba(255, 255, 255, 0.3);
            color: #fff;
        }
        .station-row {
            cursor: pointer;
            padding: 7px 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.8rem;
            transition: background 0.15s;
        }
        .station-row:hover {
            background: rgba(56, 189, 248, 0.1);
        }
        .vehicle-row {
            cursor: pointer;
            padding: 6px 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.8rem;
            transition: background 0.15s;
        }
        .vehicle-row:hover {
            background: rgba(251, 191, 36, 0.1);
        }
        .map-legend {
            position: absolute;
            bottom: 24px;
            right: 24px;
            background: rgba(15, 23, 42, 0.92);
            backdrop-filter: blur(10px);
            border: 1px solid var(--bg-card-border);
            border-radius: 8px;
            padding: 12px 16px;
            font-size: 0.75rem;
            z-index: 1000;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;
        }
        .legend-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
        }
        .legend-line {
            width: 18px;
            height: 3px;
            display: inline-block;
        }
        @keyframes pulse-ring {
            0% { transform: scale(0.6); opacity: 1; }
            100% { transform: scale(2.2); opacity: 0; }
        }
        .pulse-marker {
            width: 24px;
            height: 24px;
            background: rgba(251, 191, 36, 0.4);
            border: 2px solid #fbbf24;
            border-radius: 50%;
            animation: pulse-ring 1.4s infinite ease-out;
        }
        .leaflet-popup-content-wrapper {
            background: rgba(15, 23, 42, 0.95) !important;
            color: #f8fafc !important;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 8px;
            backdrop-filter: blur(8px);
        }
        .leaflet-popup-tip {
            background: rgba(15, 23, 42, 0.95) !important;
        }
    </style>
</head>
<body>

    <!-- Top Navigation Header -->
    <nav id="top-navbar" class="d-flex align-items-center justify-content-between px-3">
        <div class="d-flex align-items-center gap-3">
            <span class="brand-badge"><i class="fa-solid fa-database me-1"></i> CANONICAL MASTER</span>
            <div>
                <span class="fw-bold fs-6 tracking-wide">HANOI BUS CANONICAL SUITE</span>
                <span class="text-muted d-none d-md-inline ms-2 fs-7">| Thẩm Định Hệ Quy Chiếu Gốc BusMap</span>
            </div>
        </div>

        <!-- Global Selectors -->
        <div class="d-flex align-items-center gap-2">
            <select id="route-select" class="custom-select-dark" style="min-width: 220px;" onchange="onRouteChanged()">
            </select>

            <div class="btn-group" role="group">
                <button type="button" id="btn-go" class="btn btn-direction active" onclick="setDirection('go')">
                    <i class="fa-solid fa-arrow-right me-1"></i> Chiều Đi
                </button>
                <button type="button" id="btn-re" class="btn btn-direction" onclick="setDirection('re')">
                    <i class="fa-solid fa-arrow-left me-1"></i> Chiều Về
                </button>
            </div>

            <select id="tile-select" class="custom-select-dark" style="width: 145px;" onchange="changeBasemap(this.value)">
                <option value="esri_sat" selected>🛰️ Esri Vệ Tinh</option>
                <option value="osm_fr">🗺️ OSM France</option>
                <option value="osm_standard">🌐 OSM Chuẩn</option>
            </select>

            <a href="telemetry_anomaly_audit_report.html" class="btn btn-sm btn-outline-warning" title="Mở Báo Cáo Kiểm Toán Dị Thường">
                <i class="fa-solid fa-bug me-1"></i> Báo Cáo Dị Thường
            </a>
        </div>
    </nav>

    <!-- Main Workspace -->
    <div id="workspace-container">

        <!-- Left Sidebar Details -->
        <div id="sidebar" class="p-3">

            <div class="mb-3">
                <div class="d-flex align-items-center justify-content-between mb-1">
                    <h5 id="route-title" class="fw-bold mb-0 text-white">Tuyến 22A</h5>
                    <span id="route-dir-badge" class="badge bg-primary px-2 py-1">Chiều Đi</span>
                </div>
                <div id="route-subtitle" class="text-muted fs-7">Bến xe Gia Lâm - Khu đô thị Kiến Hưng</div>
            </div>

            <!-- Metric Cards Grid -->
            <div class="row g-2 mb-3">
                <div class="col-6">
                    <div class="metric-card">
                        <div class="metric-label">Bám Làn (&le; 30m)</div>
                        <div id="metric-in-lane" class="metric-val text-success">96.8%</div>
                        <div id="metric-in-lane-sub" class="fs-8 text-muted">&le;15m: 87.3% | Lệch: 3.2%</div>
                    </div>
                </div>
                <div class="col-6">
                    <div class="metric-card">
                        <div class="metric-label">Trung Vị Sai Số d<sub>⊥</sub></div>
                        <div id="metric-med-d" class="metric-val text-info">5.4 m</div>
                        <div id="metric-med-d-sub" class="fs-8 text-muted">90th phân vị: 16.8 m</div>
                    </div>
                </div>
                <div class="col-6">
                    <div class="metric-card">
                        <div class="metric-label">Độ Trùng Khớp OSM</div>
                        <div id="metric-osm" class="metric-val text-warning">7.1 m</div>
                        <div class="fs-8 text-muted">BusMap vs OpenStreetMap</div>
                    </div>
                </div>
                <div class="col-6">
                    <div class="metric-card">
                        <div class="metric-label">Pings / Cự Ly Tuyến</div>
                        <div id="metric-pings-len" class="metric-val text-white">18.1k / 22.4km</div>
                        <div id="metric-vehicles-cnt" class="fs-8 text-muted">18 xe buýt vận hành</div>
                    </div>
                </div>
            </div>

            <!-- Layer Toggles -->
            <div class="mb-3 pb-2 border-bottom border-secondary border-opacity-25">
                <div class="fs-8 fw-bold text-muted text-uppercase mb-2">Lớp Bản Đồ Hiển Thị (Map Layers)</div>
                <div class="d-flex flex-wrap gap-2">
                    <span id="tog-timbus" class="toggle-badge active" onclick="toggleLayer('timbus')">
                        <span class="legend-line" style="background: #38bdf8;"></span> Tim Tuyến Chuẩn
                    </span>
                    <span id="tog-osm" class="toggle-badge active" onclick="toggleLayer('osm')">
                        <span class="legend-line" style="background: #f59e0b; border-top: 2px dashed #f59e0b; height: 0;"></span> Tim Tuyến OSM
                    </span>
                    <span id="tog-stations" class="toggle-badge active" onclick="toggleLayer('stations')">
                        <span class="legend-dot" style="background: #a855f7;"></span> Trạm Dừng
                    </span>
                    <span id="tog-pings" class="toggle-badge active" onclick="toggleLayer('pings')">
                        <span class="legend-dot" style="background: #10b981;"></span> GPS Telemetry
                    </span>
                    <span id="tog-vectors" class="toggle-badge" onclick="toggleLayer('vectors')">
                        <i class="fa-solid fa-ruler-combined text-warning"></i> Vector d<sub>⊥</sub>
                    </span>
                </div>
            </div>

            <!-- Vehicle Filter Dropdown -->
            <div class="mb-3">
                <div class="d-flex align-items-center justify-content-between mb-1">
                    <label class="fs-8 fw-bold text-muted text-uppercase">Bộ Lọc Xe (Vehicle Fleet Filter)</label>
                    <span id="vehicle-count-badge" class="badge bg-secondary fs-8">18 Xe</span>
                </div>
                <select id="vehicle-filter-select" class="form-select custom-select-dark w-100" onchange="onVehicleFilterChanged(this.value)">
                    <option value="ALL" selected>Tất cả phương tiện (All Active Fleet)</option>
                </select>
            </div>

            <!-- Nav Tabs -->
            <ul class="nav nav-tabs nav-fill mb-2 border-secondary border-opacity-25 fs-7" role="tablist">
                <li class="nav-item">
                    <button class="nav-link active text-white py-1" id="tab-stations-btn" data-bs-toggle="tab" data-bs-target="#tab-stations" type="button">
                        <i class="fa-solid fa-location-dot me-1 text-primary"></i> Trạm Dừng (<span id="station-count-tab">38</span>)
                    </button>
                </li>
                <li class="nav-item">
                    <button class="nav-link text-muted py-1" id="tab-vehicles-btn" data-bs-toggle="tab" data-bs-target="#tab-vehicles" type="button">
                        <i class="fa-solid fa-bus me-1 text-warning"></i> Đội Xe (<span id="vehicle-count-tab">18</span>)
                    </button>
                </li>
            </ul>

            <div class="tab-content flex-grow-1 overflow-auto">
                <div class="tab-pane fade show active" id="tab-stations" role="tabpanel">
                    <div id="stations-table-container"></div>
                </div>
                <div class="tab-pane fade" id="tab-vehicles" role="tabpanel">
                    <div id="vehicles-table-container"></div>
                </div>
            </div>

        </div>

        <!-- Right Main Map Container -->
        <div id="map-container">
            <div id="map"></div>

            <div class="map-legend">
                <div class="fw-bold mb-2 text-white">CHÚ GIẢI THỰC ĐỊA</div>
                <div class="legend-item">
                    <span class="legend-line" style="background: #0284c7; height: 4px;"></span>
                    <span>Tim đường Chuẩn (Canonical Shape Master)</span>
                </div>
                <div class="legend-item">
                    <span class="legend-line" style="border-top: 2px dashed #f59e0b; width: 18px;"></span>
                    <span>Tim đường OpenStreetMap (OSM Reference)</span>
                </div>
                <div class="legend-item">
                    <span class="legend-dot" style="background: #a855f7; border: 2px solid #fff;"></span>
                    <span>Trạm dừng chuẩn (Snap d_perp: 2.8m)</span>
                </div>
                <div class="legend-item">
                    <span class="legend-dot" style="background: #10b981;"></span>
                    <span>d<sub>⊥</sub> &le; 15m (Bám tim đường rất chuẩn)</span>
                </div>
                <div class="legend-item">
                    <span class="legend-dot" style="background: #06b6d4;"></span>
                    <span>15m &lt; d<sub>⊥</sub> &le; 30m (Làn ngoài / Lề đường)</span>
                </div>
                <div class="legend-item">
                    <span class="legend-dot" style="background: #f59e0b;"></span>
                    <span>30m &lt; d<sub>⊥</sub> &le; 50m (Vòng xoay / Tránh chướng ngại)</span>
                </div>
                <div class="legend-item">
                    <span class="legend-dot" style="background: #ef4444;"></span>
                    <span>d<sub>⊥</sub> &gt; 50m (Lệch làn / Ngoại lai)</span>
                </div>
            </div>
        </div>

    </div>

    <!-- Scripts -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>

    <script>
        const DATA = __PAYLOAD_JSON__;

        const TILE_SERVERS = {
            esri_sat: {
                url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                options: { maxZoom: 19, attribution: '&copy; Esri & Contributors' }
            },
            osm_fr: {
                url: 'https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png',
                options: { maxZoom: 19, subdomains: 'abc', attribution: '&copy; OpenStreetMap France' }
            },
            osm_standard: {
                url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                options: { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }
            }
        };

        let map = null;
        let currentTileLayer = null;
        let currentRouteCode = '22A';
        let currentDirection = 'go';
        let currentVehicleFilter = 'ALL';

        let layerCenterline = L.layerGroup();
        let layerOsm = L.layerGroup();
        let layerStations = L.layerGroup();
        let layerPings = L.layerGroup();
        let layerVectors = L.layerGroup();
        let activeBeaconMarker = null;

        const layerVisibility = {
            timbus: true,
            osm: true,
            stations: true,
            pings: true,
            vectors: false
        };

        window.addEventListener('DOMContentLoaded', () => {
            initMap();
            populateRouteSelector();
            loadCurrentRouteData();
        });

        function initMap() {
            map = L.map('map', {
                center: [21.0285, 105.8542],
                zoom: 13,
                zoomControl: true,
                preferCanvas: true
            });

            currentTileLayer = L.tileLayer(TILE_SERVERS.esri_sat.url, TILE_SERVERS.esri_sat.options).addTo(map);

            layerCenterline.addTo(map);
            layerOsm.addTo(map);
            layerStations.addTo(map);
            layerPings.addTo(map);
            layerVectors.addTo(map);

            setTimeout(() => map.invalidateSize(), 300);
        }

        function changeBasemap(tileKey) {
            if (!TILE_SERVERS[tileKey]) return;
            if (currentTileLayer) map.removeLayer(currentTileLayer);
            currentTileLayer = L.tileLayer(TILE_SERVERS[tileKey].url, TILE_SERVERS[tileKey].options).addTo(map);
            currentTileLayer.bringToBack();
        }

        function populateRouteSelector() {
            const sel = document.getElementById('route-select');
            sel.innerHTML = '';
            DATA.routes_summary.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r.code;
                const shortName = r.name.split(' - ')[1] || r.name;
                opt.textContent = `${r.code} - ${shortName} (${r.go_in_lane}% làn)`;
                if (r.code === currentRouteCode) opt.selected = true;
                sel.appendChild(opt);
            });
        }

        function onRouteChanged() {
            currentRouteCode = document.getElementById('route-select').value;
            currentVehicleFilter = 'ALL';
            loadCurrentRouteData();
        }

        function setDirection(d) {
            if (currentDirection === d) return;
            currentDirection = d;
            document.getElementById('btn-go').classList.toggle('active', d === 'go');
            document.getElementById('btn-re').classList.toggle('active', d === 're');
            currentVehicleFilter = 'ALL';
            loadCurrentRouteData();
        }

        function loadCurrentRouteData() {
            const key = `${currentRouteCode}_${currentDirection}`;
            const rData = DATA.data_by_route_dir[key];
            if (!rData) {
                alert(`Không tìm thấy dữ liệu cho ${currentRouteCode} (${currentDirection})`);
                return;
            }

            document.getElementById('route-title').textContent = `Tuyến ${rData.route_code}`;
            document.getElementById('route-subtitle').textContent = rData.route_name;
            document.getElementById('route-dir-badge').textContent = rData.direction_label;
            document.getElementById('route-dir-badge').className = rData.direction === 'go' ? 'badge bg-primary px-2 py-1' : 'badge bg-success px-2 py-1';

            document.getElementById('metric-in-lane').textContent = `${rData.in_lane_30m_pct}%`;
            document.getElementById('metric-in-lane-sub').textContent = `≤15m: ${rData.in_lane_15m_pct}% | Ngoại lai: ${rData.outliers_pct}%`;
            document.getElementById('metric-med-d').textContent = `${rData.median_d_perp} m`;
            document.getElementById('metric-med-d-sub').textContent = `P90 phân vị: ${rData.p90_d_perp} m`;
            
            if (rData.osm_median_m !== null) {
                document.getElementById('metric-osm').textContent = `${rData.osm_median_m} m`;
            } else {
                document.getElementById('metric-osm').textContent = 'N/A';
            }

            const lenKm = (rData.max_s_m / 1000).toFixed(1);
            document.getElementById('metric-pings-len').textContent = `${rData.operational_pings_cnt.toLocaleString()} / ${lenKm}km`;
            document.getElementById('metric-vehicles-cnt').textContent = `${rData.vehicles.length} xe buýt vận hành`;

            populateVehicleDropdown(rData.vehicles);
            populateStationsTable(rData.stations);
            populateVehiclesTable(rData.vehicles);
            renderMapLayers(rData);
        }

        function populateVehicleDropdown(vehicles) {
            const sel = document.getElementById('vehicle-filter-select');
            sel.innerHTML = '<option value="ALL">Tất cả phương tiện (All Active Fleet)</option>';
            vehicles.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v.vid;
                opt.textContent = `${v.plate} | ${v.total.toLocaleString()} pings | ${v.in_lane_pct}% bám làn`;
                if (v.vid == currentVehicleFilter) opt.selected = true;
                sel.appendChild(opt);
            });
            document.getElementById('vehicle-count-badge').textContent = `${vehicles.length} Xe`;
            document.getElementById('vehicle-count-tab').textContent = vehicles.length;
        }

        function onVehicleFilterChanged(vid) {
            currentVehicleFilter = vid;
            const key = `${currentRouteCode}_${currentDirection}`;
            const rData = DATA.data_by_route_dir[key];
            if (rData) renderPingsAndVectors(rData);
        }

        function populateStationsTable(stations) {
            document.getElementById('station-count-tab').textContent = stations.length;
            const cont = document.getElementById('stations-table-container');
            let html = '';
            stations.forEach(s => {
                const sKm = (s.s / 1000).toFixed(2);
                html += `
                <div class="station-row d-flex align-items-center justify-content-between" onclick="flyToStation(${s.lat}, ${s.lon}, '${s.name.replace(/'/g, "\\'")}', ${s.order}, ${s.s}, ${s.delta_s})">
                    <div class="d-flex align-items-center gap-2 overflow-hidden">
                        <span class="badge bg-secondary fs-8 mono" style="min-width: 28px;">${s.order}</span>
                        <span class="text-truncate text-white" title="${s.name}">${s.name}</span>
                    </div>
                    <div class="text-end mono fs-8 text-muted" style="min-width: 75px;">
                        <div>${sKm} km</div>
                        <div class="text-info">+${s.delta_s}m</div>
                    </div>
                </div>`;
            });
            cont.innerHTML = html;
        }

        function populateVehiclesTable(vehicles) {
            const cont = document.getElementById('vehicles-table-container');
            let html = '';
            vehicles.forEach(v => {
                const badgeClass = v.category === 'gold_active' ? 'bg-success' : (v.category === 'depot_dwell' ? 'bg-warning text-dark' : 'bg-info text-dark');
                html += `
                <div class="vehicle-row d-flex align-items-center justify-content-between" onclick="selectVehicle('${v.vid}')">
                    <div>
                        <div class="fw-bold text-white mono">${v.plate}</div>
                        <span class="badge ${badgeClass} fs-9">${v.status_label}</span>
                    </div>
                    <div class="text-end mono fs-8">
                        <div class="text-white">${v.in_lane_pct}% bám làn</div>
                        <div class="text-muted">${v.total.toLocaleString()} pings (d_⊥: ${v.avg_dperp}m)</div>
                    </div>
                </div>`;
            });
            cont.innerHTML = html;
        }

        function selectVehicle(vid) {
            document.getElementById('vehicle-filter-select').value = vid;
            onVehicleFilterChanged(vid);
        }

        function renderMapLayers(rData) {
            layerCenterline.clearLayers();
            if (rData.centerline && rData.centerline.length > 0) {
                const latlngs = rData.centerline.map(p => [p[0], p[1]]);
                const poly = L.polyline(latlngs, {
                    color: '#0284c7',
                    weight: 5,
                    opacity: 0.9,
                    lineCap: 'round',
                    lineJoin: 'round'
                });
                const lenKm = (rData.max_s_m / 1000).toFixed(1);
                poly.bindTooltip(`Tim tuyến Canonical: ${rData.route_code} (${rData.direction_label}) - ${lenKm} km`, { sticky: true });
                layerCenterline.addLayer(poly);
                map.fitBounds(poly.getBounds(), { padding: [30, 30] });
            }

            layerOsm.clearLayers();
            if (rData.osm_polyline && rData.osm_polyline.length > 0) {
                const osmPoly = L.polyline(rData.osm_polyline, {
                    color: '#f59e0b',
                    weight: 3,
                    dashArray: '6, 6',
                    opacity: 0.85
                });
                osmPoly.bindTooltip(`Tim tuyến OpenStreetMap (OSM) - Độ lệch trung vị: ${rData.osm_median_m || 'N/A'}m`, { sticky: true });
                layerOsm.addLayer(osmPoly);
            }

            layerStations.clearLayers();
            rData.stations.forEach(s => {
                const marker = L.circleMarker([s.lat, s.lon], {
                    radius: 6,
                    fillColor: '#a855f7',
                    color: '#ffffff',
                    weight: 2,
                    fillOpacity: 0.95
                });
                const popupContent = `
                    <div style="font-size: 0.85rem; min-width: 200px;">
                        <div class="fw-bold text-warning mb-1"><i class="fa-solid fa-location-dot me-1"></i> Trạm #${s.order}</div>
                        <div class="text-white fw-semibold mb-2">${s.name}</div>
                        <div class="mono fs-8 text-muted">
                            <div>Tiến độ s: <b>${s.s.toLocaleString()} m</b> (${(s.s/1000).toFixed(2)} km)</div>
                            <div>Cự ly liên trạm &Delta;s: <b>${s.delta_s} m</b></div>
                        </div>
                    </div>
                `;
                marker.bindPopup(popupContent);
                marker.bindTooltip(`#${s.order}: ${s.name}`, { direction: 'top', offset: [0, -6] });
                layerStations.addLayer(marker);
            });

            renderPingsAndVectors(rData);
        }

        function renderPingsAndVectors(rData) {
            layerPings.clearLayers();
            layerVectors.clearLayers();

            const pingsToRender = rData.pings.filter(p => {
                if (currentVehicleFilter === 'ALL') return true;
                return p[1] == currentVehicleFilter;
            });

            pingsToRender.forEach(p => {
                const dperp = p[6];
                let color = '#10b981';
                if (dperp > 50) color = '#ef4444';
                else if (dperp > 30) color = '#f59e0b';
                else if (dperp > 15) color = '#06b6d4';

                const marker = L.circleMarker([p[3], p[4]], {
                    radius: 4,
                    fillColor: color,
                    color: '#000000',
                    weight: 1,
                    fillOpacity: 0.85
                });

                const popupHtml = `
                    <div style="font-size: 0.82rem; min-width: 220px;">
                        <div class="d-flex align-items-center justify-content-between mb-1">
                            <span class="badge bg-secondary mono">${p[2]}</span>
                            <span class="badge" style="background: ${color}; color: #000;">d_&perp; = ${p[6]}m</span>
                        </div>
                        <div class="mono fs-8 text-muted mt-2">
                            <div>Tiến độ s: <b>${p[5].toLocaleString()} m</b></div>
                            <div>Vận tốc V: <b>${p[7]} km/h</b></div>
                            <div>Thời gian: <b>${p[8]}</b></div>
                            <div>Tọa độ: <b>${p[3].toFixed(5)}, ${p[4].toFixed(5)}</b></div>
                        </div>
                    </div>
                `;
                marker.bindPopup(popupHtml);
                marker.on('click', () => {
                    drawSnapVector([p[3], p[4]], [p[9], p[10]], p[6]);
                });

                layerPings.addLayer(marker);

                if (layerVisibility.vectors && dperp > 10) {
                    const vec = L.polyline([[p[3], p[4]], [p[9], p[10]]], {
                        color: color,
                        weight: 1.5,
                        dashArray: '3, 3',
                        opacity: 0.7
                    });
                    layerVectors.addLayer(vec);
                }
            });
        }

        function drawSnapVector(fromPt, toPt, distM) {
            layerVectors.clearLayers();
            const vec = L.polyline([fromPt, toPt], {
                color: '#fbbf24',
                weight: 2.5,
                dashArray: '4, 4',
                opacity: 0.95
            }).addTo(layerVectors);
            vec.bindTooltip(`Khoảng cách lệch d_&perp; = ${distM}m`, { permanent: true, direction: 'center', className: 'mono fs-8' });
        }

        function flyToStation(lat, lon, name, order, s, delta_s) {
            map.flyTo([lat, lon], 17, { duration: 1.0 });

            if (activeBeaconMarker) {
                map.removeLayer(activeBeaconMarker);
            }

            const pulseIcon = L.divIcon({
                className: 'pulse-marker',
                iconSize: [24, 24],
                iconAnchor: [12, 12]
            });
            activeBeaconMarker = L.marker([lat, lon], { icon: pulseIcon }).addTo(map);

            setTimeout(() => {
                L.popup()
                    .setLatLng([lat, lon])
                    .setContent(`
                        <div style="font-size: 0.85rem; min-width: 200px;">
                            <div class="fw-bold text-warning mb-1"><i class="fa-solid fa-location-dot me-1"></i> Trạm #${order}</div>
                            <div class="text-white fw-semibold mb-2">${name}</div>
                            <div class="mono fs-8 text-muted">
                                <div>Tiến độ s: <b>${s.toLocaleString()} m</b></div>
                                <div>Cự ly liên trạm &Delta;s: <b>${delta_s} m</b></div>
                            </div>
                        </div>
                    `)
                    .openOn(map);
            }, 1050);
        }

        function toggleLayer(layerKey) {
            layerVisibility[layerKey] = !layerVisibility[layerKey];
            const badge = document.getElementById(`tog-${layerKey}`);
            badge.classList.toggle('active', layerVisibility[layerKey]);

            if (layerKey === 'timbus') {
                if (layerVisibility.timbus) map.addLayer(layerCenterline);
                else map.removeLayer(layerCenterline);
            } else if (layerKey === 'osm') {
                if (layerVisibility.osm) map.addLayer(layerOsm);
                else map.removeLayer(layerOsm);
            } else if (layerKey === 'stations') {
                if (layerVisibility.stations) map.addLayer(layerStations);
                else map.removeLayer(layerStations);
            } else if (layerKey === 'pings') {
                if (layerVisibility.pings) map.addLayer(layerPings);
                else map.removeLayer(layerPings);
            } else if (layerKey === 'vectors') {
                const key = `${currentRouteCode}_${currentDirection}`;
                const rData = DATA.data_by_route_dir[key];
                if (rData) renderPingsAndVectors(rData);
            }
        }
    </script>
</body>
</html>
"""


def generate_html(data_bundle: dict):
    payload_json = json.dumps(data_bundle, ensure_ascii=False)
    html_content = HTML_TEMPLATE.replace("__PAYLOAD_JSON__", payload_json)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

    file_size_mb = os.path.getsize(OUTPUT_HTML) / (1024 * 1024)
    print(f"\nSuccessfully generated {OUTPUT_HTML} ({file_size_mb:.2f} MB)")


def main():
    print("=" * 80)
    print("CANONICAL GROUND TRUTH INTERACTIVE SPATIAL VALIDATION REPORT GENERATOR")
    print("=" * 80)

    print(f"Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)

    print(f"Loading OpenStreetMap transit relations from: {OSM_PATH}")
    osm_routes = load_osm_routes()
    print(f"Loaded {len(osm_routes)} unique route numbers from OSM.")

    data_bundle = build_gold_routes_data(conn, osm_routes)
    conn.close()

    print("\nGenerating interactive HTML report...")
    generate_html(data_bundle)
    print("=" * 80)


if __name__ == "__main__":
    main()
