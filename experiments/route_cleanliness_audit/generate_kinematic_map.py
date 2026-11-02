"""
Interactive Spatial-Kinematic Audit Visualizer (Production Version):
- 100% Complete Point Cloud (Zero Sampling Loss) rendered via Leaflet HTML5 Canvas
- Colors strictly represent 5 Cross-Track Error Tiers (d_perp):
  * <= 10m: Green (#10b981) - Làn Chuẩn
  * 10 - 20m: Lime (#84cc16) - Lệch Nhẹ / Tấp Lề
  * 20 - 35m: Yellow (#eab308) - Hành Lang Mở Rộng
  * 35 - 75m: Orange (#f97316) - Đường Gom / Lệch Vừa
  * > 75m: Red (#ef4444) - Bãi Đỗ / Gara / Ngoài Tuyến
- Independent Operational State Layers (Toggleable):
  * Xe Đang Chạy (RUNNING)
  * Xe Đang Dừng Bến / Đèn Đỏ (DWELL)
  * Xe Đỗ Bến / Bãi / Gara (DEPOT)
- Full Basemap Integration:
  * Esri World Imagery (Satellite) - Crystal-clear aerial photography of roads and depots
  * OpenStreetMap France (Sáng & Tối) - High fidelity, keyless, zero watermarks
  * OpenStreetMap Standard
- Strictly relies on device_epoch timeline.
Outputs: reports/kinematic_running_audit_map.html
"""

import os
import sys
import json
import sqlite3
import math
from pathlib import Path
from collections import defaultdict

# Root path setup
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.system_config import OSM_TILE_SERVERS

DB_PATH = Path("data/hanoi_bus_system.db")
OUTPUT_HTML = Path("reports/kinematic_running_audit_map.html")

FEATURED_ROUTES = [
    "19", "22A", "02", "E06", "21A", "34", "32", "BRT01", "99", "105", "E04", "39"
]

def classify_pings_for_route(rows):
    """
    rows: [(ping_id, veh, epoch, t_str, direction, lat, lon, s, d_perp, speed, is_dwell)]
    Sorted strictly by vehicle_id, device_epoch.
    Returns: list of compact tuples [lat, lon, d_perp, speed, s, state_code, veh, time_str, direction]
    state_code: 0 = RUNNING, 1 = DWELL, 2 = DEPOT
    """
    veh_pings = defaultdict(list)
    for r in rows:
        veh_pings[r[1]].append(r)

    compact_points = []

    for vid, p_list in veh_pings.items():
        n = len(p_list)
        for i in range(n):
            pid, veh, epoch, t_str, direction, lat, lon, s, d_perp, speed, is_dwell = p_list[i]

            # 3-minute rolling displacement based strictly on device_epoch
            w_s = []
            for j in range(max(0, i - 6), min(n, i + 7)):
                if abs(p_list[j][2] - epoch) <= 90:
                    w_s.append(p_list[j][7])

            s_span = (max(w_s) - min(w_s)) if w_s else 0.0
            spd = speed if speed is not None else 0.0

            # 1. DEPOT / GARA / OFF-ROUTE
            # Either far outside corridor (> 45m) or stationary off-duty
            if d_perp > 45.0:
                st_code = 2 # DEPOT
            # 2. IN-CORRIDOR DWELL (stopping at station, waiting at red light, passenger boarding)
            elif (s_span < 25.0 and len(w_s) >= 2) or (spd < 4.0 and is_dwell == 1):
                st_code = 1 # DWELL
            # 3. IN-CORRIDOR ACTIVE RUNNING
            else:
                st_code = 0 # RUNNING

            # Compact tuple to save memory and file size:
            # [lat, lon, d_perp, speed, s, st_code, veh, time_str, dir_str]
            compact_points.append([
                round(lat, 6),
                round(lon, 6),
                round(d_perp, 1),
                round(spd, 1),
                round(s, 1),
                st_code,
                str(veh),
                t_str[11:19] if len(t_str) >= 19 else t_str,
                direction
            ])

    return compact_points


def build_payload(conn):
    cur = conn.cursor()
    payload = {}

    for rc in FEATURED_ROUTES:
        cur.execute("SELECT route_id, route_name FROM canonical_route_master WHERE route_code = ?", (rc,))
        r_row = cur.fetchone()
        if not r_row:
            continue
        route_id, route_name = r_row

        # Canonical shape
        cur.execute("""
            SELECT direction, point_order, lat, lon, cum_distance_m
            FROM canonical_shape_master
            WHERE route_id = ?
            ORDER BY direction, point_order;
        """, (route_id,))
        shapes = {"go": [], "re": []}
        for d, seq, lat, lng, s in cur.fetchall():
            if d in shapes:
                shapes[d].append([lat, lng, round(s, 1)])

        # Canonical stations
        cur.execute("""
            SELECT direction, station_order, station_id, station_name, lat, lon, cum_distance_m, snap_dist_m
            FROM canonical_station_master
            WHERE route_id = ?
            ORDER BY direction, station_order;
        """, (route_id,))
        stations = {"go": [], "re": []}
        for d, ord_idx, s_id, s_name, lat, lng, s, d_perp in cur.fetchall():
            if d in stations:
                stations[d].append({
                    "id": s_id,
                    "ord": ord_idx,
                    "name": s_name,
                    "lat": lat,
                    "lon": lng,
                    "s": round(s, 1),
                    "dp": round(d_perp, 1)
                })

        # Telemetry pings sorted strictly by vehicle_id and device_epoch
        cur.execute("""
            SELECT ping_id, vehicle_id, device_epoch, device_update_time, direction, lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, is_dwell
            FROM route_projected_telemetry
            WHERE route_id = ?
            ORDER BY vehicle_id, device_epoch;
        """, (route_id,))
        p_rows = cur.fetchall()

        # Classify all points
        all_points = classify_pings_for_route(p_rows)

        # Metrics
        total_p = len(all_points)
        run_cnt = sum(1 for p in all_points if p[5] == 0)
        dwell_cnt = sum(1 for p in all_points if p[5] == 1)
        depot_cnt = sum(1 for p in all_points if p[5] == 2)

        # Deviation breakdown
        c_le10 = sum(1 for p in all_points if p[2] <= 10.0)
        c_10_20 = sum(1 for p in all_points if 10.0 < p[2] <= 20.0)
        c_20_35 = sum(1 for p in all_points if 20.0 < p[2] <= 35.0)
        c_35_75 = sum(1 for p in all_points if 35.0 < p[2] <= 75.0)
        c_gt75 = sum(1 for p in all_points if p[2] > 75.0)

        in_35_pct = ((c_le10 + c_10_20 + c_20_35) / total_p * 100.0) if total_p else 0.0

        all_dps = sorted([p[2] for p in all_points])
        med_all = all_dps[total_p // 2] if total_p else 0.0

        run_dps = sorted([p[2] for p in all_points if p[5] == 0])
        med_run = run_dps[len(run_dps) // 2] if run_dps else 0.0

        tier = "GOLD" if (in_35_pct >= 88.0 and med_run <= 10.0) else ("SILVER" if in_35_pct >= 75.0 else "BRONZE")

        payload[rc] = {
            "name": route_name,
            "tier": tier,
            "metrics": {
                "total_pings": total_p,
                "in_lane_pct": round(in_35_pct, 1),
                "med_dp": round(med_all, 1),
                "med_run_dp": round(med_run, 1),
                "run_cnt": run_cnt,
                "dwell_cnt": dwell_cnt,
                "depot_cnt": depot_cnt,
                "tiers": {
                    "le10": c_le10,
                    "t10_20": c_10_20,
                    "t20_35": c_20_35,
                    "t35_75": c_35_75,
                    "gt75": c_gt75
                }
            },
            "shapes": shapes,
            "stations": stations,
            "points": all_points  # 100% of all points!
        }

    return payload


HTML_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>Bản Đồ Kiểm Toán Động Học Thực Địa - Phân Mức Sai Số 5 Tầng & Lớp Trạng Thái</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg-dark: #0f172a;
      --card-bg: rgba(15, 23, 42, 0.94);
      --border-color: rgba(255, 255, 255, 0.14);
      /* 5-Tier Deviation Palette */
      --c-tier1: #10b981; /* <=10m: Emerald */
      --c-tier2: #84cc16; /* 10-20m: Lime */
      --c-tier3: #eab308; /* 20-35m: Yellow */
      --c-tier4: #f97316; /* 35-75m: Orange */
      --c-tier5: #ef4444; /* >75m: Crimson Red */
      --color-centerline: #06b6d4;
      --color-station: #facc15;
    }
    body, html {
      margin: 0; padding: 0; height: 100%; width: 100%;
      font-family: 'Inter', sans-serif; background: #0f172a; color: #f8fafc;
      overflow: hidden;
    }
    #map { height: 100vh; width: 100vw; z-index: 1; }
    
    /* Zero-Watermark Custom Dark Mode for OSM France */
    .dark-map-tiles .leaflet-tile-pane {
      filter: brightness(0.65) invert(1) contrast(3.0) hue-rotate(200deg) saturate(0.28) brightness(0.75);
    }

    .hud-panel {
      position: absolute; top: 16px; left: 16px; z-index: 1000;
      width: 440px; max-height: calc(100vh - 32px); overflow-y: auto;
      background: var(--card-bg); backdrop-filter: blur(14px);
      border: 1px solid var(--border-color); border-radius: 14px;
      padding: 18px; box-shadow: 0 20px 40px rgba(0,0,0,0.65);
    }
    .hud-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .badge-tier { font-size: 0.8rem; font-weight: 700; padding: 4px 10px; border-radius: 6px; }
    .badge-gold { background: #eab308; color: #000; }
    .badge-silver { background: #94a3b8; color: #000; }
    .badge-bronze { background: #b45309; color: #fff; }

    .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 12px 0; }
    .stat-box { background: rgba(15, 23, 42, 0.75); border: 1px solid var(--border-color); border-radius: 8px; padding: 9px 11px; }
    .stat-box .title { font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
    .stat-box .val { font-size: 1.15rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
    
    .section-title { font-size: 0.74rem; font-weight: 700; color: #38bdf8; text-transform: uppercase; letter-spacing: 0.6px; margin: 12px 0 6px 0; }

    .legend-item { display: flex; align-items: center; justify-content: space-between; padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; background: rgba(15, 23, 42, 0.5); margin-bottom: 3px; }
    .legend-bullet { width: 12px; height: 12px; border-radius: 50%; display: inline-block; margin-right: 8px; }

    .layer-item {
      display: flex; align-items: center; justify-content: space-between;
      padding: 8px 10px; margin-bottom: 6px; border-radius: 8px;
      background: rgba(15, 23, 42, 0.55); border: 1px solid var(--border-color);
      cursor: pointer; transition: all 0.2s;
    }
    .layer-item:hover { background: rgba(30, 41, 59, 0.85); }
    .layer-icon { width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; margin-right: 8px; font-size: 0.75rem; }

    .leaflet-popup-content-wrapper {
      background: #1e293b !important; color: #f8fafc !important;
      border: 1px solid rgba(255,255,255,0.18); border-radius: 8px;
      font-family: 'Inter', sans-serif;
    }
    .leaflet-popup-tip { background: #1e293b !important; }
  </style>
</head>
<body>
  <div id="map"></div>

  <div class="hud-panel">
    <div class="hud-header">
      <div>
        <h5 class="mb-0 fw-bold" style="letter-spacing: -0.5px;"><i class="fa-solid fa-map-location-dot text-info me-2"></i>Bản Đồ Kiểm Toán Động Học</h5>
        <small class="text-secondary">Trục Thời Gian Thiết Bị (Device Epoch)</small>
      </div>
      <span id="tierBadge" class="badge-tier badge-gold">GOLD</span>
    </div>

    <!-- Route selector -->
    <div class="mb-2">
      <label class="form-label text-secondary small mb-1 fw-semibold">CHỌN TUYẾN KIỂM TRA</label>
      <select id="routeSelect" class="form-select bg-dark text-white border-secondary">
      </select>
    </div>

    <!-- Direction & Basemap Filter -->
    <div class="row g-2 mb-2">
      <div class="col-6">
        <label class="form-label text-secondary small mb-1 fw-semibold">CHIỀU VẬN HÀNH</label>
        <div class="btn-group w-100" role="group">
          <input type="radio" class="btn-check" name="dirRadio" id="dirBoth" value="both" checked>
          <label class="btn btn-outline-secondary btn-sm" for="dirBoth">Cả 2</label>
          <input type="radio" class="btn-check" name="dirRadio" id="dirGo" value="go">
          <label class="btn btn-outline-secondary btn-sm" for="dirGo">Đi</label>
          <input type="radio" class="btn-check" name="dirRadio" id="dirRe" value="re">
          <label class="btn btn-outline-secondary btn-sm" for="dirRe">Về</label>
        </div>
      </div>
      <div class="col-6">
        <label class="form-label text-secondary small mb-1 fw-semibold">BẢN ĐỒ NỀN (BASEMAP)</label>
        <select id="basemapSelect" class="form-select form-select-sm bg-dark text-white border-secondary">
          <option value="esri_sat" selected>🛰️ Esri Vệ Tinh (Satellite)</option>
          <option value="osm_fr">🗺️ OSM France (Sáng)</option>
          <option value="osm_fr_dark">🌙 OSM France (Nền Tối)</option>
          <option value="osm_std">🌐 OSM Tiêu Chuẩn</option>
        </select>
      </div>
    </div>

    <!-- 1. MÀU SẮC CHỈ MỨC ĐỘ LỆCH (5 TẦNG) -->
    <div class="section-title"><i class="fa-solid fa-palette me-1"></i>QUY ƯỚC MÀU SẮC: ĐỘ LỆCH TIM ĐƯỜNG (d_perp)</div>
    <div class="p-2 rounded bg-dark border border-secondary mb-2">
      <div class="legend-item">
        <div class="d-flex align-items-center">
          <span class="legend-bullet" style="background: var(--c-tier1);"></span>
          <span><b>&le; 10 mét</b> (Chuẩn Làn Buýt)</span>
        </div>
        <span id="cntTier1" class="text-secondary font-monospace">--</span>
      </div>
      <div class="legend-item">
        <div class="d-flex align-items-center">
          <span class="legend-bullet" style="background: var(--c-tier2);"></span>
          <span><b>10 - 20 mét</b> (Làn Cận / Tấp Lề)</span>
        </div>
        <span id="cntTier2" class="text-secondary font-monospace">--</span>
      </div>
      <div class="legend-item">
        <div class="d-flex align-items-center">
          <span class="legend-bullet" style="background: var(--c-tier3);"></span>
          <span><b>20 - 35 mét</b> (Hành Lang Mở Rộng)</span>
        </div>
        <span id="cntTier3" class="text-secondary font-monospace">--</span>
      </div>
      <div class="legend-item">
        <div class="d-flex align-items-center">
          <span class="legend-bullet" style="background: var(--c-tier4);"></span>
          <span><b>35 - 75 mét</b> (Lệch Vừa / Đường Gom)</span>
        </div>
        <span id="cntTier4" class="text-secondary font-monospace">--</span>
      </div>
      <div class="legend-item">
        <div class="d-flex align-items-center">
          <span class="legend-bullet" style="background: var(--c-tier5);"></span>
          <span><b>&gt; 75 mét</b> (Bãi Đỗ / Gara / Ngoài Tuyến)</span>
        </div>
        <span id="cntTier5" class="text-secondary font-monospace">--</span>
      </div>
    </div>

    <!-- 2. LAYER BẬT/TẮT TRẠNG THÁI VẬN HÀNH -->
    <div class="section-title"><i class="fa-solid fa-layer-group me-1"></i>LỚP TRẠNG THÁI VẬN HÀNH (LAYER TOGGLE)</div>

    <div class="layer-item" onclick="toggleLayer('centerline')">
      <div class="d-flex align-items-center">
        <span class="layer-icon" style="background: rgba(6,182,212,0.2); color: #06b6d4;"><i class="fa-solid fa-road"></i></span>
        <span class="small fw-semibold">Tim Đường Master (BusMap)</span>
      </div>
      <input class="form-check-input ms-2" type="checkbox" id="chkCenterline" checked>
    </div>

    <div class="layer-item" onclick="toggleLayer('stations')">
      <div class="d-flex align-items-center">
        <span class="layer-icon" style="background: rgba(250,204,21,0.2); color: #facc15;"><i class="fa-solid fa-location-dot"></i></span>
        <span class="small fw-semibold">Trạm dừng chính thức</span>
      </div>
      <input class="form-check-input ms-2" type="checkbox" id="chkStations" checked>
    </div>

    <div class="layer-item" onclick="toggleLayer('running')">
      <div class="d-flex align-items-center">
        <span class="layer-icon" style="background: rgba(16,185,129,0.2); color: #10b981;"><i class="fa-solid fa-bus"></i></span>
        <div>
          <span class="small fw-semibold">Xe Đang Chạy (Running)</span><br>
          <small class="text-secondary" style="font-size: 0.68rem;" id="subRunningCnt">Di chuyển (v &ge; 5km/h hoặc &Delta;s &ge; 25m)</small>
        </div>
      </div>
      <input class="form-check-input ms-2" type="checkbox" id="chkRunning" checked>
    </div>

    <div class="layer-item" onclick="toggleLayer('dwell')">
      <div class="d-flex align-items-center">
        <span class="layer-icon" style="background: rgba(234,179,8,0.2); color: #eab308;"><i class="fa-solid fa-pause"></i></span>
        <div>
          <span class="small fw-semibold">Xe Đang Dừng (Dwell / Đón Trả Khách)</span><br>
          <small class="text-secondary" style="font-size: 0.68rem;" id="subDwellCnt">Dừng đón trả khách hoặc dừng đèn đỏ</small>
        </div>
      </div>
      <input class="form-check-input ms-2" type="checkbox" id="chkDwell" checked>
    </div>

    <div class="layer-item" onclick="toggleLayer('depot')">
      <div class="d-flex align-items-center">
        <span class="layer-icon" style="background: rgba(239,68,68,0.2); color: #ef4444;"><i class="fa-solid fa-warehouse"></i></span>
        <div>
          <span class="small fw-semibold">Xe Đỗ Bến / Bãi / Gara (Depot)</span><br>
          <small class="text-secondary" style="font-size: 0.68rem;" id="subDepotCnt">Nằm tại bãi xe/gara cách xa tuyến</small>
        </div>
      </div>
      <input class="form-check-input ms-2" type="checkbox" id="chkDepot" checked>
    </div>

    <!-- Summary Box -->
    <div class="stat-grid mt-2">
      <div class="stat-box" style="border-left: 3px solid #10b981;">
        <div class="title">Bám Làn (&le; 35m)</div>
        <div id="statAdherence" class="val text-success">--%</div>
      </div>
      <div class="stat-box" style="border-left: 3px solid #06b6d4;">
        <div class="title">Tổng Pings (100% dữ liệu)</div>
        <div id="statTotalPings" class="val text-info">--</div>
      </div>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const DATA = __DATA_PLACEHOLDER__;

    // Fast HTML5 Canvas renderer to handle tens of thousands of points smoothly
    const map = L.map('map', {
      preferCanvas: true,
      zoomControl: false,
      attributionControl: false
    }).setView([21.0285, 105.8542], 12);

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // 5-Tier Color Scale strictly based on d_perp
    function getColorByDeviation(dp) {
      if (dp <= 10.0) return '#10b981'; // Tier 1: Emerald
      if (dp <= 20.0) return '#84cc16'; // Tier 2: Lime
      if (dp <= 35.0) return '#eab308'; // Tier 3: Yellow
      if (dp <= 75.0) return '#f97316'; // Tier 4: Orange
      return '#ef4444';                 // Tier 5: Crimson Red
    }

    // Basemaps with official Esri Satellite and OSM France (Headerless & Keyless)
    const BASEMAPS = {
      esri_sat: {
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        options: { maxZoom: 19, attribution: '&copy; Esri, Maxar, Earthstar Geographics' },
        dark: false
      },
      osm_fr: {
        url: 'https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png',
        options: { subdomains: 'abc', maxZoom: 20, attribution: '&copy; OpenStreetMap France' },
        dark: false
      },
      osm_fr_dark: {
        url: 'https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png',
        options: { subdomains: 'abc', maxZoom: 20, attribution: '&copy; OpenStreetMap France' },
        dark: true
      },
      osm_std: {
        url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        options: { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' },
        dark: false
      }
    };

    let curBasemapKey = 'esri_sat';
    let baseLayer = L.tileLayer(BASEMAPS[curBasemapKey].url, BASEMAPS[curBasemapKey].options).addTo(map);

    document.getElementById('basemapSelect').addEventListener('change', (e) => {
      const mode = e.target.value;
      const cfg = BASEMAPS[mode];
      if (!cfg) return;

      if (cfg.dark) {
        document.body.classList.add('dark-map-tiles');
      } else {
        document.body.classList.remove('dark-map-tiles');
      }

      map.removeLayer(baseLayer);
      baseLayer = L.tileLayer(cfg.url, cfg.options).addTo(map);
      baseLayer.bringToBack();
    });

    // Layer Groups
    const centerlineGroup = L.layerGroup().addTo(map);
    const stationGroup = L.layerGroup().addTo(map);
    const telemetryCanvasGroup = L.layerGroup().addTo(map);

    const layerToggles = {
      centerline: true,
      stations: true,
      running: true,
      dwell: true,
      depot: true
    };

    function toggleLayer(name) {
      layerToggles[name] = !layerToggles[name];
      document.getElementById('chk' + name.charAt(0).toUpperCase() + name.slice(1)).checked = layerToggles[name];
      renderCurrentRoute();
    }

    // Populate route selector
    const sel = document.getElementById('routeSelect');
    Object.keys(DATA).forEach(rc => {
      const opt = document.createElement('option');
      opt.value = rc;
      opt.textContent = `Tuyến ${rc} [${DATA[rc].tier}] - ${DATA[rc].name}`;
      sel.appendChild(opt);
    });

    let currentRouteCode = "19";
    sel.value = currentRouteCode;

    sel.addEventListener('change', (e) => {
      currentRouteCode = e.target.value;
      renderCurrentRoute(true);
    });

    document.querySelectorAll('input[name="dirRadio"]').forEach(r => {
      r.addEventListener('change', () => renderCurrentRoute(false));
    });

    ['chkCenterline', 'chkStations', 'chkRunning', 'chkDwell', 'chkDepot'].forEach(id => {
      document.getElementById(id).addEventListener('change', (e) => {
        const key = id.replace('chk', '').toLowerCase();
        layerToggles[key] = e.target.checked;
        renderCurrentRoute(false);
      });
    });

    function renderCurrentRoute(fitBounds = false) {
      const rData = DATA[currentRouteCode];
      if (!rData) return;

      // Update badge & stats
      const badge = document.getElementById('tierBadge');
      badge.className = `badge-tier badge-${rData.tier.toLowerCase()}`;
      badge.textContent = rData.tier;

      document.getElementById('statAdherence').textContent = `${rData.metrics.in_lane_pct}%`;
      document.getElementById('statTotalPings').textContent = rData.metrics.total_pings.toLocaleString();

      // Counts per tier
      const t = rData.metrics.tiers;
      document.getElementById('cntTier1').textContent = `${t.le10.toLocaleString()} (${(t.le10/rData.metrics.total_pings*100).toFixed(1)}%)`;
      document.getElementById('cntTier2').textContent = `${t.t10_20.toLocaleString()} (${(t.t10_20/rData.metrics.total_pings*100).toFixed(1)}%)`;
      document.getElementById('cntTier3').textContent = `${t.t20_35.toLocaleString()} (${(t.t20_35/rData.metrics.total_pings*100).toFixed(1)}%)`;
      document.getElementById('cntTier4').textContent = `${t.t35_75.toLocaleString()} (${(t.t35_75/rData.metrics.total_pings*100).toFixed(1)}%)`;
      document.getElementById('cntTier5').textContent = `${t.gt75.toLocaleString()} (${(t.gt75/rData.metrics.total_pings*100).toFixed(1)}%)`;

      // Layer subtitle counts
      document.getElementById('subRunningCnt').textContent = `${rData.metrics.run_cnt.toLocaleString()} pings đang di chuyển`;
      document.getElementById('subDwellCnt').textContent = `${rData.metrics.dwell_cnt.toLocaleString()} pings dừng đón khách/đèn đỏ`;
      document.getElementById('subDepotCnt').textContent = `${rData.metrics.depot_cnt.toLocaleString()} pings đỗ bãi/gara`;

      // Clear layers
      centerlineGroup.clearLayers();
      stationGroup.clearLayers();
      telemetryCanvasGroup.clearLayers();

      const dir = document.querySelector('input[name="dirRadio"]:checked').value;
      const bounds = L.latLngBounds();

      // 1. Centerlines
      if (layerToggles.centerline) {
        ['go', 're'].forEach(d => {
          if (dir === 'both' || dir === d) {
            const pts = rData.shapes[d];
            if (pts && pts.length > 0) {
              const latlngs = pts.map(p => [p[0], p[1]]);
              const color = (d === 'go') ? '#06b6d4' : '#818cf8';
              const pl = L.polyline(latlngs, {
                color: color,
                weight: 4,
                opacity: 0.85
              }).bindTooltip(`Tuyến ${currentRouteCode} (${d.toUpperCase()}) - ${pts.length} điểm`);
              centerlineGroup.addLayer(pl);
              latlngs.forEach(ll => bounds.extend(ll));
            }
          }
        });
      }

      // 2. Stations
      if (layerToggles.stations) {
        ['go', 're'].forEach(d => {
          if (dir === 'both' || dir === d) {
            const sts = rData.stations[d];
            if (sts) {
              sts.forEach(s => {
                const marker = L.circleMarker([s.lat, s.lon], {
                  radius: 4,
                  fillColor: '#facc15',
                  color: '#000',
                  weight: 1,
                  fillOpacity: 0.95
                }).bindPopup(`<b>Trạm [${s.ord}]: ${s.name}</b><br>ID: ${s.id} | s: ${s.s}m | d_perp: ${s.dp}m`);
                stationGroup.addLayer(marker);
              });
            }
          }
        });
      }

      // 3. Telemetry Pings (100% Data on Canvas)
      // Point format: [lat, lon, d_perp, speed, s, st_code, veh, time_str, dir_str]
      const stateLabels = ["XE ĐANG CHẠY (RUNNING)", "XE ĐANG DỪNG (DWELL)", "XE ĐỖ BÃI / GARA (DEPOT)"];

      rData.points.forEach(p => {
        const [lat, lon, dp, spd, s, st_code, veh, t_str, p_dir] = p;

        if (dir !== 'both' && dir !== p_dir) return;

        // Check Layer Toggle:
        if (st_code === 0 && !layerToggles.running) return;
        if (st_code === 1 && !layerToggles.dwell) return;
        if (st_code === 2 && !layerToggles.depot) return;

        // Color is STRICTLY determined by deviation dp:
        const color = getColorByDeviation(dp);

        const m = L.circleMarker([lat, lon], {
          radius: 3,
          fillColor: color,
          color: color,
          weight: 0.5,
          fillOpacity: 0.8
        }).bindPopup(`
          <div style="font-size: 0.82rem; line-height: 1.4;">
            <b style="color: ${color};">${stateLabels[st_code]}</b><br>
            <b>Xe:</b> ${veh} | <b>Thời gian:</b> ${t_str}<br>
            <b>Độ lệch d_perp:</b> <b style="color: ${color}; font-size: 0.95rem;">${dp}m</b><br>
            <b>Vận tốc:</b> ${spd} km/h | <b>Vị trí s:</b> ${s}m
          </div>
        `);
        telemetryCanvasGroup.addLayer(m);
      });

      if (fitBounds && bounds.isValid()) {
        map.fitBounds(bounds, { padding: [50, 50] });
      }
    }

    // Initial render
    renderCurrentRoute(true);
  </script>
</body>
</html>
"""

def main():
    print("Building Production Kinematic Map Visualizer with Esri & OSM France...")
    conn = sqlite3.connect(DB_PATH)
    payload = build_payload(conn)
    conn.close()

    payload_json = json.dumps(payload, ensure_ascii=False)
    html_content = HTML_PAGE.replace("__DATA_PLACEHOLDER__", payload_json)

    os.makedirs(OUTPUT_HTML.parent, exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

    size_mb = os.path.getsize(OUTPUT_HTML) / (1024 * 1024)
    print(f"Generated {OUTPUT_HTML} ({size_mb:.2f} MB) with 100% points across {len(payload)} routes.")

if __name__ == "__main__":
    main()
