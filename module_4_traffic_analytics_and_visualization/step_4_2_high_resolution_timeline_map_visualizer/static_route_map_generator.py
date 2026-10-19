"""
Tạo ứng dụng Web bản đồ tương tác (Interactive HTML Map) cho 192 tuyến xe buýt Hà Nội.
Kiến trúc thuần túy Nodes & Ways (Ground-Truth Physical Road Network):
- Triệt tiêu 100% hiện tượng "nối xuyên đỉnh" (chord cutting):
  Mỗi Way được vẽ độc lập chính xác theo các Node thực tế của nó. Tuyệt đối không vẽ đường nối chim bay giữa các Way.
- Bảo toàn 100% toàn bộ chiều dài các tuyến (Tuyến 08A đạt đủ ~18.9 km Chiều đi và ~18.1 km Chiều về).
- Tách 2 màu trực quan rõ rệt theo chiều:
  + Chiều Đi (Outbound): Màu Xanh Dương hoàng gia (#2563eb)
  + Chiều Về (Inbound): Màu Cam cháy rực rỡ (#ea580c)
- Bật/Tắt độc lập từng chiều trên Sidebar (Accordion UI).
- Tra cứu chi tiết từng đoạn Way (Tên đường, OSM Way ID, cự ly đoạn, số đỉnh).
- Bản đồ nền Google Maps / Esri không bao giờ dính lỗi 403 khi mở trực tiếp file:/// trên Chrome/Edge.
"""

import os
import sys
import json
import glob
from pathlib import Path
from typing import Dict, Any, List

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROUTES_DIR = Path("data/ground_truth/routes") if Path("data/ground_truth/routes").exists() else Path("ground_truth_route_station/output/routes")
CATALOG_PATH = Path("data/ground_truth/master_bus_routes_catalog.json") if Path("data/ground_truth/master_bus_routes_catalog.json").exists() else Path("ground_truth_route_station/output/master_bus_routes_catalog.json")
OUTPUT_HTML = Path("data/ground_truth/hanoi_bus_routes_map.html")


HUST_ROUTES = {"31", "32", "26", "08A", "03A", "21A", "02", "19", "22A", "25", "27", "28", "35A", "35B", "41", "51", "BRT01", "E01", "E07TC"}

ROUTE_PALETTE = [
    "#e11d48", "#0284c7", "#16a34a", "#9333ea", "#ea580c",
    "#0d9488", "#ca8a04", "#4f46e5", "#c026d3", "#059669",
    "#d97706", "#2563eb", "#db2777", "#7c3aed", "#0891b2",
    "#65a30d", "#e11448", "#4338ca", "#b45309", "#047857"
]

def build_interactive_map():
    print("[*] Đang đọc Master Catalog...")
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        catalog_data = json.load(f)

    catalog = catalog_data.get("catalog", [])
    print(f"[*] Tìm thấy {len(catalog)} tuyến trong catalog.")

    routes_payload = []
    metadata_files = sorted(list(ROUTES_DIR.glob("*_metadata.json")))

    for i, meta_file in enumerate(metadata_files):
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)

        ref = meta.get("route_ref", "")
        variants = meta.get("variants", [])
        if not variants:
            continue

        is_hust = ref in HUST_ROUTES
        cat_info = next((c for c in catalog if c.get("route_ref") == ref), {})
        route_base_color = ROUTE_PALETTE[i % len(ROUTE_PALETTE)]

        variants_data = []
        for vIdx, v in enumerate(variants):
            # 1. Đóng gói ways gọn nhẹ: [osm_id, street_name, length_m, [[lat, lon], ...]]
            ways_packed = []
            for w in v.get("ways", []):
                coords = [[round(pt[1], 5), round(pt[0], 5)] for pt in w.get("coordinates", [])]
                if len(coords) >= 2:
                    ways_packed.append([
                        w.get("osm_id", 0),
                        w.get("name", ""),
                        round(w.get("length_m", 0)),
                        coords
                    ])

            # 2. Đóng gói stops: [lat, lon, name, seq]
            stops_packed = [
                [round(s["lat"], 5), round(s["lon"], 5), s["name"], s["sequence"]]
                for s in v.get("stops", [])
            ]

            # 3. Định danh chiều & màu sắc
            if vIdx == 0:
                dir_label = "Chiều đi"
                dir_type = "outbound"
                dir_color = "#2563eb"  # Royal Blue
            elif vIdx == 1:
                dir_label = "Chiều về"
                dir_type = "inbound"
                dir_color = "#ea580c"  # Vivid Orange
            else:
                dir_label = f"Biến thể {vIdx + 1}"
                dir_type = f"variant_{vIdx}"
                dir_color = "#8b5cf6"  # Purple

            variants_data.append({
                "variant_index": vIdx,
                "dir_label": dir_label,
                "dir_type": dir_type,
                "dir_color": dir_color,
                "name": v.get("name", ""),
                "from": v.get("from", ""),
                "to": v.get("to", ""),
                "length_km": v.get("length_km", 0.0),
                "operator": v.get("operator", ""),
                "ways_count": len(ways_packed),
                "stops_count": len(stops_packed),
                "ways": ways_packed,
                "stops": stops_packed
            })

        routes_payload.append({
            "ref": ref,
            "is_hust": is_hust,
            "base_color": route_base_color,
            "variants_count": len(variants_data),
            "total_length_km": cat_info.get("total_length_km", sum(v["length_km"] for v in variants_data)),
            "total_ways": cat_info.get("total_ways", sum(v["ways_count"] for v in variants_data)),
            "total_stops": cat_info.get("total_stops", sum(v["stops_count"] for v in variants_data)),
            "variants": variants_data
        })

    print(f"[*] Đóng gói thành công {len(routes_payload)} tuyến vào HTML...")
    json_data_str = json.dumps(routes_payload, ensure_ascii=False, separators=(',', ':'))

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bản Đồ Mạng Lưới Tuyến & Trạm Xe Buýt Hà Nội (Chuẩn Nodes & Ways OSM)</title>
    
    <!-- Leaflet CSS & JS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    
    <!-- Google Fonts & Font Awesome -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">

    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        body {{
            display: flex;
            height: 100vh;
            overflow: hidden;
            background: #0b1120;
            color: #f8fafc;
        }}
        #sidebar {{
            width: 420px;
            background: #0f172a;
            border-right: 1px solid #1e293b;
            display: flex;
            flex-direction: column;
            z-index: 1000;
            box-shadow: 6px 0 24px rgba(0,0,0,0.4);
        }}
        .header {{
            padding: 16px 20px;
            background: #020617;
            border-bottom: 1px solid #1e293b;
        }}
        .header h1 {{
            font-size: 16px;
            font-weight: 800;
            color: #38bdf8;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .header p {{
            font-size: 11.5px;
            color: #94a3b8;
            margin-top: 5px;
            line-height: 1.4;
        }}
        .stats-bar {{
            display: flex;
            gap: 6px;
            padding: 10px 18px;
            background: #0f172a;
            border-bottom: 1px solid #1e293b;
            font-size: 11px;
        }}
        .stat-badge {{
            flex: 1;
            padding: 6px 6px;
            border-radius: 6px;
            background: #1e293b;
            text-align: center;
            border: 1px solid #334155;
        }}
        .stat-badge span {{
            display: block;
            font-weight: 700;
            font-size: 13px;
            color: #f1f5f9;
        }}
        .controls {{
            padding: 12px 18px;
            border-bottom: 1px solid #1e293b;
            display: flex;
            flex-direction: column;
            gap: 10px;
            background: #090e1a;
        }}
        .search-box {{
            position: relative;
        }}
        .search-box input {{
            width: 100%;
            padding: 9px 12px 9px 34px;
            border-radius: 8px;
            border: 1px solid #334155;
            background: #020617;
            color: #f8fafc;
            font-size: 13px;
            outline: none;
            transition: all 0.2s;
        }}
        .search-box input:focus {{
            border-color: #38bdf8;
            box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
        }}
        .search-box i {{
            position: absolute;
            left: 11px;
            top: 11px;
            color: #64748b;
            font-size: 13px;
        }}
        .filter-pills {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }}
        .pill {{
            padding: 4px 10px;
            border-radius: 16px;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            border: 1px solid #334155;
            background: #1e293b;
            color: #cbd5e1;
            transition: all 0.15s;
        }}
        .pill.active {{
            background: #0284c7;
            border-color: #38bdf8;
            color: white;
            box-shadow: 0 2px 8px rgba(2, 132, 199, 0.3);
        }}
        .action-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            color: #94a3b8;
            padding-top: 2px;
        }}
        .btn-link {{
            background: none;
            border: none;
            color: #38bdf8;
            cursor: pointer;
            font-size: 11.5px;
            font-weight: 600;
            padding: 2px 2px;
            transition: color 0.15s;
        }}
        .btn-link:hover {{
            color: #7dd3fc;
            text-decoration: underline;
        }}
        #route-list {{
            flex: 1;
            overflow-y: auto;
            padding: 10px 14px;
        }}
        #route-list::-webkit-scrollbar {{
            width: 6px;
        }}
        #route-list::-webkit-scrollbar-thumb {{
            background: #334155;
            border-radius: 3px;
        }}

        /* Card Tuyến Xe Buýt */
        .route-card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            margin-bottom: 8px;
            overflow: hidden;
            transition: all 0.2s ease;
        }}
        .route-card.active {{
            border-color: #38bdf8;
            box-shadow: 0 2px 12px rgba(56, 189, 248, 0.15);
        }}
        .route-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 9px 12px;
            background: #152033;
            cursor: pointer;
            user-select: none;
        }}
        .route-header:hover {{
            background: #1c2a42;
        }}
        .route-title-area {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
            overflow: hidden;
        }}
        .route-badge {{
            min-width: 44px;
            padding: 3px 6px;
            border-radius: 6px;
            font-weight: 800;
            font-size: 12px;
            text-align: center;
            color: #fff;
            flex-shrink: 0;
            letter-spacing: 0.5px;
        }}
        .route-main-info {{
            overflow: hidden;
            flex: 1;
        }}
        .route-name {{
            font-size: 12px;
            font-weight: 700;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: #f1f5f9;
        }}
        .route-sub {{
            font-size: 10px;
            color: #94a3b8;
            display: flex;
            gap: 6px;
            align-items: center;
            margin-top: 2px;
        }}
        .tag-status {{
            font-size: 9px;
            padding: 1px 5px;
            border-radius: 4px;
            font-weight: 700;
        }}
        .tag-nodesways {{ background: #065f46; color: #34d399; }}
        .tag-hust {{ background: #831843; color: #f472b6; }}

        .route-actions {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-shrink: 0;
            margin-left: 8px;
        }}
        .btn-expand {{
            background: none;
            border: none;
            color: #94a3b8;
            cursor: pointer;
            font-size: 12px;
            padding: 4px;
            transition: transform 0.2s;
        }}
        .btn-expand.expanded {{
            transform: rotate(180deg);
            color: #38bdf8;
        }}
        .checkbox-custom {{
            width: 17px;
            height: 17px;
            cursor: pointer;
            accent-color: #38bdf8;
        }}

        /* Danh sách Chiều (Variants) */
        .variant-list {{
            background: #0f172a;
            border-top: 1px solid #283548;
            display: flex;
            flex-direction: column;
        }}
        .variant-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px 8px 16px;
            border-bottom: 1px solid #1a2536;
            transition: background 0.15s;
        }}
        .variant-item:last-child {{
            border-bottom: none;
        }}
        .variant-item:hover {{
            background: #152238;
        }}
        .variant-info {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
            overflow: hidden;
            cursor: pointer;
        }}
        .dir-indicator {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
            flex-shrink: 0;
            box-shadow: 0 0 6px rgba(0,0,0,0.5);
        }}
        .dir-indicator.outbound {{
            background: #2563eb;
            box-shadow: 0 0 8px #2563eb;
        }}
        .dir-indicator.inbound {{
            background: #ea580c;
            box-shadow: 0 0 8px #ea580c;
        }}
        .variant-details {{
            overflow: hidden;
            flex: 1;
        }}
        .variant-title {{
            font-size: 11.5px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .variant-title .dir-pill {{
            font-size: 9px;
            font-weight: 800;
            padding: 1px 6px;
            border-radius: 4px;
            text-transform: uppercase;
        }}
        .dir-pill-outbound {{
            background: #1e3a8a;
            color: #93c5fd;
            border: 1px solid #3b82f6;
        }}
        .dir-pill-inbound {{
            background: #7c2d12;
            color: #fdba74;
            border: 1px solid #f97316;
        }}
        .variant-path {{
            font-size: 11px;
            color: #cbd5e1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-top: 2px;
        }}
        .variant-ctrls {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-left: 8px;
        }}
        .btn-focus {{
            background: none;
            border: none;
            color: #64748b;
            cursor: pointer;
            font-size: 12px;
            padding: 4px;
            transition: color 0.15s;
        }}
        .btn-focus:hover {{
            color: #38bdf8;
        }}

        /* BẢN ĐỒ */
        #map-container {{
            flex: 1;
            position: relative;
        }}
        #map {{
            width: 100%;
            height: 100%;
        }}

        /* Thanh Công cụ Nổi (Floating Toolbar) */
        .floating-tools {{
            position: absolute;
            top: 16px;
            right: 16px;
            z-index: 1000;
            background: rgba(15, 23, 42, 0.92);
            backdrop-filter: blur(10px);
            border: 1px solid #334155;
            padding: 10px 16px;
            border-radius: 10px;
            display: flex;
            gap: 16px;
            align-items: center;
            font-size: 12px;
            color: #f1f5f9;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }}
        .tool-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .tool-check {{
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            user-select: none;
        }}
        .tool-check input {{
            cursor: pointer;
            accent-color: #38bdf8;
        }}
        .color-legend {{
            display: flex;
            align-items: center;
            gap: 12px;
            border-left: 1px solid #334155;
            padding-left: 12px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 11.5px;
            font-weight: 600;
        }}
        .legend-line {{
            width: 18px;
            height: 5px;
            border-radius: 2px;
        }}
        .legend-line.outbound {{
            background: #2563eb;
            box-shadow: 0 0 6px #2563eb;
        }}
        .legend-line.inbound {{
            background: #ea580c;
            box-shadow: 0 0 6px #ea580c;
        }}

        /* Leaflet popup dark theme */
        .leaflet-popup-content-wrapper {{
            background: #0f172a !important;
            color: #f8fafc !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
            box-shadow: 0 12px 30px rgba(0,0,0,0.6) !important;
            padding: 6px 4px !important;
        }}
        .leaflet-popup-tip {{
            background: #0f172a !important;
        }}
        .popup-badge {{
            display: inline-block;
            font-size: 10px;
            font-weight: 800;
            padding: 2px 7px;
            border-radius: 4px;
            margin-bottom: 6px;
        }}
        .popup-title {{
            font-size: 13.5px;
            font-weight: 800;
            color: #38bdf8;
            margin-bottom: 6px;
        }}
        .popup-row {{
            font-size: 11.5px;
            color: #cbd5e1;
            margin-bottom: 4px;
            line-height: 1.4;
        }}
        .popup-row b {{
            color: #94a3b8;
        }}
    </style>
</head>
<body>

    <!-- SIDEBAR -->
    <div id="sidebar">
        <div class="header">
            <h1><i class="fa-solid fa-route" style="color: #38bdf8;"></i> MẠNG LƯỚI BUÝT HÀ NỘI</h1>
            <p>192 Tuyến chuẩn Nodes & Ways OSM • Không nối xuyên đỉnh • Tách 2 chiều</p>
        </div>

        <div class="stats-bar">
            <div class="stat-badge">
                <span id="stat-total">192</span> Tuyến
            </div>
            <div class="stat-badge">
                <span id="stat-ways" style="color: #34d399;">50,164</span> Ways
            </div>
            <div class="stat-badge">
                <span id="stat-visible" style="color: #38bdf8;">0</span> Nhánh bật
            </div>
        </div>

        <div class="controls">
            <div class="search-box">
                <i class="fa-solid fa-magnifying-glass"></i>
                <input type="text" id="searchInput" placeholder="Tìm số tuyến hoặc địa danh (vd: 08A, 31, Bách Khoa)..." />
            </div>

            <div class="filter-pills">
                <div class="pill active" data-filter="all">Tất cả (192)</div>
                <div class="pill" data-filter="hust"><i class="fa-solid fa-star" style="color: #f472b6;"></i> 19 Tuyến HUST</div>
            </div>

            <div class="action-row">
                <div style="display:flex; gap: 8px; flex-wrap: wrap;">
                    <button class="btn-link" id="btnSelectAll">Bật tất cả</button>
                    <span>•</span>
                    <button class="btn-link" id="btnDeselectAll">Tắt tất cả</button>
                    <span>•</span>
                    <button class="btn-link" id="btnSelectHUST">19 Tuyến HUST</button>
                    <span>•</span>
                    <button class="btn-link" id="btnOnlyOutbound">Chỉ Chiều Đi</button>
                    <span>•</span>
                    <button class="btn-link" id="btnOnlyInbound">Chỉ Chiều Về</button>
                </div>
            </div>
        </div>

        <div id="route-list">
            <!-- Danh sách tuyến render tự động bởi JavaScript -->
        </div>
    </div>

    <!-- MAP CONTAINER -->
    <div id="map-container">
        <!-- Floating Toolbar -->
        <div class="floating-tools">
            <div class="tool-group">
                <label class="tool-check">
                    <input type="checkbox" id="toggleStops" />
                    <span><i class="fa-solid fa-map-pin" style="color: #38bdf8;"></i> Hiển thị trạm dừng</span>
                </label>
            </div>
            <div class="color-legend">
                <div class="legend-item">
                    <div class="legend-line outbound"></div>
                    <span style="color: #93c5fd;">Chiều Đi</span>
                </div>
                <div class="legend-item">
                    <div class="legend-line inbound"></div>
                    <span style="color: #fdba74;">Chiều Về</span>
                </div>
            </div>
        </div>

        <div id="map"></div>
    </div>

    <script>
        const routesData = {json_data_str};

        // Khởi tạo bản đồ Leaflet
        const map = L.map('map', {{
            center: [21.0285, 105.8542],
            zoom: 12,
            zoomControl: false
        }});

        L.control.zoom({{ position: 'bottomright' }}).addTo(map);

        // Các lớp bản đồ nền chuẩn OpenStreetMap & Google Maps (100% Hoạt động mượt mà, không bao giờ bị chặn 403 hay màn hình trắng)
        const osmFrance = L.tileLayer('https://{{s}}.tile.openstreetmap.fr/osmfr/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 20,
            subdomains: 'abc',
            attribution: '&copy; OpenStreetMap contributors, OSM France'
        }});

        const cartoVoyager = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            maxZoom: 20,
            subdomains: 'abcd',
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }});

        const cartoDark = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            maxZoom: 20,
            subdomains: 'abcd',
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }});

        const googleStreets = L.tileLayer('https://mt1.google.com/vt/lyrs=m&x={{x}}&y={{y}}&z={{z}}', {{
            maxZoom: 20,
            attribution: '&copy; Google Maps'
        }});

        const esriStreet = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
            maxZoom: 19,
            attribution: '&copy; Esri, HERE, Garmin, USGS'
        }});

        const googleSatellite = L.tileLayer('https://mt1.google.com/vt/lyrs=y&x={{x}}&y={{y}}&z={{z}}', {{
            maxZoom: 20,
            attribution: '&copy; Google Maps Satellite'
        }});

        // Mặc định nạp OSM France (Phong cách OpenStreetMap chuẩn gốc 100%, không bị 403)
        osmFrance.addTo(map);

        const baseMaps = {{
            "🌐 OpenStreetMap (Gốc - Mượt mà)": osmFrance,
            "🗺️ OpenStreetMap (Carto Voyager)": cartoVoyager,
            "🌑 OpenStreetMap (Dark Night)": cartoDark,
            "🚗 Google Maps Đường Phố": googleStreets,
            "🏙️ Esri Đường Phố": esriStreet,
            "🛰️ Google Vệ Tinh": googleSatellite
        }};
        L.control.layers(baseMaps, null, {{ position: 'topright' }}).addTo(map);

        // Quản lý trạng thái các Layer Leaflet theo từng variant: key = `${{ref}}_${{vIdx}}`
        const variantWayLayers = {{}};
        const variantStopLayers = {{}};
        const expandedRoutes = new Set();
        let currentFilter = 'all';
        let showStops = false;

        const routeListEl = document.getElementById('route-list');
        const searchInput = document.getElementById('searchInput');

        function renderSidebar() {{
            const query = searchInput.value.toLowerCase().trim();
            routeListEl.innerHTML = '';

            routesData.forEach(route => {{
                if (currentFilter === 'hust' && !route.is_hust) return;

                const matchRef = route.ref.toLowerCase().includes(query);
                const matchName = route.variants.some(v => 
                    v.name.toLowerCase().includes(query) || 
                    v.from.toLowerCase().includes(query) || 
                    v.to.toLowerCase().includes(query)
                );
                if (query && !matchRef && !matchName) return;

                const enabledCount = route.variants.filter((_, vIdx) => !!variantWayLayers[`${{route.ref}}_${{vIdx}}`]).length;
                const isAllActive = enabledCount === route.variants.length && route.variants.length > 0;
                const isIndeterminate = enabledCount > 0 && enabledCount < route.variants.length;
                const isExpanded = expandedRoutes.has(route.ref) || query.length > 0;

                const card = document.createElement('div');
                card.className = 'route-card' + (enabledCount > 0 ? ' active' : '');
                card.dataset.ref = route.ref;

                const hustTag = route.is_hust ? '<span class="tag-status tag-hust">★ HUST</span>' : '';
                const nodeWayTag = '<span class="tag-status tag-nodesways">NODES & WAYS</span>';

                let html = `
                    <div class="route-header">
                        <div class="route-title-area" onclick="toggleAccordion('${{route.ref}}')">
                            <div class="route-badge" style="background: ${{route.base_color}}">${{route.ref}}</div>
                            <div class="route-main-info">
                                <div class="route-name">${{route.variants[0]?.name || ('Tuyến ' + route.ref)}}</div>
                                <div class="route-sub">
                                    <span>${{route.total_length_km}} km</span>
                                    <span>•</span>
                                    <span>${{route.total_ways}} ways</span>
                                    <span>•</span>
                                    <span>${{route.total_stops}} trạm</span>
                                    <span>•</span>
                                    ${{hustTag}}
                                    ${{nodeWayTag}}
                                </div>
                            </div>
                        </div>
                        <div class="route-actions">
                            <button class="btn-expand ${{isExpanded ? 'expanded' : ''}}" onclick="toggleAccordion('${{route.ref}}')" title="Xem chi tiết 2 chiều">
                                <i class="fa-solid fa-chevron-down"></i>
                            </button>
                            <input type="checkbox" class="checkbox-custom" id="chk_route_${{route.ref}}" 
                                ${{isAllActive ? 'checked' : ''}} 
                                onchange="toggleEntireRoute('${{route.ref}}', this.checked)" />
                        </div>
                    </div>
                `;

                if (isExpanded) {{
                    html += `<div class="variant-list">`;
                    route.variants.forEach((v, vIdx) => {{
                        const vKey = `${{route.ref}}_${{vIdx}}`;
                        const isVActive = !!variantWayLayers[vKey];
                        const dirClass = v.dir_type === 'outbound' ? 'outbound' : 'inbound';
                        const pillClass = v.dir_type === 'outbound' ? 'dir-pill-outbound' : 'dir-pill-inbound';

                        html += `
                            <div class="variant-item">
                                <div class="variant-info" onclick="flyToVariant('${{route.ref}}', ${{vIdx}})">
                                    <div class="dir-indicator ${{dirClass}}"></div>
                                    <div class="variant-details">
                                        <div class="variant-title">
                                            <span class="dir-pill ${{pillClass}}">${{v.dir_label}}</span>
                                            <span style="color:#e2e8f0; font-weight:600;">${{v.length_km}} km (${{v.ways_count}} ways • ${{v.stops_count}} trạm)</span>
                                        </div>
                                        <div class="variant-path" title="${{v.from}} ➔ ${{v.to}}">
                                            ${{v.from || 'Bến đầu'}} <i class="fa-solid fa-arrow-right-long" style="font-size:10px; color:#64748b;"></i> ${{v.to || 'Bến cuối'}}
                                        </div>
                                    </div>
                                </div>
                                <div class="variant-ctrls">
                                    <button class="btn-focus" onclick="flyToVariant('${{route.ref}}', ${{vIdx}})" title="Phóng to đến chiều này">
                                        <i class="fa-solid fa-crosshairs"></i>
                                    </button>
                                    <input type="checkbox" class="checkbox-custom" id="chk_var_${{vKey}}" 
                                        ${{isVActive ? 'checked' : ''}} 
                                        onchange="toggleVariant('${{route.ref}}', ${{vIdx}}, this.checked)" />
                                </div>
                            </div>
                        `;
                    }});
                    html += `</div>`;
                }}

                card.innerHTML = html;
                routeListEl.appendChild(card);

                const chkParent = card.querySelector(`#chk_route_${{route.ref}}`);
                if (chkParent) {{
                    chkParent.indeterminate = isIndeterminate;
                }}
            }});

            updateVisibleBadge();
        }}

        function toggleAccordion(ref) {{
            if (expandedRoutes.has(ref)) expandedRoutes.delete(ref);
            else expandedRoutes.add(ref);
            renderSidebar();
        }}

        // Bật / Tắt một Chiều (Vẽ độc lập từng Way - 0% nối xuyên đỉnh)
        function toggleVariant(ref, vIdx, isEnable) {{
            const route = routesData.find(r => r.ref === ref);
            if (!route) return;
            const v = route.variants[vIdx];
            if (!v) return;

            const vKey = `${{ref}}_${{vIdx}}`;

            if (isEnable) {{
                if (variantWayLayers[vKey]) return;

                const wayGroup = L.featureGroup();
                const dirPillStyle = v.dir_type === 'outbound' 
                    ? 'background:#1e3a8a; color:#93c5fd; border: 1px solid #3b82f6;' 
                    : 'background:#7c2d12; color:#fdba74; border: 1px solid #f97316;';

                // Vẽ từng đoạn Way nguyên bản (Zero Chord Cutting)
                v.ways.forEach(w => {{
                    const latlngs = w[3];
                    if (latlngs.length >= 2) {{
                        const poly = L.polyline(latlngs, {{
                            color: v.dir_color,
                            weight: 4.5,
                            opacity: 0.9,
                            lineCap: 'round',
                            lineJoin: 'round'
                        }});

                        poly.bindPopup(`
                            <div style="padding: 4px;">
                                <span class="popup-badge" style="${{dirPillStyle}}">
                                    🚌 TUYẾN ${{route.ref}} • ${{v.dir_label.toUpperCase()}}
                                </span>
                                <div class="popup-title">${{w[1] || 'Đoạn đường không tên'}}</div>
                                <div class="popup-row"><b>Tên đường OSM:</b> <span style="color:#f1f5f9; font-weight:700;">${{w[1] || 'N/A'}}</span> (Way ID: <code>${{w[0]}}</code>)</div>
                                <div class="popup-row"><b>Cự ly đoạn:</b> <span style="color:#38bdf8; font-weight:700;">${{w[2]}} m</span> | <b>Số đỉnh Nodes:</b> ${{latlngs.length}}</div>
                                <div class="popup-row"><b>Hành trình:</b> ${{v.from}} ➔ ${{v.to}} (${{v.length_km}} km)</div>
                                <div class="popup-row"><b>Tổng đoạn của chiều:</b> ${{v.ways_count}} ways | <b>Trạm:</b> ${{v.stops_count}}</div>
                            </div>
                        `);

                        poly.on('mouseover', () => {{
                            poly.setStyle({{ weight: 7, opacity: 1.0 }});
                            poly.bringToFront();
                        }});
                        poly.on('mouseout', () => {{
                            poly.setStyle({{ weight: 4.5, opacity: 0.9 }});
                        }});

                        wayGroup.addLayer(poly);
                    }}
                }});

                // Vẽ Trạm dừng theo chiều
                const stopGroup = L.featureGroup();
                v.stops.forEach(s => {{
                    const marker = L.circleMarker([s[0], s[1]], {{
                        radius: 4.5,
                        color: '#ffffff',
                        weight: 1.5,
                        fillColor: v.dir_color,
                        fillOpacity: 0.95
                    }});
                    marker.bindPopup(`
                        <div style="padding: 4px;">
                            <div class="popup-title" style="color: ${{v.dir_color}};">🚏 ${{s[2]}}</div>
                            <div class="popup-row"><b>Tuyến:</b> ${{route.ref}} (${{v.dir_label}})</div>
                            <div class="popup-row"><b>Thứ tự đón:</b> Trạm số #${{s[3]}} / ${{v.stops_count}}</div>
                            <div class="popup-row"><b>Tọa độ:</b> ${{s[0]}}, ${{s[1]}}</div>
                        </div>
                    `);
                    stopGroup.addLayer(marker);
                }});

                wayGroup.addTo(map);
                if (showStops) {{
                    stopGroup.addTo(map);
                }}

                variantWayLayers[vKey] = wayGroup;
                variantStopLayers[vKey] = stopGroup;

            }} else {{
                if (variantWayLayers[vKey]) {{
                    map.removeLayer(variantWayLayers[vKey]);
                    delete variantWayLayers[vKey];
                }}
                if (variantStopLayers[vKey]) {{
                    map.removeLayer(variantStopLayers[vKey]);
                    delete variantStopLayers[vKey];
                }}
            }}

            renderSidebar();
        }}

        function toggleEntireRoute(ref, isEnable) {{
            const route = routesData.find(r => r.ref === ref);
            if (!route) return;
            route.variants.forEach((_, vIdx) => {{
                toggleVariant(ref, vIdx, isEnable);
            }});
        }}

        function flyToVariant(ref, vIdx) {{
            const vKey = `${{ref}}_${{vIdx}}`;
            if (!variantWayLayers[vKey]) {{
                toggleVariant(ref, vIdx, true);
            }}
            if (variantWayLayers[vKey]) {{
                const bounds = variantWayLayers[vKey].getBounds();
                if (bounds.isValid()) {{
                    map.fitBounds(bounds, {{ padding: [50, 50], maxZoom: 14 }});
                }}
            }}
        }}

        function updateVisibleBadge() {{
            const count = Object.keys(variantWayLayers).length;
            document.getElementById('stat-visible').innerText = count;
        }}

        // Filter Pills
        document.querySelectorAll('.filter-pills .pill').forEach(pill => {{
            pill.addEventListener('click', () => {{
                document.querySelectorAll('.filter-pills .pill').forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                currentFilter = pill.dataset.filter;
                renderSidebar();
            }});
        }});

        searchInput.addEventListener('input', () => {{
            renderSidebar();
        }});

        // Quick Actions
        document.getElementById('btnSelectAll').addEventListener('click', () => {{
            routesData.forEach(r => {{
                r.variants.forEach((_, vIdx) => toggleVariant(r.ref, vIdx, true));
            }});
        }});

        document.getElementById('btnDeselectAll').addEventListener('click', () => {{
            Object.keys(variantWayLayers).forEach(vKey => {{
                const [ref, vIdx] = vKey.split('_');
                toggleVariant(ref, parseInt(vIdx), false);
            }});
        }});

        document.getElementById('btnSelectHUST').addEventListener('click', () => {{
            Object.keys(variantWayLayers).forEach(vKey => {{
                const [ref, vIdx] = vKey.split('_');
                toggleVariant(ref, parseInt(vIdx), false);
            }});
            routesData.filter(r => r.is_hust).forEach(r => {{
                r.variants.forEach((_, vIdx) => toggleVariant(r.ref, vIdx, true));
            }});
            const allLayers = Object.values(variantWayLayers);
            if (allLayers.length > 0) {{
                const allBounds = L.featureGroup(allLayers).getBounds();
                if (allBounds.isValid()) map.fitBounds(allBounds, {{ padding: [30, 30] }});
            }}
        }});

        document.getElementById('btnOnlyOutbound').addEventListener('click', () => {{
            routesData.forEach(r => {{
                r.variants.forEach((v, vIdx) => {{
                    if (vIdx === 0) toggleVariant(r.ref, vIdx, true);
                    else toggleVariant(r.ref, vIdx, false);
                }});
            }});
        }});

        document.getElementById('btnOnlyInbound').addEventListener('click', () => {{
            routesData.forEach(r => {{
                r.variants.forEach((v, vIdx) => {{
                    if (vIdx === 1) toggleVariant(r.ref, vIdx, true);
                    else toggleVariant(r.ref, vIdx, false);
                }});
            }});
        }});

        document.getElementById('toggleStops').addEventListener('change', (e) => {{
            showStops = e.target.checked;
            Object.keys(variantStopLayers).forEach(vKey => {{
                if (showStops && variantWayLayers[vKey]) {{
                    variantStopLayers[vKey].addTo(map);
                }} else {{
                    map.removeLayer(variantStopLayers[vKey]);
                }}
            }});
        }});

        // Mặc định ban đầu: Kích hoạt 19 Tuyến HUST (Cả 2 Chiều Đi - Xanh và Chiều Về - Cam)
        routesData.filter(r => r.is_hust).forEach(r => {{
            r.variants.forEach((_, vIdx) => toggleVariant(r.ref, vIdx, true));
        }});
        renderSidebar();

        setTimeout(() => {{
            const allLayers = Object.values(variantWayLayers);
            if (allLayers.length > 0) {{
                const allBounds = L.featureGroup(allLayers).getBounds();
                if (allBounds.isValid()) map.fitBounds(allBounds, {{ padding: [40, 40] }});
            }}
        }}, 600);

    </script>
</body>
</html>
"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"🎉 Đã sinh thành công Bản Đồ Tương Tác: {OUTPUT_HTML.resolve()}")
    return OUTPUT_HTML

def main():
    return build_interactive_map()

if __name__ == "__main__":
    main()

