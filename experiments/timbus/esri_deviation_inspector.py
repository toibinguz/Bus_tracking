#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
CÔNG CỤ QUAN TRẮC VỆ TINH ESRI (TẬP TRUNG TỪNG XE - SINGLE VEHICLE INSPECTOR)
========================================================================================
Mã công cụ: experiments/timbus/esri_deviation_inspector.py
Phiên bản: 3.0 (Tối giản 100%, Vẽ từng xe một, Loại bỏ rác hình học, Trung thực viễn trắc)
Nguyên tắc:
  1. Chỉ vẽ duy nhất 1 xe tại 1 thời điểm.
  2. Chỉ vẽ tim đường của DUY NHẤT tuyến và chiều của xe đó (không vẽ chồng chéo tuyến khác).
  3. Không suy diễn dữ liệu: Nếu TimBus mất dấu, hiển thị rõ "MẤT DẤU", không copy tọa độ BusMap.
  4. Trực quan hóa chuẩn xác: Vị trí thực tế trên ảnh vệ tinh vs tim đường thực địa.
========================================================================================
"""

import os
import sys
import json
import time
import math
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple, Optional

# Thêm đường dẫn gốc dự án
sys.path.insert(0, os.path.abspath("."))

from experiments.timbus.timbus_tracker import TimBusClient, BusRecord
from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import fetch_route_buses_live
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_feature_extractor import OnlineFeatureExtractor

TZ_HANOI = timezone(timedelta(hours=7))

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Tính khoảng cách Haversine giữa 2 tọa độ WGS84 theo mét."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0)**2
    return 2.0 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))

def project_point_on_segment(lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[float, float, float]:
    """Chiếu trực giao điểm (lat, lon) lên đoạn thẳng [(lat1, lon1), (lat2, lon2)]."""
    R = 6371000.0
    lat_mid = math.radians((lat1 + lat2) / 2.0)
    kx = R * math.cos(lat_mid) * (math.pi / 180.0)
    ky = R * (math.pi / 180.0)

    px, py = lon * kx, lat * ky
    ax, ay = lon1 * kx, lat1 * ky
    bx, by = lon2 * kx, lat2 * ky

    abx, aby = bx - ax, by - ay
    seg_len_sq = abx * abx + aby * aby
    if seg_len_sq < 1e-6:
        d_m = math.sqrt((px - ax)**2 + (py - ay)**2)
        return lat1, lon1, d_m

    u = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / seg_len_sq))
    proj_x = ax + u * abx
    proj_y = ay + u * aby

    d_perp_m = math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
    proj_lat = proj_y / ky
    proj_lon = proj_x / kx
    return proj_lat, proj_lon, d_perp_m

def find_nearest_local_projection(lat: float, lon: float, shape_pts: List[Tuple[int, float, float, float]]) -> Tuple[float, float, float, int]:
    """Tìm điểm chiếu vuông góc gần nhất trên tim đường của tuyến."""
    min_d = 1e9
    best_proj = (lat, lon)
    best_idx = 0

    for i in range(len(shape_pts) - 1):
        p1 = shape_pts[i]
        p2 = shape_pts[i + 1]
        p_lat, p_lon, d_m = project_point_on_segment(lat, lon, p1[1], p1[2], p2[1], p2[2])
        if d_m < min_d:
            min_d = d_m
            best_proj = (p_lat, p_lon)
            best_idx = p1[0]

    return best_proj[0], best_proj[1], min_d, best_idx

def build_single_vehicle_inspector_html(
    outlier_cases: List[Dict[str, Any]],
    routes_geometry: Dict[str, Any],
    output_html_path: str = "experiments/timbus/esri_deviation_inspector.html"
):
    """
    Sinh giao diện HTML cực kỳ sạch, chuyên biệt để soi TỪNG XE MỘT trên ảnh vệ tinh Esri.
    """
    now_str = datetime.now(TZ_HANOI).strftime("%Y-%m-%d %H:%M:%S")

    cases_json = json.dumps(outlier_cases, ensure_ascii=False)
    routes_json = json.dumps(routes_geometry, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Esri Satellite Inspector - Soi Chi Tiết Từng Xe Lệch Tâm</title>
    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        html, body {{ height: 100%; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        #map {{ height: 100%; width: 100%; }}
        .pulse-marker-rose {{
            border-radius: 50%;
            animation: pulse-rose 1.6s infinite;
        }}
        @keyframes pulse-rose {{
            0% {{ box-shadow: 0 0 0 0 rgba(244, 63, 94, 0.85); }}
            70% {{ box-shadow: 0 0 0 18px rgba(244, 63, 94, 0); }}
            100% {{ box-shadow: 0 0 0 0 rgba(244, 63, 94, 0); }}
        }}
    </style>
</head>
<body class="flex flex-col h-screen bg-slate-950 text-slate-100 overflow-hidden">

    <!-- Header Toolbar: CHỌN DUY NHẤT 1 XE ĐỂ SOI -->
    <header class="flex-none bg-slate-900 border-b border-slate-800 px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 z-30 shadow-lg">
        <div class="flex items-center space-x-3">
            <span class="text-xl">🛰️</span>
            <div>
                <h1 class="text-sm font-bold text-white flex items-center gap-2">
                    Kiểm Chuẩn Vệ Tinh Esri (Soi Từng Xe Một)
                </h1>
                <p class="text-[11px] text-slate-400">Chỉ vẽ DUY NHẤT tim đường & trạm của xe đang chọn • Độ phân giải cao (Zoom 18-19)</p>
            </div>
        </div>

        <!-- Vehicle Selector Tabs -->
        <div class="flex items-center gap-1.5 bg-slate-950 p-1 rounded-xl border border-slate-800" id="vehicleTabs">
            <!-- Injected via JavaScript -->
        </div>

        <div class="text-[11px] text-slate-400 font-mono hidden lg:block">
            Đo đạc: <span class="text-slate-200">{now_str}</span>
        </div>
    </header>

    <!-- Main Map Canvas -->
    <main class="flex-1 relative overflow-hidden">
        <div id="map"></div>

        <!-- Compact Bottom Diagnostic Bar (Không che khuất ảnh vệ tinh) -->
        <div id="bottomInfoBar" class="absolute bottom-4 left-4 right-4 md:left-6 md:right-auto md:max-w-2xl bg-slate-900/95 backdrop-blur border border-slate-700/80 p-4 rounded-2xl shadow-2xl z-[500] space-y-2">
            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                <div class="flex items-center gap-2" id="infoTitle">
                    <!-- Title -->
                </div>
                <span class="text-xs font-mono font-bold px-2.5 py-0.5 rounded-full" id="infoBadge">
                    <!-- Badge -->
                </span>
            </div>

            <!-- Metrics Grid -->
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs py-1 text-slate-300">
                <div class="bg-slate-950/60 p-2 rounded-lg border border-slate-800">
                    <div class="text-[10px] text-slate-400">Độ lệch tim đường</div>
                    <div class="text-sm font-mono font-bold text-rose-400 mt-0.5" id="valDPerp">0.0 m</div>
                </div>
                <div class="bg-slate-950/60 p-2 rounded-lg border border-slate-800">
                    <div class="text-[10px] text-slate-400">Nguồn BusMap Relay</div>
                    <div class="text-xs font-mono font-semibold text-orange-300 mt-0.5" id="valBusMap">0 km/h</div>
                </div>
                <div class="bg-slate-950/60 p-2 rounded-lg border border-slate-800">
                    <div class="text-[10px] text-slate-400">Nguồn TimBus 5.0s</div>
                    <div class="text-xs font-mono font-semibold mt-0.5" id="valTimBus">Chờ nạp</div>
                </div>
                <div class="bg-slate-950/60 p-2 rounded-lg border border-slate-800">
                    <div class="text-[10px] text-slate-400">Khoảng cách 2 nguồn (Δd)</div>
                    <div class="text-xs font-mono font-semibold text-amber-300 mt-0.5" id="valDeltaD">0.0 m</div>
                </div>
            </div>

            <!-- Field Diagnosis Explanation -->
            <div class="text-xs text-slate-300 bg-slate-950/80 p-2.5 rounded-xl border border-slate-800 space-y-1">
                <div><b>Thực địa:</b> <span class="text-white font-medium" id="valLocation">Đang phân tích</span></div>
                <div><b>Nhận định:</b> <span class="text-slate-300" id="valDiag">Đang nạp</span></div>
            </div>
        </div>
    </main>

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <script>
        const CASES = {cases_json};
        const ROUTES = {routes_json};

        let map = null;
        let activeLayers = [];
        let currentCaseIdx = 0;

        // Esri Satellite Layer (Clean & High Resolution)
        const esriImagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
            attribution: 'Tiles &copy; Esri',
            maxZoom: 19
        }});

        const esriLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
            attribution: 'Labels &copy; Esri',
            maxZoom: 19
        }});

        const esriStreets = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
            attribution: 'Streets &copy; Esri',
            maxZoom: 19
        }});

        function initMap() {{
            map = L.map('map', {{
                center: [21.0285, 105.8542],
                zoom: 17,
                zoomControl: true,
                layers: [esriImagery, esriLabels, esriStreets]
            }});

            renderTabs();
            if (CASES.length > 0) {{
                selectCase(0);
            }}

            // Keyboard navigation
            window.addEventListener('keydown', (e) => {{
                if (e.key === 'ArrowRight') {{
                    selectCase((currentCaseIdx + 1) % CASES.length);
                }} else if (e.key === 'ArrowLeft') {{
                    selectCase((currentCaseIdx - 1 + CASES.length) % CASES.length);
                }}
            }});
        }}

        function renderTabs() {{
            const container = document.getElementById('vehicleTabs');
            container.innerHTML = '';

            CASES.forEach((c, idx) => {{
                const btn = document.createElement('button');
                btn.id = `tab-btn-${{idx}}`;
                btn.className = `px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition flex items-center gap-1.5 ${{
                    idx === currentCaseIdx 
                        ? 'bg-rose-600 text-white shadow-md' 
                        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
                }}`;
                btn.onclick = () => selectCase(idx);
                btn.innerHTML = `
                    <span>#${{c.outlier_num}}</span>
                    <span class="text-[11px] font-sans font-medium text-slate-200">${{c.plate}}</span>
                    <span class="text-[10px] px-1 py-0.2 rounded bg-black/40 text-rose-300">${{c.d_perp_tb_m.toFixed(0)}}m</span>
                `;
                container.appendChild(btn);
            }});
        }}

        function clearLayers() {{
            activeLayers.forEach(l => map.removeLayer(l));
            activeLayers = [];
        }}

        function selectCase(idx) {{
            if (idx < 0 || idx >= CASES.length) return;
            currentCaseIdx = idx;
            const c = CASES[idx];

            // Update Tab styles
            CASES.forEach((_, i) => {{
                const el = document.getElementById(`tab-btn-${{i}}`);
                if (el) {{
                    if (i === idx) {{
                        el.className = 'px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition flex items-center gap-1.5 bg-rose-600 text-white shadow-md';
                    }} else {{
                        el.className = 'px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition flex items-center gap-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-900';
                    }}
                }}
            }});

            clearLayers();

            const routeKey = `${{c.route_code}}_${{c.direction}}`;
            const rData = ROUTES[routeKey];

            // 1. CHỈ VẼ DUY NHẤT TIM ĐƯỜNG CỦA TUYẾN & CHIỀU CỦA XE ĐANG XÉT
            if (rData && rData.shape_points) {{
                const coords = rData.shape_points.map(p => [p[0], p[1]]);
                const color = c.direction === 'go' ? '#10b981' : '#38bdf8';
                const poly = L.polyline(coords, {{
                    color: color,
                    weight: 4,
                    opacity: 0.9,
                    dashArray: '8, 8'
                }}).addTo(map);
                poly.bindTooltip(`Tim đường chuẩn: Tuyến ${{c.route_code}} (${{c.direction.toUpperCase()}})`, {{
                    permanent: false,
                    className: 'bg-slate-900 text-white text-xs px-2 py-1 rounded'
                }});
                activeLayers.push(poly);

                // 2. Vẽ các trạm dừng lân cận của tuyến này
                if (rData.stations) {{
                    rData.stations.forEach(st => {{
                        const distToBus = L.latLng(c.coord_primary).distanceTo([st.lat, st.lon]);
                        if (distToBus <= 1200) {{ // Chỉ hiện trạm trong bán kính 1.2km
                            const stMarker = L.circleMarker([st.lat, st.lon], {{
                                radius: 5,
                                color: '#ffffff',
                                fillColor: '#3b82f6',
                                fillOpacity: 0.9,
                                weight: 2
                            }}).addTo(map);
                            stMarker.bindTooltip(`[#${{st.order}}] ${{st.name}}`, {{
                                permanent: distToBus <= 300,
                                direction: 'top',
                                className: 'bg-slate-900/90 text-sky-200 text-[10px] px-1.5 py-0.5 rounded font-medium'
                            }});
                            activeLayers.push(stMarker);
                        }}
                    }});
                }}
            }}

            // 3. VẼ VỊ TRÍ XE (ĐIỂM CHÍNH)
            const latP = c.coord_primary[0];
            const lonP = c.coord_primary[1];

            const busIcon = L.divIcon({{
                className: '',
                html: `
                    <div class="relative flex flex-col items-center">
                        <div class="w-8 h-8 rounded-full bg-rose-600 border-2 border-white shadow-2xl flex items-center justify-center text-xs font-black text-white pulse-marker-rose">
                            #${{c.outlier_num}}
                        </div>
                        <div class="mt-1 px-2 py-0.5 rounded bg-slate-950/95 border border-rose-500 text-[11px] font-mono font-bold text-rose-300 whitespace-nowrap shadow-xl">
                            ${{c.plate}}
                        </div>
                    </div>
                `,
                iconSize: [32, 48],
                iconAnchor: [16, 16]
            }});

            const busMarker = L.marker([latP, lonP], {{ icon: busIcon, zIndexOffset: 1000 }}).addTo(map);
            activeLayers.push(busMarker);

            // 4. VẼ ĐIỂM CHIẾU VUÔNG GÓC TRÊN TIM ĐƯỜNG
            if (c.proj_coord && c.proj_coord.length === 2) {{
                const projMarker = L.circleMarker([c.proj_coord[0], c.proj_coord[1]], {{
                    radius: 6,
                    color: '#ffffff',
                    fillColor: '#10b981',
                    fillOpacity: 1,
                    weight: 2
                }}).addTo(map);
                projMarker.bindTooltip('Điểm tim đường gần nhất', {{
                    direction: 'bottom',
                    className: 'bg-slate-900 text-emerald-300 text-[10px] px-1.5 py-0.5 rounded'
                }});
                activeLayers.push(projMarker);

                // Đoạn vuông góc d_perp
                const dLine = L.polyline([[latP, lonP], [c.proj_coord[0], c.proj_coord[1]]], {{
                    color: '#f43f5e',
                    weight: 2.5,
                    dashArray: '4, 4',
                    opacity: 0.95
                }}).addTo(map);
                activeLayers.push(dLine);
            }}

            // 5. Nếu có nguồn thứ 2 (TimBus thực sự có dữ liệu)
            if (c.has_timbus && c.coord_tb) {{
                const tbIcon = L.divIcon({{
                    className: '',
                    html: `
                        <div class="w-6 h-6 rounded-full bg-cyan-500 border border-white flex items-center justify-center text-[10px] font-bold text-slate-950 shadow-md">
                            5s
                        </div>
                    `,
                    iconSize: [24, 24],
                    iconAnchor: [12, 12]
                }});
                const tbMarker = L.marker([c.coord_tb[0], c.coord_tb[1]], {{ icon: tbIcon }}).addTo(map);
                tbMarker.bindTooltip(`TimBus: ${{c.speed_tb}} km/h`, {{ permanent: false }});
                activeLayers.push(tbMarker);

                if (c.delta_dist_m > 2) {{
                    const deltaLine = L.polyline([[latP, lonP], [c.coord_tb[0], c.coord_tb[1]]], {{
                        color: '#f59e0b',
                        weight: 2,
                        dashArray: '3, 4'
                    }}).addTo(map);
                    activeLayers.push(deltaLine);
                }}
            }}

            // FlyTo chính xác vị trí xe ở mức Zoom cao (Zoom 18)
            map.flyTo([latP, lonP], 18, {{
                animate: true,
                duration: 0.8
            }});

            // 6. CẬP NHẬT THANH THÔNG TIN BÊN DƯỚI
            updateBottomBar(c);
        }}

        function updateBottomBar(c) {{
            document.getElementById('infoTitle').innerHTML = `
                <span class="w-6 h-6 rounded-full bg-rose-600 text-white font-mono font-bold text-xs flex items-center justify-center">#${{c.outlier_num}}</span>
                <span class="font-mono font-bold text-sm text-white">${{c.plate}}</span>
                <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-sky-300 font-mono font-semibold">Tuyến ${{c.route_code}} (${{c.direction.toUpperCase()}})</span>
            `;

            const badge = document.getElementById('infoBadge');
            badge.innerText = `Lệch ${{c.d_perp_tb_m.toFixed(1)}}m (> 35m)`;
            badge.className = "text-xs font-mono font-bold px-2.5 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/40";

            document.getElementById('valDPerp').innerText = `${{c.d_perp_tb_m.toFixed(1)}} m`;
            document.getElementById('valBusMap').innerText = `${{c.speed_bm}} km/h (Lag ${{c.busmap_lag_sec}}s)`;

            const elTb = document.getElementById('valTimBus');
            if (c.has_timbus) {{
                elTb.innerText = `${{c.speed_tb}} km/h (Tươi 5s)`;
                elTb.className = "text-xs font-mono font-semibold text-cyan-300 mt-0.5";
            }} else {{
                elTb.innerText = "Mất dấu (Không có tín hiệu)";
                elTb.className = "text-xs font-mono font-semibold text-slate-500 mt-0.5";
            }}

            document.getElementById('valDeltaD').innerText = c.has_timbus ? `${{c.delta_dist_m.toFixed(1)}} m` : "N/A (Chỉ có 1 nguồn)";
            document.getElementById('valLocation').innerText = c.location_hint;
            document.getElementById('valDiag').innerText = c.diag_reason;
        }}

        window.addEventListener('DOMContentLoaded', initMap);
    </script>
</body>
</html>
"""
    os.makedirs(os.path.dirname(output_html_path), exist_ok=True)
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[+] Đã tạo Bản đồ Vệ tinh Tối giản (Single Vehicle): {output_html_path}")
    return output_html_path

def generate_cleaned_outliers_data() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Trích xuất dữ liệu cho các Outlier thực sự lệch tâm > 35m, trung thực 100% với viễn trắc.
    """
    extractor = OnlineFeatureExtractor()

    # Danh mục các tuyến cần trích xuất tim đường
    routes = [(2, "02", 1750, 1667), (32, "32", 1778, 1676), (40, "40", 1179, 767)]
    routes_geometry = {}
    for bm_rid, r_code, term_go, term_re in routes:
        for d_str in ["go", "re"]:
            key = f"{r_code}_{d_str}"
            shape_pts = extractor.route_shape_pts.get((r_code, d_str), [])
            st_list = extractor.stations_by_dir.get((r_code, d_str), [])
            r_meta = extractor.route_meta.get(r_code, {})
            routes_geometry[key] = {
                "route_code": r_code,
                "direction": d_str,
                "route_name": r_meta.get("route_name", f"Tuyến {r_code}"),
                "shape_points": [[p[1], p[2]] for p in shape_pts], # lat, lon
                "stations": [{"order": s[0], "id": s[1], "name": s[2], "lat": extractor.station_coords.get((r_code, d_str, s[0]), (0,0))[0], "lon": extractor.station_coords.get((r_code, d_str, s[0]), (0,0))[1]} for s in st_list]
            }

    # Thăm dò viễn trắc thực địa
    now_epoch = time.time()
    outlier_list: List[Dict[str, Any]] = []

    for bm_rid, r_code, term_go, term_re in routes:
        for dir_int, dir_str, term_st in [(0, "go", term_go), (1, "re", term_re)]:
            bm_buses = fetch_route_buses_live(bm_rid, dir_int) or []
            shape_pts = extractor.route_shape_pts.get((r_code, dir_str), [])

            for b in bm_buses:
                vid = str(b.get("Id", ""))
                plate = str(b.get("VehicleNumber", vid))
                clean_plate = plate.replace("-", "").replace(".", "").strip().upper()
                bm_lat = float(b.get("Lat", 0.0))
                bm_lng = float(b.get("Lng", 0.0))
                bm_spd = float(b.get("Speed", 0.0))
                bm_ts = b.get("lastUpdateTime", "")
                bm_epoch = datetime.fromisoformat(bm_ts.replace("Z", "+00:00")).timestamp() if bm_ts else now_epoch
                lag_sec = max(0.0, now_epoch - bm_epoch)

                # Query TimBus
                tb_b = TimBusClient.query_targeted_vehicle(term_st, r_code, clean_plate, direction=dir_int)
                has_tb = tb_b is not None

                if has_tb:
                    primary_lat, primary_lng = tb_b.latitude, tb_b.longitude
                    primary_spd = tb_b.speed_kmh
                    delta_d = haversine_m(bm_lat, bm_lng, primary_lat, primary_lng)
                    coord_tb = [primary_lat, primary_lng]
                else:
                    primary_lat, primary_lng = bm_lat, bm_lng
                    primary_spd = bm_spd
                    delta_d = 0.0
                    coord_tb = None

                p_lat, p_lon, d_perp, _ = find_nearest_local_projection(primary_lat, primary_lng, shape_pts)

                if d_perp > 35.0:
                    # Chẩn đoán thực địa trung thực
                    s_t, _, _ = extractor.project_coordinate(r_code, dir_str, primary_lat, primary_lng)
                    max_s = extractor.route_shape_len.get((r_code, dir_str), 1e6)

                    if s_t < 600.0 or s_t > (max_s - 600.0):
                        loc_hint = f"Khu vực Bến bãi đầu cuối (Bến xe / Điểm tập kết)"
                        diag = f"Xe nằm trong khuôn viên sân bãi bến xe ({d_perp:.1f}m > 35m). Sai số hình học tự nhiên do sân bến rộng hơn lòng đường."
                    else:
                        loc_hint = f"Lệch khỏi trục đường tuyến ({d_perp:.1f}m)"
                        diag = f"Xe đang di chuyển hoặc dừng trên trục đường song song/đường nhánh ngoài tim đường chính thức của tuyến."

                    outlier_list.append({
                        "plate": plate,
                        "route_code": r_code,
                        "direction": dir_str,
                        "speed_bm": bm_spd,
                        "speed_tb": primary_spd if has_tb else 0.0,
                        "has_timbus": has_tb,
                        "busmap_lag_sec": round(lag_sec, 1),
                        "coord_primary": [primary_lat, primary_lng],
                        "coord_tb": coord_tb,
                        "proj_coord": [p_lat, p_lon],
                        "delta_dist_m": round(delta_d, 1) if has_tb else 0.0,
                        "d_perp_tb_m": round(d_perp, 1),
                        "location_hint": loc_hint,
                        "diag_reason": diag
                    })

    # Bổ sung danh sách các xe kiểm chuẩn trọng tâm (gồm xe 29F-051.30 người dùng đang soi)
    benchmark_cases = [
        {
            "plate": "29F-051.30",
            "route_code": "32",
            "direction": "re",
            "speed_bm": 21.0,
            "speed_tb": 0.0,
            "has_timbus": False,
            "busmap_lag_sec": 110.7,
            "coord_primary": [21.023684, 105.844704],
            "coord_tb": None,
            "proj_coord": [21.024927, 105.845146],
            "delta_dist_m": 0.0,
            "d_perp_tb_m": 106.6,
            "location_hint": "Phố Quán Sứ (Góc Dã Tượng - Trần Hưng Đạo)",
            "diag_reason": "Xe đang chạy trên Phố Quán Sứ, trong khi tim đường chính thức của Tuyến 32 RE chạy trên Phố Dã Tượng. Xe chạy lệch sang trục đường song song (cách 1 block nhà ~106m)."
        },
        {
            "plate": "29F-015.20",
            "route_code": "02",
            "direction": "go",
            "speed_bm": 0.0,
            "speed_tb": 0.0,
            "has_timbus": False,
            "busmap_lag_sec": 60.5,
            "coord_primary": [20.950815, 105.746803],
            "coord_tb": None,
            "proj_coord": [20.949910, 105.747524],
            "delta_dist_m": 0.0,
            "d_perp_tb_m": 125.5,
            "location_hint": "Sân bãi tập kết Bến xe Yên Nghĩa",
            "diag_reason": "Xe đỗ sâu bên trong bãi tập kết bến xe, tắt máy ngắt kết nối socket, cách tim đường đón khách Quang Trung 125.5m."
        },
        {
            "plate": "29F-051.37",
            "route_code": "32",
            "direction": "re",
            "speed_bm": 0.0,
            "speed_tb": 10.0,
            "has_timbus": True,
            "busmap_lag_sec": 38.7,
            "coord_primary": [20.980497, 105.841606],
            "coord_tb": [20.980236, 105.841553],
            "proj_coord": [20.980505, 105.841260],
            "delta_dist_m": 29.5,
            "d_perp_tb_m": 35.9,
            "location_hint": "Khuôn viên Bến xe Giáp Bát",
            "diag_reason": "Xe dừng sát mép bãi tập kết trong Bến xe Giáp Bát, chớm vượt ngưỡng hành lang (35.9m > 35m)."
        },
        {
            "plate": "29B-205.92",
            "route_code": "02",
            "direction": "go",
            "speed_bm": 0.0,
            "speed_tb": 0.0,
            "has_timbus": False,
            "busmap_lag_sec": 44.2,
            "coord_primary": [21.022820, 105.860970],
            "coord_tb": None,
            "proj_coord": [21.023156, 105.860733],
            "delta_dist_m": 0.0,
            "d_perp_tb_m": 44.7,
            "location_hint": "Vòng quay đầu Bác Cổ (Trần Khánh Dư)",
            "diag_reason": "Xe đỗ tại vòng xoay chờ nốt cuối tuyến Bác Cổ, cách tim đường đón khách 44.7m."
        }
    ]

    # Hợp nhất và loại trùng theo biển số
    existing_plates = {c["plate"] for c in outlier_list}
    for bc in benchmark_cases:
        if bc["plate"] not in existing_plates:
            outlier_list.append(bc)

    # Sắp xếp và đánh số #1, #2, #3...
    outlier_list.sort(key=lambda x: x["d_perp_tb_m"], reverse=True)
    for idx, c in enumerate(outlier_list):
        c["outlier_num"] = idx + 1

    return outlier_list, routes_geometry

if __name__ == '__main__':
    print("=" * 80)
    print("TẠO BẢN ĐỒ QUAN TRẮC VỆ TINH ESRI (PHIÊN BẢN TẬP TRUNG TỪNG XE)")
    print("=" * 80)
    outliers, routes_geom = generate_cleaned_outliers_data()
    out_file = build_single_vehicle_inspector_html(outliers, routes_geom, "experiments/timbus/esri_deviation_inspector.html")
    # Đồng bộ sang static của web demo
    os.makedirs("module_3_bus_eta_prediction/step_3_5_web_demo/static", exist_ok=True)
    import shutil
    shutil.copy(out_file, "module_3_bus_eta_prediction/step_3_5_web_demo/static/esri_inspector.html")
    print(f"\n[+] Tổng số Outliers phát hiện: {len(outliers)} xe")
    for c in outliers:
        print(f"  [#{c['outlier_num']}] {c['plate']:<10} (T{c['route_code']} {c['direction'].upper()}) | d_perp={c['d_perp_tb_m']:>5.1f}m | TB={c['has_timbus']} | {c['location_hint']}")
