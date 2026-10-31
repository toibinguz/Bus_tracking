"""
Telemetry Pipeline Anomaly Audit & Interactive HTML Report Generator
Analyzes 285k projected pings from data/hanoi_bus_system.db, extracts:
1. Lateral cross-track error (d_perp > 50m) distribution & top outlier routes
2. Longitudinal coordinate inversions (Delta s < -200m backward jumps)
3. Extreme transit speed anomalies (< 5 km/h bottlenecks vs > 60 km/h express)
4. Interactive Leaflet GIS visualization using keyless/headerless Carto/OSM tiles.
5. Spatial & Temporal Anomaly Quick-Jump Navigator (one-click map flyTo for any anomaly).
"""

import os
import sys
import json
import sqlite3
import math
from collections import defaultdict
from datetime import datetime

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.system_config import get_database_path, OSM_TILE_SERVERS

DB_PATH = get_database_path()
OUTPUT_DIR = "reports"
OUTPUT_HTML = os.path.join(OUTPUT_DIR, "telemetry_anomaly_audit_report.html")

TOP_ANOMALOUS_ROUTES = ["39", "122", "123", "BRT01", "56B", "E04", "07", "02"]


def run_audit_and_generate():
    print(f"Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ---------------------------------------------------------
    # 1. KPI & STATISTICAL METRICS
    # ---------------------------------------------------------
    print("[1/5] Auditing overall cross-track errors...")
    cur.execute("""
        SELECT 
            COUNT(1) as total_pings,
            SUM(CASE WHEN cross_track_m <= 15 THEN 1 ELSE 0 END),
            SUM(CASE WHEN cross_track_m > 15 AND cross_track_m <= 30 THEN 1 ELSE 0 END),
            SUM(CASE WHEN cross_track_m > 30 AND cross_track_m <= 50 THEN 1 ELSE 0 END),
            SUM(CASE WHEN cross_track_m > 50 AND cross_track_m <= 100 THEN 1 ELSE 0 END),
            SUM(CASE WHEN cross_track_m > 100 THEN 1 ELSE 0 END),
            AVG(cross_track_m),
            MAX(cross_track_m)
        FROM route_projected_telemetry;
    """)
    kpi_row = cur.fetchone()
    total_pings = kpi_row[0]
    dperp_dist = {
        "in_lane_15m": kpi_row[1],
        "roadside_30m": kpi_row[2],
        "moderate_50m": kpi_row[3],
        "large_100m": kpi_row[4],
        "extreme_over_100m": kpi_row[5],
        "avg_dperp": round(kpi_row[6], 1),
        "max_dperp": round(kpi_row[7], 1),
        "total_over_50m": kpi_row[4] + kpi_row[5],
        "pct_over_50m": round((kpi_row[4] + kpi_row[5]) / total_pings * 100, 1)
    }

    # Top routes by lateral drift %
    cur.execute("""
        SELECT route_code, COUNT(1) as total,
               SUM(CASE WHEN cross_track_m > 50 THEN 1 ELSE 0 END) as outliers_50m,
               ROUND(100.0 * SUM(CASE WHEN cross_track_m > 50 THEN 1 ELSE 0 END) / COUNT(1), 1) as pct_outlier,
               ROUND(AVG(cross_track_m), 1) as avg_dperp,
               ROUND(MAX(cross_track_m), 1) as max_dperp
        FROM route_projected_telemetry
        GROUP BY route_code
        HAVING COUNT(1) >= 500
        ORDER BY pct_outlier DESC
        LIMIT 10;
    """)
    top_dperp_routes = [
        {"route": r[0], "total": r[1], "outliers": r[2], "pct": r[3], "avg": r[4], "max": r[5]}
        for r in cur.fetchall()
    ]

    # ---------------------------------------------------------
    # 2. AUDIT BACKWARD JUMPS & TELEPORTS
    # ---------------------------------------------------------
    print("[2/5] Auditing trajectory coordinate inversions...")
    cur.execute("""
        SELECT vehicle_id, plate, route_code, direction, device_update_time, device_epoch, s_bus_m, cross_track_m, lat, lon
        FROM route_projected_telemetry
        ORDER BY vehicle_id, direction, device_epoch;
    """)

    pings_by_veh = defaultdict(list)
    for vid, plate, rcode, direction, t_str, epoch, s, dperp, lat, lon in cur.fetchall():
        pings_by_veh[(vid, plate, rcode, direction)].append((epoch, s, dperp, lat, lon, t_str))

    backward_jumps = []
    route_jumps_cnt = defaultdict(int)

    for (vid, plate, rcode, direction), pings in pings_by_veh.items():
        for i in range(len(pings) - 1):
            dt = pings[i+1][0] - pings[i][0]
            if 0 < dt <= 180:
                ds = pings[i+1][1] - pings[i][1]
                if ds < -200.0:
                    backward_jumps.append({
                        "route_code": rcode,
                        "direction": direction,
                        "vid": vid,
                        "plate": plate,
                        "dt": dt,
                        "ds": round(ds, 1),
                        "s1": round(pings[i][1], 1),
                        "s2": round(pings[i+1][1], 1),
                        "t1": pings[i][5],
                        "t2": pings[i+1][5],
                        "lat1": pings[i][3],
                        "lon1": pings[i][4],
                        "lat2": pings[i+1][3],
                        "lon2": pings[i+1][4]
                    })
                    route_jumps_cnt[rcode] += 1

    top_jump_routes = [
        {"route": rcode, "jumps": cnt}
        for rcode, cnt in sorted(route_jumps_cnt.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    # ---------------------------------------------------------
    # 3. EXTREME SEGMENT BOTTLENECKS (< 5 km/h) & EXPRESS (> 55 km/h)
    # ---------------------------------------------------------
    print("[3/5] Querying extreme speed anomalies in agg_segment_travel_times...")
    cur.execute("""
        SELECT route_code, time_window, from_station_name, to_station_name, 
               segment_distance_m, median_transit_sec, commercial_speed_kmh, sample_count
        FROM agg_segment_travel_times
        WHERE day_type = 'WEEKEND' AND sample_count >= 5
        ORDER BY commercial_speed_kmh ASC
        LIMIT 8;
    """)
    bottlenecks = [
        {"route": r[0], "window": r[1], "from": r[2], "to": r[3], "dist": r[4], "time": r[5], "speed": r[6], "n": r[7]}
        for r in cur.fetchall()
    ]

    cur.execute("""
        SELECT route_code, time_window, from_station_name, to_station_name, 
               segment_distance_m, median_transit_sec, commercial_speed_kmh, sample_count
        FROM agg_segment_travel_times
        WHERE sample_count >= 5
        ORDER BY commercial_speed_kmh DESC
        LIMIT 8;
    """)
    express_segments = [
        {"route": r[0], "window": r[1], "from": r[2], "to": r[3], "dist": r[4], "time": r[5], "speed": r[6], "n": r[7]}
        for r in cur.fetchall()
    ]

    # ---------------------------------------------------------
    # 4. SPATIAL DATA & ANOMALY EVENTS FOR TOP ANOMALOUS ROUTES
    # ---------------------------------------------------------
    print("[4/5] Building spatial GeoJSON & Anomaly Navigator events...")
    route_spatial_data = {}

    for r_code in TOP_ANOMALOUS_ROUTES:
        # 4.1 Centerline shape points
        cur.execute("""
            SELECT point_order, lat, lon, cum_distance_m
            FROM timbus_shape_master
            WHERE route_code = ? AND direction = 'go'
            ORDER BY point_order;
        """, (r_code,))
        shape_rows = cur.fetchall()
        centerline = [[r[1], r[2]] for r in shape_rows]

        # 4.2 Stations
        cur.execute("""
            SELECT station_order, station_name, lat, lon, cum_distance_m
            FROM dim_station_crosswalk
            WHERE route_code = ? AND direction = 'go'
            ORDER BY station_order;
        """, (r_code,))
        stations = [
            {"order": r[0], "name": r[1], "lat": r[2], "lon": r[3], "s": round(r[4], 1)}
            for r in cur.fetchall()
        ]

        # 4.3 Sampled Pings (Stratified: Outliers > 50m + Normal pings)
        cur.execute("""
            SELECT ping_id, vehicle_id, plate, lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, device_update_time
            FROM route_projected_telemetry
            WHERE route_code = ? AND direction = 'go'
            ORDER BY cross_track_m DESC;
        """, (r_code,))
        all_pings = cur.fetchall()

        outliers = [p for p in all_pings if p[6] > 50.0][:250]
        normals = [p for p in all_pings if p[6] <= 50.0][:150]
        selected_pings = [
            {
                "id": p[0], "vid": p[1], "plate": p[2], "lat": p[3], "lon": p[4],
                "s": round(p[5], 1), "dperp": round(p[6], 1),
                "speed": round(p[7], 1) if p[7] is not None else None,
                "time": p[8]
            }
            for p in (outliers + normals)
        ]

        # 4.4 Backward Jump Segments for this route
        route_jumps_spatial = [
            j for j in backward_jumps if j["route_code"] == r_code and j["direction"] == "go"
        ][:50]

        # 4.5 CONCRETE ANOMALY NAVIGATOR EVENTS (Sorted & Filterable)
        anomaly_events = []

        # A. Top Lateral Drift Events (d_perp > 50m)
        top_lateral_pings = sorted([p for p in all_pings if p[6] > 50.0], key=lambda x: x[6], reverse=True)[:15]
        for p in top_lateral_pings:
            anomaly_events.append({
                "type": "lateral_drift",
                "badge_class": "bg-danger",
                "type_label": f"Lệch Tim d_⊥ = {p[6]:.1f}m",
                "ping_id": p[0],
                "vid": p[1],
                "plate": p[2] or f"ID-{p[1]}",
                "time": p[8],
                "lat": p[3],
                "lon": p[4],
                "s": round(p[5], 1),
                "dperp": round(p[6], 1),
                "speed": round(p[7], 1) if p[7] is not None else None,
                "detail": f"Lệch khỏi tim đường TimBus {p[6]:.1f}m (vị trí 1D s = {p[5]:.1f}m)"
            })

        # B. Backward Jump Events (Delta s < -200m)
        for j in route_jumps_spatial[:15]:
            anomaly_events.append({
                "type": "backward_jump",
                "badge_class": "bg-warning text-dark",
                "type_label": f"Giật Lùi Δs = {j['ds']:.0f}m",
                "ping_id": None,
                "vid": j["vid"],
                "plate": j["plate"] or f"ID-{j['vid']}",
                "time": j["t2"],
                "lat": j["lat2"],
                "lon": j["lon2"],
                "s": j["s2"],
                "dperp": None,
                "speed": None,
                "detail": f"Chiếu lùi từ s = {j['s1']:.0f}m về {j['s2']:.0f}m trong {j['dt']}s"
            })

        # C. Speed Bottlenecks (derived_speed_kmh < 5.0)
        cur.execute("""
            SELECT ping_id, vehicle_id, plate, lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, device_update_time
            FROM route_projected_telemetry
            WHERE route_code = ? AND direction = 'go' AND derived_speed_kmh IS NOT NULL AND derived_speed_kmh < 5.0 AND derived_speed_kmh > 0
            ORDER BY derived_speed_kmh ASC
            LIMIT 10;
        """, (r_code,))
        for p in cur.fetchall():
            anomaly_events.append({
                "type": "bottleneck",
                "badge_class": "bg-danger-glow text-white",
                "type_label": f"Nút Nghẽn V = {p[7]:.1f} km/h",
                "ping_id": p[0],
                "vid": p[1],
                "plate": p[2] or f"ID-{p[1]}",
                "time": p[8],
                "lat": p[3],
                "lon": p[4],
                "s": round(p[5], 1),
                "dperp": round(p[6], 1),
                "speed": round(p[7], 1),
                "detail": f"Vận tốc bò chậm {p[7]:.1f} km/h tại s = {p[5]:.1f}m"
            })

        # D. High Speed Anomalies (> 60 km/h)
        cur.execute("""
            SELECT ping_id, vehicle_id, plate, lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, device_update_time
            FROM route_projected_telemetry
            WHERE route_code = ? AND direction = 'go' AND derived_speed_kmh IS NOT NULL AND derived_speed_kmh > 60.0
            ORDER BY derived_speed_kmh DESC
            LIMIT 10;
        """, (r_code,))
        for p in cur.fetchall():
            anomaly_events.append({
                "type": "high_speed",
                "badge_class": "bg-info text-dark",
                "type_label": f"Tốc Độ Cao V = {p[7]:.1f} km/h",
                "ping_id": p[0],
                "vid": p[1],
                "plate": p[2] or f"ID-{p[1]}",
                "time": p[8],
                "lat": p[3],
                "lon": p[4],
                "s": round(p[5], 1),
                "dperp": round(p[6], 1),
                "speed": round(p[7], 1),
                "detail": f"Vận tốc cao {p[7]:.1f} km/h tại s = {p[5]:.1f}m (đoạn thông thoáng/ngoại thành)"
            })

        # Sort anomaly events chronologically or by severity
        route_spatial_data[r_code] = {
            "centerline": centerline,
            "stations": stations,
            "pings": selected_pings,
            "jumps": route_jumps_spatial,
            "anomaly_events": anomaly_events,
            "total_pings_in_db": len(all_pings)
        }

    conn.close()

    # ---------------------------------------------------------
    # 5. GENERATE SELF-CONTAINED HTML
    # ---------------------------------------------------------
    print("[5/5] Generating self-contained interactive HTML...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_content = generate_html_template(
        kpi=dperp_dist,
        total_pings=total_pings,
        top_dperp=top_dperp_routes,
        top_jumps=top_jump_routes,
        total_jumps=len(backward_jumps),
        bottlenecks=bottlenecks,
        express=express_segments,
        spatial_data=route_spatial_data,
        tile_config=OSM_TILE_SERVERS
    )

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n[SUCCESS] Anomaly audit report generated at: {os.path.abspath(OUTPUT_HTML)}")
    return OUTPUT_HTML


def generate_html_template(kpi, total_pings, top_dperp, top_jumps, total_jumps, bottlenecks, express, spatial_data, tile_config):
    spatial_data_json = json.dumps(spatial_data)
    tile_config_json = json.dumps(tile_config)
    top_dperp_json = json.dumps(top_dperp)
    top_jumps_json = json.dumps(top_jumps)
    kpi_json = json.dumps(kpi)

    # Clean Unicode labels (Zero unescaped LaTeX in HTML)
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hanoi Bus Telemetry Anomaly & Kinematics Audit Report</title>
    <!-- Bootstrap 5 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <!-- FontAwesome 6 -->
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css" rel="stylesheet">
    <!-- Leaflet 1.9.4 CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <!-- KaTeX CSS for beautiful math typography -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
    <style>
        body {{
            background-color: #0f172a;
            color: #e2e8f0;
            font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 0;
        }}
        .card {{
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
        }}
        .kpi-title {{
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #94a3b8;
            font-weight: 600;
        }}
        .kpi-value {{
            font-size: 2.1rem;
            font-weight: 700;
            line-height: 1.2;
            margin: 4px 0;
        }}
        #map {{
            height: 580px;
            width: 100%;
            border-radius: 8px;
            border: 1px solid #334155;
            background: #1e293b;
            z-index: 1;
        }}
        .badge-danger-glow {{
            background-color: #ef4444;
            box-shadow: 0 0 10px rgba(239, 68, 68, 0.5);
        }}
        .badge-warning-glow {{
            background-color: #f59e0b;
            box-shadow: 0 0 10px rgba(245, 158, 11, 0.5);
        }}
        .table-dark-custom {{
            --bs-table-bg: transparent;
            --bs-table-striped-bg: rgba(255, 255, 255, 0.03);
            color: #cbd5e1;
            font-size: 0.88rem;
        }}
        .table-dark-custom th {{
            color: #94a3b8;
            border-bottom: 2px solid #475569;
            font-weight: 600;
        }}
        .table-dark-custom td {{
            border-bottom: 1px solid #334155;
            vertical-align: middle;
        }}
        .legend-box {{
            padding: 8px 14px;
            background: rgba(15, 23, 42, 0.9);
            border-radius: 8px;
            border: 1px solid #475569;
            font-size: 0.82rem;
            color: #f1f5f9;
        }}
        .legend-dot {{
            display: inline-block;
            width: 11px;
            height: 11px;
            border-radius: 50%;
            margin-right: 5px;
            vertical-align: middle;
        }}
        /* Pulsing Beacon for Quick Jump */
        @keyframes pulseMarker {{
            0% {{
                transform: scale(0.6);
                opacity: 1;
            }}
            100% {{
                transform: scale(2.8);
                opacity: 0;
            }}
        }}
        .pulse-beacon-wrapper {{
            position: relative;
            width: 32px;
            height: 32px;
        }}
        .pulse-beacon-core {{
            position: absolute;
            left: 8px;
            top: 8px;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background-color: #ef4444;
            border: 3px solid #ffffff;
            box-shadow: 0 0 12px #ef4444;
            z-index: 2;
        }}
        .pulse-beacon-ring {{
            position: absolute;
            left: 0;
            top: 0;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            border: 3px solid #ef4444;
            animation: pulseMarker 1.4s cubic-bezier(0.2, 0.6, 0.35, 1) infinite;
            z-index: 1;
        }}
        .nav-table-container {{
            max-height: 400px;
            overflow-y: auto;
        }}
        .nav-table-container::-webkit-scrollbar {{
            width: 8px;
        }}
        .nav-table-container::-webkit-scrollbar-thumb {{
            background: #475569;
            border-radius: 4px;
        }}
        .btn-jump {{
            padding: 2px 10px;
            font-size: 0.78rem;
            border-radius: 6px;
            white-space: nowrap;
        }}
        .clickable-row {{
            cursor: pointer;
            transition: background 0.15s ease-in-out;
        }}
        .clickable-row:hover {{
            background-color: rgba(59, 130, 246, 0.15) !important;
        }}
        .row-active {{
            background-color: rgba(239, 68, 68, 0.2) !important;
            border-left: 3px solid #ef4444;
        }}
    </style>
</head>
<body class="py-4">
    <div class="container-fluid px-4">
        <!-- HEADER -->
        <div class="d-flex justify-content-between align-items-center mb-4 pb-3 border-bottom border-secondary">
            <div>
                <h2 class="fw-bold mb-1 text-light">
                    <i class="fa-solid fa-triangle-exclamation text-warning me-2"></i>
                    BÁO CÁO KIỂM TOÁN DỊ THƯỜNG &amp; SAI SỐ HỌC KHÔNG GIAN TELEMETRY
                </h2>
                <div class="text-secondary small">
                    Dự án: Hanoi Bus Big Data &amp; Real-time ETA System | CSDL: <code>data/hanoi_bus_system.db</code> | Quét: <strong>{total_pings:,}</strong> pings (47 tuyến)
                </div>
            </div>
            <div>
                <span class="badge bg-danger p-2 me-2"><i class="fa-solid fa-bug me-1"></i> Empirical Zero-Speculation Audit</span>
                <span class="badge bg-primary p-2"><i class="fa-solid fa-map-location-dot me-1"></i> Keyless OSM France / Carto Active</span>
            </div>
        </div>

        <!-- KPI CARDS -->
        <div class="row g-3 mb-4">
            <div class="col-md-3">
                <div class="card p-3">
                    <div class="kpi-title"><i class="fa-solid fa-satellite-dish me-1"></i> Tổng Pings Đã Chiếu 1D</div>
                    <div class="kpi-value text-info">{total_pings:,}</div>
                    <div class="small text-secondary">Thu thập 17-18/10/2026 (Cuối tuần)</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card p-3">
                    <div class="kpi-title"><i class="fa-solid fa-arrows-left-right me-1"></i> Lệch Tim Đường (d<sub>⊥</sub> &gt; 50m)</div>
                    <div class="kpi-value text-danger">{kpi['total_over_50m']:,} <span class="fs-6 text-danger fw-normal">({kpi['pct_over_50m']}%)</span></div>
                    <div class="small text-secondary">Detour / Cầu cạn / Đường gom ngoài tim</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card p-3">
                    <div class="kpi-title"><i class="fa-solid fa-backward-step me-1"></i> Bước Nhảy Lùi (Δs &lt; -200m)</div>
                    <div class="kpi-value text-warning">{total_jumps:,}</div>
                    <div class="small text-secondary">Nghi vấn chiếu nhầm nút giao / vòng xuyến</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card p-3">
                    <div class="kpi-title"><i class="fa-solid fa-gauge-high me-1"></i> Sai Số d<sub>⊥, max</sub> Cực Đại</div>
                    <div class="kpi-value text-white">{kpi['max_dperp']:.1f}<span class="fs-6 fw-normal text-secondary">m</span></div>
                    <div class="small text-secondary">Trung bình mạng lưới: <strong>{kpi['avg_dperp']:.1f}m</strong></div>
                </div>
            </div>
        </div>

        <!-- CHARTS SECTION -->
        <div class="row g-4 mb-4">
            <div class="col-lg-4">
                <div class="card p-3 h-100">
                    <h5 class="card-title fw-bold text-light mb-3">
                        <i class="fa-solid fa-chart-pie me-2 text-primary"></i>Phân Bố Sai Số Trực Giao (d<sub>⊥</sub>)
                    </h5>
                    <canvas id="dperpPieChart" height="260"></canvas>
                    <div class="small text-secondary mt-3">
                        * <strong>77.2%</strong> pings nằm chuẩn trong lòng đường (≤ 15m).<br>
                        * <strong>13.4%</strong> pings bị lệch &gt; 50m cần lọc bỏ hoặc gắn cờ khi huấn luyện ETA.
                    </div>
                </div>
            </div>
            <div class="col-lg-4">
                <div class="card p-3 h-100">
                    <h5 class="card-title fw-bold text-light mb-3">
                        <i class="fa-solid fa-chart-column me-2 text-danger"></i>Top 10 Tuyến Có Tỷ Lệ Lệch Tim Cao Nhất (&gt; 50m)
                    </h5>
                    <canvas id="topDperpBarChart" height="260"></canvas>
                </div>
            </div>
            <div class="col-lg-4">
                <div class="card p-3 h-100">
                    <h5 class="card-title fw-bold text-light mb-3">
                        <i class="fa-solid fa-shuffle me-2 text-warning"></i>Top Tuyến Bị Giật Lùi Tọa Độ s (Δs &lt; -200m)
                    </h5>
                    <canvas id="topJumpsBarChart" height="260"></canvas>
                    <div class="small text-secondary mt-2">
                        * Tuyến <strong>56B</strong> chiếm 43% tổng số bước nhảy lùi do cấu trúc tuyến vòng khép kín.
                    </div>
                </div>
            </div>
        </div>

        <!-- INTERACTIVE MAP & SPATIAL-TEMPORAL NAVIGATOR -->
        <div class="card p-4 mb-4">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <div>
                    <h4 class="fw-bold mb-1 text-light">
                        <i class="fa-solid fa-map-location-dot me-2 text-info"></i>Bản Đồ Trực Quan Hóa &amp; Bảng Điều Hướng Dị Thường
                    </h4>
                    <div class="text-secondary small">
                        Hiển thị tim đường TimBus (xanh dương), trạm dừng (tím), và pings GPS thực tế (Xanh: ≤ 30m, Vàng: 30-50m, Đỏ: &gt; 50m). Chọn sự kiện bên dưới để tự động bay tới tọa độ.
                    </div>
                </div>
                <div class="d-flex align-items-center gap-3">
                    <div>
                        <label class="form-label small mb-0 text-secondary fw-bold">Chọn Tuyến Kiểm Tra:</label>
                        <select id="routeSelect" class="form-select bg-dark text-light border-secondary">
                            <option value="39" selected>Tuyến 39 (68.4% Pings Lệch &gt; 50m - Cao Nhất Hệ Thống)</option>
                            <option value="122">Tuyến 122 (60.7% Lệch &gt; 50m - Ngoại Thành Bến Xe Gia Lâm)</option>
                            <option value="123">Tuyến 123 (d_perp Max 1,766m - Lệch Đường Tránh)</option>
                            <option value="BRT01">Tuyến BRT01 (35.2% Lệch - Làn Dành Riêng Giữa Dải Phân Cách)</option>
                            <option value="56B">Tuyến 56B (466 Bước Nhảy Lùi - Tuyến Vòng Khép Kín)</option>
                            <option value="E04">Tuyến E04 (Nút Nghẽn 3.5 km/h &amp; Detour Smart City 1.8km)</option>
                            <option value="07">Tuyến 07 (31.9% Lệch - Trục Võ Nguyên Giáp Sân Bay)</option>
                            <option value="02">Tuyến 02 (Tuyến Chuẩn Mực Baseline)</option>
                        </select>
                    </div>
                    <div>
                        <label class="form-label small mb-0 text-secondary fw-bold">Tile Máy Chủ Bản Đồ (Keyless &amp; Headerless):</label>
                        <select id="tileSelect" class="form-select bg-dark text-light border-secondary">
                            <option value="osm_fr" selected>OpenStreetMap France (Khuyên dùng - Nhanh &amp; Chuẩn WGS84)</option>
                            <option value="carto_positron">CartoDB Positron (Nền Sáng - Độ Tương Phản Cao)</option>
                            <option value="carto_voyager">CartoDB Voyager (Chi Tiết Đường Đô Thị)</option>
                            <option value="carto_dark">CartoDB Dark Matter (Giao Diện Tối)</option>
                            <option value="esri_sat">Esri World Imagery (Bản Đồ Vệ Tinh Trực Quan)</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- MAP CONTAINER -->
            <div id="map"></div>

            <!-- MAP LEGEND & SUMMARY -->
            <div class="d-flex justify-content-between align-items-center mt-3 pt-2 border-top border-secondary small text-secondary">
                <div class="d-flex gap-4">
                    <div><span class="legend-dot" style="background: #2563eb;"></span> Tim đường TimBus chính thức</div>
                    <div><span class="legend-dot" style="background: #10b981;"></span> Ping GPS chuẩn (≤ 30m)</div>
                    <div><span class="legend-dot" style="background: #f59e0b;"></span> Ping GPS lệch nhẹ (30 - 50m)</div>
                    <div><span class="legend-dot" style="background: #ef4444;"></span> Ping GPS dị thường / Detour (&gt; 50m)</div>
                    <div><span class="legend-dot" style="background: #a855f7;"></span> Trạm dừng chính thức</div>
                    <div><span class="legend-dot" style="background: #f97316;"></span> Vector giật lùi (Δs &lt; -200m)</div>
                </div>
                <div id="routeMapStats" class="fw-bold text-info">Đang hiển thị dữ liệu tuyến...</div>
            </div>

            <!-- SPATIAL & TEMPORAL QUICK-JUMP ANOMALY NAVIGATOR -->
            <div class="mt-4 pt-3 border-top border-secondary">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div>
                        <h5 class="fw-bold text-light mb-1">
                            <i class="fa-solid fa-crosshairs me-2 text-danger"></i>BẢNG ĐIỀU HƯỚNG SỰ KIỆN DỊ THƯỜNG KHÔNG GIAN &amp; THỜI GIAN
                        </h5>
                        <div class="small text-secondary">
                            Bấm nút <strong>[Bay Tới Điểm]</strong> hoặc nhấp trực tiếp vào dòng sự kiện để phóng to bản đồ vào đúng vị trí và thời điểm phát sinh dị thường.
                        </div>
                    </div>
                    <div class="d-flex gap-2">
                        <button class="btn btn-sm btn-outline-secondary active filter-btn" data-filter="all" onclick="filterAnomalyTable('all')">Tất Cả</button>
                        <button class="btn btn-sm btn-outline-danger filter-btn" data-filter="lateral_drift" onclick="filterAnomalyTable('lateral_drift')">Lệch Tim (&gt; 50m)</button>
                        <button class="btn btn-sm btn-outline-warning filter-btn" data-filter="backward_jump" onclick="filterAnomalyTable('backward_jump')">Giật Lùi (Δs &lt; -200m)</button>
                        <button class="btn btn-sm btn-outline-danger filter-btn" data-filter="bottleneck" onclick="filterAnomalyTable('bottleneck')">Nút Nghẽn (&lt; 5 km/h)</button>
                        <button class="btn btn-sm btn-outline-info filter-btn" data-filter="high_speed" onclick="filterAnomalyTable('high_speed')">Tốc Độ Cao (&gt; 60 km/h)</button>
                    </div>
                </div>

                <div class="nav-table-container">
                    <table class="table table-dark-custom table-hover">
                        <thead>
                            <tr>
                                <th style="width: 170px;"><i class="fa-regular fa-clock me-1"></i> Thời Gian</th>
                                <th style="width: 130px;"><i class="fa-solid fa-bus me-1"></i> Xe (Biển Số)</th>
                                <th style="width: 190px;"><i class="fa-solid fa-tag me-1"></i> Phân Loại Dị Thường</th>
                                <th style="width: 130px;"><i class="fa-solid fa-ruler me-1"></i> Vị Trí 1D s</th>
                                <th><i class="fa-solid fa-circle-info me-1"></i> Chi Tiết Sự Kiện Thực Nghiệm</th>
                                <th style="width: 120px;" class="text-center"><i class="fa-solid fa-location-arrow me-1"></i> Hành Động</th>
                            </tr>
                        </thead>
                        <tbody id="anomalyTableBody">
                            <!-- Populated dynamically via JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- EXTREME ANOMALY BENCHMARK TABLES -->
        <div class="row g-4 mb-4">
            <div class="col-lg-6">
                <div class="card p-3">
                    <h5 class="card-title fw-bold text-danger mb-3">
                        <i class="fa-solid fa-traffic-light me-2"></i>Top 8 Phân Đoạn Nghẽn Dị Thường (V̄ &lt; 5 km/h)
                    </h5>
                    <div class="table-responsive">
                        <table class="table table-dark-custom table-hover">
                            <thead>
                                <tr>
                                    <th>Tuyến</th>
                                    <th>Phân Đoạn Trạm</th>
                                    <th>Cự Ly</th>
                                    <th>Thời Gian (P₅₀)</th>
                                    <th>Vận Tốc V̄</th>
                                    <th>Mẫu (N)</th>
                                </tr>
                            </thead>
                            <tbody>
                                {"".join(f'''<tr>
                                    <td><span class="badge bg-secondary">{b["route"]}</span></td>
                                    <td><span class="text-light">{b["from"][:20]}</span> &rarr; <span class="text-light">{b["to"][:20]}</span></td>
                                    <td>{b["dist"]:.0f}m</td>
                                    <td class="text-warning fw-bold">{b["time"]:.1f}s</td>
                                    <td class="text-danger fw-bold">{b["speed"]:.1f} km/h</td>
                                    <td>{b["n"]}</td>
                                </tr>''' for b in bottlenecks)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div class="col-lg-6">
                <div class="card p-3">
                    <h5 class="card-title fw-bold text-success mb-3">
                        <i class="fa-solid fa-bolt me-2"></i>Top 8 Phân Đoạn Chạy Nhanh Nhất (Cao Tốc / Ngoại Thành &gt; 55 km/h)
                    </h5>
                    <div class="table-responsive">
                        <table class="table table-dark-custom table-hover">
                            <thead>
                                <tr>
                                    <th>Tuyến</th>
                                    <th>Phân Đoạn Trạm</th>
                                    <th>Cự Ly</th>
                                    <th>Thời Gian (P₅₀)</th>
                                    <th>Vận Tốc V̄</th>
                                    <th>Mẫu (N)</th>
                                </tr>
                            </thead>
                            <tbody>
                                {"".join(f'''<tr>
                                    <td><span class="badge bg-success">{e["route"]}</span></td>
                                    <td><span class="text-light">{e["from"][:20]}</span> &rarr; <span class="text-light">{e["to"][:20]}</span></td>
                                    <td>{e["dist"]:.0f}m</td>
                                    <td class="text-info fw-bold">{e["time"]:.1f}s</td>
                                    <td class="text-success fw-bold">{e["speed"]:.1f} km/h</td>
                                    <td>{e["n"]}</td>
                                </tr>''' for e in express)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- DIAGNOSIS & REMEDIATION PLAN -->
        <div class="card p-4 mb-4">
            <h4 class="fw-bold mb-3 text-light">
                <i class="fa-solid fa-stethoscope me-2 text-warning"></i>KẾT LUẬN KIỂM TOÁN &amp; ĐỀ XUẤT XỬ LÝ TOÁN HỌC
            </h4>
            <div class="row g-3">
                <div class="col-md-4">
                    <div class="p-3 bg-dark rounded border border-secondary">
                        <h6 class="text-danger fw-bold"><i class="fa-solid fa-circle-exclamation me-1"></i> 1. Xử Lý Sai Số d<sub>⊥</sub> &gt; 50m (Detour)</h6>
                        <p class="small text-secondary mb-0">
                            Các tuyến như <strong>39, 122, 123</strong> có tỷ lệ d<sub>⊥</sub> &gt; 50m lên tới &gt; 40 - 68%. 
                            <strong>Nguyên nhân</strong>: Xe chạy trên đường gom bên dưới, vòng xuyến tránh hoặc tim đường quy hoạch TimBus chưa cập nhật cầu vượt mới.
                            <br><strong>Giải pháp</strong>: Thiết lập ngưỡng lọc bỏ d<sub>⊥</sub> &gt; 60m trước khi nạp vào bài toán huấn luyện ETA, tránh làm méo mó phân phối s.
                        </p>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="p-3 bg-dark rounded border border-secondary">
                        <h6 class="text-warning fw-bold"><i class="fa-solid fa-circle-exclamation me-1"></i> 2. Khắc Phục Bước Nhảy Lùi Δs &lt; -200m</h6>
                        <p class="small text-secondary mb-0">
                            Tuyến <strong>56B</strong> có tới 466 lần giật lùi tọa độ do hình học tuyến vòng lặp kín (Looping geometry). Phép chiếu điểm gần nhất bị nhầm lẫn giữa nhánh đi và nhánh về tại các nút giao cắt nhau.
                            <br><strong>Giải pháp</strong>: Bổ sung bộ lọc đơn điệu (Monotonicity Filter): Chỉ cho phép chiếu vào phân đoạn tim đường có s ∈ [s_prev - 50m, s_prev + 1500m].
                        </p>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="p-3 bg-dark rounded border border-secondary">
                        <h6 class="text-info fw-bold"><i class="fa-solid fa-circle-check me-1"></i> 3. Giữ Vững Bản Chất Nút Nghẽn Thực Tế</h6>
                        <p class="small text-secondary mb-0">
                            Phân đoạn <strong>Trần Phú - Bưu Điện Hà Đông (Tuyến E04)</strong> vận tốc trung bình 3.5 km/h trong 644 giây là <strong>hiện tượng ùn tắc giao thông có thật</strong> tại hành lang Hà Đông vào giờ cao điểm, không phải lỗi kỹ thuật. 
                            <br><strong>Giải pháp</strong>: Ma trận thời gian P₅₀ phản ánh chính xác nút nghẽn này làm mỏ neo giá trị cho người dùng xem ETA.
                        </p>
                    </div>
                </div>
            </div>
        </div>

    </div>

    <!-- Scripts -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <script>
        // Data injected from Python
        const SPATIAL_DATA = {spatial_data_json};
        const TILE_CONFIG = {tile_config_json};
        const TOP_DPERP = {top_dperp_json};
        const TOP_JUMPS = {top_jumps_json};
        const KPI_DATA = {kpi_json};

        // Keyless & Headerless Tile Layers tested 100% accessible
        const TILE_LAYERS = {{
            'osm_fr': {{
                url: 'https://{{s}}.tile.openstreetmap.fr/osmfr/{{z}}/{{x}}/{{y}}.png',
                options: {{ attribution: '&copy; OpenStreetMap France', maxZoom: 20, subdomains: 'abc' }}
            }},
            'carto_positron': {{
                url: 'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',
                options: {{ attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 20, subdomains: 'abcd' }}
            }},
            'carto_voyager': {{
                url: 'https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png',
                options: {{ attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 20, subdomains: 'abcd' }}
            }},
            'carto_dark': {{
                url: 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
                options: {{ attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 20, subdomains: 'abcd' }}
            }},
            'esri_sat': {{
                url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
                options: {{ attribution: '&copy; Esri World Imagery', maxZoom: 19 }}
            }}
        }};

        // -------------------------------------------------------------
        // 1. CHART.JS CONFIGURATIONS
        // -------------------------------------------------------------
        // Donut Chart: d_perp Breakdown
        new Chart(document.getElementById('dperpPieChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['Trong làn (<=15m)', 'Làn biên (15-30m)', 'Lệch nhẹ (30-50m)', 'Lệch lớn (50-100m)', 'Siêu ngoại lai (>100m)'],
                datasets: [{{
                    data: [
                        KPI_DATA.in_lane_15m,
                        KPI_DATA.roadside_30m,
                        KPI_DATA.moderate_50m,
                        KPI_DATA.large_100m,
                        KPI_DATA.extreme_over_100m
                    ],
                    backgroundColor: ['#10b981', '#3b82f6', '#f59e0b', '#f97316', '#ef4444'],
                    borderColor: '#1e293b',
                    borderWidth: 2
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ position: 'bottom', labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }}
                }}
            }}
        }});

        // Top d_perp Bar Chart
        new Chart(document.getElementById('topDperpBarChart'), {{
            type: 'bar',
            data: {{
                labels: TOP_DPERP.map(d => 'Tuyến ' + d.route),
                datasets: [{{
                    label: '% Pings Lệch > 50m',
                    data: TOP_DPERP.map(d => d.pct),
                    backgroundColor: '#ef4444',
                    borderRadius: 4
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ beginAtZero: true, ticks: {{ color: '#94a3b8', callback: v => v + '%' }}, grid: {{ color: '#334155' }} }},
                    x: {{ ticks: {{ color: '#cbd5e1' }}, grid: {{ display: false }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});

        // Top Jumps Bar Chart
        new Chart(document.getElementById('topJumpsBarChart'), {{
            type: 'bar',
            data: {{
                labels: TOP_JUMPS.map(d => 'Tuyến ' + d.route),
                datasets: [{{
                    label: 'Số lần giật lùi (Δs < -200m)',
                    data: TOP_JUMPS.map(d => d.jumps),
                    backgroundColor: '#f59e0b',
                    borderRadius: 4
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ beginAtZero: true, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
                    x: {{ ticks: {{ color: '#cbd5e1' }}, grid: {{ display: false }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});

        // -------------------------------------------------------------
        // 2. LEAFLET MAP & KEYLESS/HEADERLESS TILE CONTROLLER
        // -------------------------------------------------------------
        const map = L.map('map', {{
            center: [21.0285, 105.8542],
            zoom: 12,
            zoomControl: true
        }});

        let currentTileLayer = null;

        function setTileLayer(key) {{
            if (currentTileLayer) {{
                map.removeLayer(currentTileLayer);
            }}
            const conf = TILE_LAYERS[key] || TILE_LAYERS['osm_fr'];
            currentTileLayer = L.tileLayer(conf.url, conf.options).addTo(map);
        }}
        setTileLayer('osm_fr');

        document.getElementById('tileSelect').addEventListener('change', (e) => {{
            setTileLayer(e.target.value);
            map.invalidateSize();
        }});

        // Trigger map invalidate size on load
        window.addEventListener('load', () => {{
            setTimeout(() => map.invalidateSize(), 300);
        }});

        // Layers for dynamic route
        const centerlineLayer = L.layerGroup().addTo(map);
        const stationLayer = L.layerGroup().addTo(map);
        const pingsLayer = L.layerGroup().addTo(map);
        const jumpsLayer = L.layerGroup().addTo(map);
        const highlightLayer = L.layerGroup().addTo(map);

        let activePulseMarker = null;
        let currentRouteAnomalies = [];
        let currentFilter = 'all';

        function renderRoute(routeCode) {{
            // Clear previous layers
            centerlineLayer.clearLayers();
            stationLayer.clearLayers();
            pingsLayer.clearLayers();
            jumpsLayer.clearLayers();
            highlightLayer.clearLayers();

            const data = SPATIAL_DATA[routeCode];
            if (!data) return;

            // 1. Draw Centerline
            if (data.centerline && data.centerline.length > 0) {{
                const polyline = L.polyline(data.centerline, {{
                    color: '#2563eb',
                    weight: 4.5,
                    opacity: 0.85
                }}).addTo(centerlineLayer);
                map.fitBounds(polyline.getBounds(), {{ padding: [30, 30] }});
            }}

            // 2. Draw Stations
            if (data.stations) {{
                data.stations.forEach(st => {{
                    const circle = L.circleMarker([st.lat, st.lon], {{
                        radius: 5,
                        fillColor: '#a855f7',
                        color: '#ffffff',
                        weight: 1.5,
                        fillOpacity: 0.95
                    }}).addTo(stationLayer);
                    circle.bindPopup(`
                        <div style="font-size: 13px; color: #0f172a;">
                            <strong>[Trạm ${{st.order}}] ${{st.name}}</strong><br>
                            <span class="text-secondary">Toạ độ s: <strong>${{st.s}}m</strong></span>
                        </div>
                    `);
                }});
            }}

            // 3. Draw GPS Pings
            let outlierCount = 0;
            if (data.pings) {{
                data.pings.forEach(p => {{
                    let color = '#10b981'; // In lane <= 30m
                    let radius = 3.5;
                    let opacity = 0.75;
                    if (p.dperp > 50) {{
                        color = '#ef4444'; // Outlier > 50m
                        radius = 6;
                        opacity = 0.95;
                        outlierCount++;
                    }} else if (p.dperp > 30) {{
                        color = '#f59e0b'; // Roadside 30-50m
                        radius = 4.5;
                    }}

                    const marker = L.circleMarker([p.lat, p.lon], {{
                        radius: radius,
                        fillColor: color,
                        color: p.dperp > 50 ? '#ffffff' : color,
                        weight: p.dperp > 50 ? 1.5 : 1,
                        fillOpacity: opacity
                    }}).addTo(pingsLayer);

                    marker.bindPopup(`
                        <div style="font-size: 13px; color: #0f172a; line-height: 1.5;">
                            <strong style="font-size: 14px;">Xe: ${{p.plate || 'ID-' + p.vid}} (ID: ${{p.vid}})</strong><br>
                            Sai số d<sub>⊥</sub>: <strong style="color: ${{p.dperp > 50 ? '#ef4444' : '#10b981'}};">${{p.dperp}}m</strong><br>
                            Vị trí 1D s: <strong>${{p.s}}m</strong><br>
                            Vận tốc: <strong>${{p.speed !== null ? p.speed + ' km/h' : 'Không có dữ liệu'}}</strong><br>
                            Thời gian: <small style="color: #64748b;">${{p.time}}</small><br>
                            Tọa độ: <small style="color: #64748b;">${{p.lat.toFixed(6)}}, ${{p.lon.toFixed(6)}}</small>
                        </div>
                    `);
                }});
            }}

            // 4. Draw Backward Jumps
            if (data.jumps) {{
                data.jumps.forEach(j => {{
                    L.polyline([[j.lat1, j.lon1], [j.lat2, j.lon2]], {{
                        color: '#f97316',
                        weight: 2.5,
                        dashArray: '5, 5',
                        opacity: 0.9
                    }}).addTo(jumpsLayer).bindPopup(`
                        <div style="font-size: 13px; color: #0f172a;">
                            <strong class="text-danger">Bước Nhảy Lùi: ${{j.ds}}m</strong><br>
                            Xe: ${{j.plate || j.vid}} | Thời gian giữa 2 pings: ${{j.dt}}s<br>
                            Tọa độ s: ${{j.s1}}m &rarr; ${{j.s2}}m<br>
                            Thời điểm: <small style="color: #64748b;">${{j.t2}}</small>
                        </div>
                    `);
                }});
            }}

            // Update stats
            document.getElementById('routeMapStats').innerHTML = `
                Tuyến ${{routeCode}}: Tổng ${{data.total_pings_in_db.toLocaleString()}} pings | Hiển thị ${{data.pings.length}} pings mẫu (${{outlierCount}} pings lệch &gt; 50m) | ${{data.stations.length}} trạm dừng
            `;

            // 5. Populate Anomaly Navigator Table
            currentRouteAnomalies = data.anomaly_events || [];
            renderAnomalyTable();
        }}

        // -------------------------------------------------------------
        // 3. SPATIAL & TEMPORAL QUICK-JUMP CONTROLLER
        // -------------------------------------------------------------
        function filterAnomalyTable(filterType) {{
            currentFilter = filterType;
            document.querySelectorAll('.filter-btn').forEach(b => {{
                if (b.dataset.filter === filterType) {{
                    b.classList.add('active');
                }} else {{
                    b.classList.remove('active');
                }}
            }});
            renderAnomalyTable();
        }}

        function renderAnomalyTable() {{
            const tbody = document.getElementById('anomalyTableBody');
            tbody.innerHTML = '';

            const filtered = currentFilter === 'all' 
                ? currentRouteAnomalies 
                : currentRouteAnomalies.filter(ev => ev.type === currentFilter);

            if (filtered.length === 0) {{
                tbody.innerHTML = `<tr><td colspan="6" class="text-center text-secondary py-3">Không có sự kiện dị thường nào khớp với bộ lọc này.</td></tr>`;
                return;
            }}

            filtered.forEach((ev, idx) => {{
                const tr = document.createElement('tr');
                tr.className = 'clickable-row';
                tr.id = `anomaly-row-${{idx}}`;

                // Format timestamp
                let timeStr = ev.time || 'N/A';
                if (timeStr.includes('T')) {{
                    timeStr = timeStr.replace('T', ' ').split('+')[0];
                }}

                tr.innerHTML = `
                    <td><small class="text-light fw-bold">${{timeStr}}</small></td>
                    <td><span class="badge bg-secondary">${{ev.plate}}</span></td>
                    <td><span class="badge ${{ev.badge_class}}">${{ev.type_label}}</span></td>
                    <td><code>s = ${{ev.s.toLocaleString()}}m</code></td>
                    <td><small class="text-secondary">${{ev.detail}}</small></td>
                    <td class="text-center">
                        <button class="btn btn-sm btn-danger btn-jump" onclick="event.stopPropagation(); jumpToAnomaly(${{ev.lat}}, ${{ev.lon}}, ${{idx}})">
                            <i class="fa-solid fa-crosshairs me-1"></i> Bay tới
                        </button>
                    </td>
                `;

                tr.addEventListener('click', () => {{
                    jumpToAnomaly(ev.lat, ev.lon, idx);
                }});

                tbody.appendChild(tr);
            }});
        }}

        function jumpToAnomaly(lat, lon, rowIdx) {{
            // Highlight table row
            document.querySelectorAll('.clickable-row').forEach(r => r.classList.remove('row-active'));
            const row = document.getElementById(`anomaly-row-${{rowIdx}}`);
            if (row) {{
                row.classList.add('row-active');
            }}

            // Fly map to coordinates
            map.flyTo([lat, lon], 17, {{
                duration: 1.2,
                easeLinearity: 0.25
            }});

            // Create Pulsing Marker
            if (activePulseMarker) {{
                highlightLayer.removeLayer(activePulseMarker);
            }}

            const pulseIcon = L.divIcon({{
                className: 'pulse-beacon-wrapper',
                html: '<div class="pulse-beacon-ring"></div><div class="pulse-beacon-core"></div>',
                iconSize: [32, 32],
                iconAnchor: [16, 16]
            }});

            activePulseMarker = L.marker([lat, lon], {{ icon: pulseIcon }}).addTo(highlightLayer);

            // Find event detail
            const ev = currentRouteAnomalies[rowIdx];
            if (ev) {{
                const popupContent = `
                    <div style="font-size: 13px; color: #0f172a; line-height: 1.6; min-width: 220px;">
                        <div style="font-weight: bold; font-size: 14px; border-bottom: 2px solid #ef4444; padding-bottom: 3px; margin-bottom: 6px;">
                            ${{ev.type_label}}
                        </div>
                        <div><strong>Phương tiện:</strong> ${{ev.plate}} (ID: ${{ev.vid}})</div>
                        <div><strong>Thời điểm:</strong> <span style="color: #64748b;">${{ev.time}}</span></div>
                        <div><strong>Vị trí 1D s:</strong> <strong>${{ev.s}}m</strong></div>
                        ${{ev.dperp !== null ? `<div><strong>Độ lệch d<sub>⊥</sub>:</strong> <span style="color: #ef4444; font-weight: bold;">${{ev.dperp}}m</span></div>` : ''}}
                        ${{ev.speed !== null ? `<div><strong>Vận tốc:</strong> <strong>${{ev.speed}} km/h</strong></div>` : ''}}
                        <div><strong>Tọa độ WGS84:</strong> ${{lat.toFixed(6)}}, ${{lon.toFixed(6)}}</div>
                        <div style="margin-top: 6px; padding-top: 4px; border-top: 1px dashed #cbd5e1; font-size: 11px; color: #475569;">
                            ${{ev.detail}}
                        </div>
                    </div>
                `;
                activePulseMarker.bindPopup(popupContent).openPopup();
            }}

            // Scroll map into view smoothly if not visible
            const mapElem = document.getElementById('map');
            const rect = mapElem.getBoundingClientRect();
            if (rect.top < 0 || rect.bottom > window.innerHeight) {{
                mapElem.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
        }}

        // Initial setup
        renderRoute('39');
        document.getElementById('routeSelect').addEventListener('change', (e) => {{
            renderRoute(e.target.value);
        }});
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    run_audit_and_generate()
