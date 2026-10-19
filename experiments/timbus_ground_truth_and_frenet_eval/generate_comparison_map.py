"""
Generate Interactive Multi-Source Comparison Map for Route 02:
Overlays:
1. TimBus Official Master (Shape Polyline + 40 Stations Go + 36 Stations Re)
2. OpenStreetMap Ground Truth (Ways Polyline + 38 Stops Go + 34 Stops Re)
3. BusMap Telemetry Real Vehicle Trajectory (GPS pings + derived velocity)
4. Highlighted Discrepancy Stations (Renamed / Newly added stations)
"""

import json
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = "data/telemetry_audit_2026_10_17_18.db"
OSM_META_PATH = "data/ground_truth/routes/route_02_metadata.json"
OUTPUT_HTML = "data/visualizations/route_02_ground_truth_comparison.html"
ROOT_OUTPUT_HTML = "route_02_ground_truth_comparison.html"

os.makedirs("data/visualizations", exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 1. TimBus Shapes
tb_shapes = {"go": [], "re": []}
for r in c.execute("SELECT direction, lat, lon, cum_distance_m FROM timbus_shape_master ORDER BY direction, point_order"):
    tb_shapes[r[0]].append([r[1], r[2], r[3]])

# 2. TimBus Stations
tb_stations = {"go": [], "re": []}
for r in c.execute("SELECT direction, station_order, station_id, station_name, lat, lon, cum_distance_m FROM timbus_station_master ORDER BY direction, station_order"):
    tb_stations[r[0]].append({
        "order": r[1],
        "id": r[2],
        "name": r[3],
        "lat": r[4],
        "lon": r[5],
        "cum_m": r[6]
    })

# 3. Telemetry: Sample actual vehicle trip on Route 02 (fleet with clean trip)
# Find a vehicle with good number of pings on Route 02
c.execute("""
SELECT fleet_code, COUNT(*) 
FROM route_02_projected_telemetry 
WHERE direction = 'go' 
GROUP BY fleet_code 
ORDER BY COUNT(*) DESC 
LIMIT 1
""")
best_fleet = c.fetchone()
fleet_code = best_fleet[0] if best_fleet else None

telemetry_trip = []
if fleet_code:
    query = """
    SELECT ping_id, timestamp, lat, lon, s_bus_m, cross_track_m, derived_speed_kmh, current_station_id
    FROM route_02_projected_telemetry
    WHERE fleet_code = ? AND direction = 'go'
    ORDER BY epoch
    LIMIT 300
    """
    for r in c.execute(query, (fleet_code,)):
        telemetry_trip.append({
            "id": r[0],
            "time": r[1],
            "lat": r[2],
            "lon": r[3],
            "s_m": r[4],
            "d_perp": r[5],
            "speed": r[6],
            "curr_st": r[7]
        })

# 4. OSM Ground Truth
with open(OSM_META_PATH, "r", encoding="utf-8") as f:
    osm_data = json.load(f)

osm_go_stops = []
osm_go_shape = []
if "variants" in osm_data and len(osm_data["variants"]) > 0:
    v0 = osm_data["variants"][0]
    for s in v0.get("stops", []):
        osm_go_stops.append({
            "seq": s.get("sequence"),
            "osm_id": s.get("osm_id"),
            "name": s.get("name"),
            "lat": s.get("lat"),
            "lon": s.get("lon")
        })
    for w in v0.get("ways", []):
        for pt in w.get("coordinates", []):
            osm_go_shape.append([pt[1], pt[0]]) # [lat, lon]

conn.close()

# Discrepancy highlights (between TimBus and BusMap)
discrepancies = [
    {"id": 774, "name": "Đối diện Bệnh viện Xanh pôn - 60 Trần Phú", "lat": 21.031665, "lon": 105.835885, "type": "NEW_TIMBUS", "desc": "Trạm mới đưa vào khai thác trên TimBus (BusMap bản cũ chưa có)"},
    {"id": 5770, "name": "870 Quang Trung - Ga Văn Khê", "lat": 20.955538, "lon": 105.755762, "type": "NEW_TIMBUS", "desc": "Trạm mới kết nối Metro Cát Linh - Hà Đông trên TimBus"},
    {"id": 6422, "name": "216 Nguyễn Trãi - Nhà Văn hóa TDP 8 & 9 Trung Văn", "lat": 20.987855, "lon": 105.797713, "type": "RENAMED_MOVED", "desc": "TimBus cập nhật mã 6422 thay cho mã 536 (ĐH Hà Nội) do dịch chuyển nhà chờ"},
    {"id": 6895, "name": "Hồ Gươm Plaza", "lat": 20.978521, "lon": 105.785516, "type": "RENAMED_MOVED", "desc": "TimBus cập nhật mã 6895 thay cho mã 799 (Big C Hà Đông)"}
]

# Generate Leaflet HTML
html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <title>Hanoi Bus Route 02 - Multi-Source Ground Truth Comparison</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        body, html {{
            margin: 0;
            padding: 0;
            height: 100%;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: #333;
        }}
        #map {{
            height: 100vh;
            width: 100vw;
        }}
        .control-panel {{
            position: absolute;
            top: 15px;
            left: 60px;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(8px);
            padding: 16px 20px;
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            z-index: 1000;
            max-width: 380px;
            max-height: 90vh;
            overflow-y: auto;
        }}
        .control-panel h2 {{
            margin: 0 0 6px 0;
            font-size: 17px;
            color: #1a237e;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .control-panel .subtitle {{
            font-size: 12px;
            color: #555;
            margin-bottom: 12px;
            line-height: 1.4;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .badge-timbus {{ background: #e8f5e9; color: #2e7d32; border: 1px solid #81c784; }}
        .badge-osm {{ background: #e3f2fd; color: #1565c0; border: 1px solid #90caf9; }}
        .badge-telemetry {{ background: #fff3e0; color: #e65100; border: 1px solid #ffb74d; }}
        
        .stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 14px;
        }}
        .stat-card {{
            background: #f8f9fa;
            padding: 8px 10px;
            border-radius: 6px;
            border-left: 3px solid #1a237e;
        }}
        .stat-card.green {{ border-left-color: #2e7d32; }}
        .stat-card.blue {{ border-left-color: #1565c0; }}
        .stat-label {{ font-size: 11px; color: #666; }}
        .stat-val {{ font-size: 14px; font-weight: 700; color: #111; }}

        .legend-section {{
            margin-top: 10px;
            border-top: 1px solid #eee;
            padding-top: 10px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 6px;
            font-size: 12px;
        }}
        .legend-color {{
            width: 18px;
            height: 18px;
            margin-right: 8px;
            border-radius: 50%;
            display: inline-block;
            flex-shrink: 0;
        }}
        .legend-line {{
            width: 22px;
            height: 4px;
            margin-right: 8px;
            display: inline-block;
            flex-shrink: 0;
            border-radius: 2px;
        }}
        .info-box {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: white;
            padding: 14px 18px;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            z-index: 1000;
            font-size: 12px;
            max-width: 320px;
            display: none;
        }}
        .info-box h4 {{ margin: 0 0 6px 0; font-size: 14px; color: #1a237e; }}
        .btn-focus {{
            background: #1a237e;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 11px;
            font-weight: 600;
            margin-top: 6px;
        }}
        .btn-focus:hover {{ background: #283593; }}
    </style>
</head>
<body>

<div id="map"></div>

<div class="control-panel">
    <h2>🚌 Tuyến 02: Bác Cổ - BX Yên Nghĩa</h2>
    <div class="subtitle">
        Bản đồ đối soát không gian đa nguồn: <span class="badge badge-timbus">TimBus Master</span> vs <span class="badge badge-osm">OpenStreetMap</span> vs <span class="badge badge-telemetry">Telemetry GPS</span>
    </div>

    <div class="stat-grid">
        <div class="stat-card green">
            <div class="stat-label">TimBus (Sở GTVT)</div>
            <div class="stat-val">40 trạm | 17.4 km</div>
        </div>
        <div class="stat-card blue">
            <div class="stat-label">OpenStreetMap</div>
            <div class="stat-val">38 trạm | 17.2 km</div>
        </div>
    </div>

    <div class="legend-section">
        <strong>Lớp dữ liệu & Ký hiệu:</strong>
        <div class="legend-item">
            <span class="legend-line" style="background: #00A86B; height: 5px;"></span>
            <span><strong>TimBus Polyline</strong> (Tim đường chính thức)</span>
        </div>
        <div class="legend-item">
            <span class="legend-color" style="background: #00A86B; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.4);"></span>
            <span><strong>TimBus Trạm</strong> (40 nhà chờ WGS84)</span>
        </div>
        <div class="legend-item">
            <span class="legend-line" style="background: #1976D2; height: 3px; border-bottom: 2px dashed #90CAF9;"></span>
            <span><strong>OSM Ways</strong> (Đường OpenStreetMap)</span>
        </div>
        <div class="legend-item">
            <span class="legend-color" style="background: #1976D2; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.4);"></span>
            <span><strong>OSM Stops</strong> (38 nền đón trả khách)</span>
        </div>
        <div class="legend-item">
            <span class="legend-line" style="background: #FF5722; height: 3px;"></span>
            <span><strong>GPS Xe Thực Tế</strong> (Xe {fleet_code})</span>
        </div>
        <div class="legend-item">
            <span class="legend-color" style="background: #9C27B0; border: 2px solid white; box-shadow: 0 0 5px #9C27B0;"></span>
            <span><strong>Điểm vi sai TimBus / BusMap</strong> (Trạm mới/dời)</span>
        </div>
    </div>

    <button class="btn-focus" onclick="fitBoundsAll()">📐 Xem toàn cảnh tuyến đường</button>
</div>

<div id="infoBox" class="info-box">
    <h4 id="infoTitle">Thông tin đối tượng</h4>
    <div id="infoContent"></div>
</div>

<!-- Leaflet JS -->
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>

<script>
    // 1. Data Injection from Backend
    const timbusShapeGo = {json.dumps([[p[0], p[1]] for p in tb_shapes["go"]])};
    const timbusShapeRe = {json.dumps([[p[0], p[1]] for p in tb_shapes["re"]])};
    const timbusStationsGo = {json.dumps(tb_stations["go"], ensure_ascii=False)};
    const osmShapeGo = {json.dumps(osm_go_shape)};
    const osmStopsGo = {json.dumps(osm_go_stops, ensure_ascii=False)};
    const telemetryPings = {json.dumps(telemetry_trip, ensure_ascii=False)};
    const discrepancyPoints = {json.dumps(discrepancies, ensure_ascii=False)};

    // 2. Initialize Map
    const map = L.map('map', {{
        center: [20.985, 105.805],
        zoom: 13,
        zoomControl: true
    }});

    // 3. Basemap Tile Layers
    const cartoLight = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; CartoDB &copy; OpenStreetMap',
        maxZoom: 19
    }}).addTo(map);

    const osmStandard = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    }});

    const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
        attribution: '&copy; Esri',
        maxZoom: 18
    }});

    // 4. Feature Groups
    const layerTimbusShape = L.featureGroup();
    const layerTimbusStations = L.featureGroup();
    const layerOsmShape = L.featureGroup();
    const layerOsmStations = L.featureGroup();
    const layerTelemetry = L.featureGroup();
    const layerDiscrepancies = L.featureGroup();

    // A. Draw TimBus Shape Go (Green solid line)
    const tbPolyGo = L.polyline(timbusShapeGo, {{
        color: '#00A86B',
        weight: 5,
        opacity: 0.85
    }}).bindPopup("<strong>TimBus Polyline (Chiều đi)</strong><br>Tổng chiều dài: 17.42 km<br>Nguồn: TRAMOC / Sở GTVT Hà Nội");
    layerTimbusShape.addLayer(tbPolyGo);

    // B. Draw TimBus Stations Go (Green circles with numbers)
    timbusStationsGo.forEach((s, idx) => {{
        const marker = L.circleMarker([s.lat, s.lon], {{
            radius: 6,
            fillColor: '#00A86B',
            color: '#FFFFFF',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.95
        }}).bindPopup(`
            <div style="font-size:12px; min-width:200px;">
                <span class="badge badge-timbus">TimBus Master Station</span>
                <h4 style="margin:6px 0 4px 0; color:#2e7d32;">#${{s.order + 1}}. ${{s.name}}</h4>
                <strong>Mã trạm (ObjectID):</strong> ${{s.id}}<br>
                <strong>Tọa độ:</strong> ${{s.lat.toFixed(6)}}, ${{s.lon.toFixed(6)}}<br>
                <strong>Khoảng cách từ đầu bến (s):</strong> ${{s.cum_m.toLocaleString()}} m (${{(s.cum_m/1000).toFixed(2)}} km)
            </div>
        `);
        layerTimbusStations.addLayer(marker);
    }});

    // C. Draw OSM Shape Go (Blue line)
    if (osmShapeGo.length > 0) {{
        const osmPoly = L.polyline(osmShapeGo, {{
            color: '#1976D2',
            weight: 3,
            opacity: 0.7,
            dashArray: '6, 6'
        }}).bindPopup("<strong>OpenStreetMap Ways (Route 02)</strong><br>Nguồn: OpenStreetMap Relation 12851968");
        layerOsmShape.addLayer(osmPoly);
    }}

    // D. Draw OSM Stations Go (Blue circles)
    osmStopsGo.forEach((s) => {{
        const marker = L.circleMarker([s.lat, s.lon], {{
            radius: 5,
            fillColor: '#1976D2',
            color: '#FFFFFF',
            weight: 1.5,
            opacity: 1,
            fillOpacity: 0.8
        }}).bindPopup(`
            <div style="font-size:12px; min-width:200px;">
                <span class="badge badge-osm">OpenStreetMap Stop</span>
                <h4 style="margin:6px 0 4px 0; color:#1565c0;">Thứ tự ${{s.seq}}: ${{s.name}}</h4>
                <strong>OSM ID:</strong> ${{s.osm_id}}<br>
                <strong>Tọa độ:</strong> ${{s.lat.toFixed(6)}}, ${{s.lon.toFixed(6)}}
            </div>
        `);
        layerOsmStations.addLayer(marker);
    }});

    // E. Draw Real Vehicle Telemetry Trajectory (Orange)
    if (telemetryPings.length > 0) {{
        const telCoords = telemetryPings.map(p => [p.lat, p.lon]);
        const telPoly = L.polyline(telCoords, {{
            color: '#FF5722',
            weight: 3,
            opacity: 0.9
        }}).bindPopup(`<strong>Luồng GPS Thực Tế (Xe ${{telemetryPings[0] ? '{fleet_code}' : ''}})</strong><br>Số bản tin ghi nhận: ${{telemetryPings.length}}`);
        layerTelemetry.addLayer(telPoly);

        // Add circle pings
        telemetryPings.forEach((p, idx) => {{
            if (idx % 2 === 0) {{ // Sample every 2nd ping for performance
                const marker = L.circleMarker([p.lat, p.lon], {{
                    radius: 3.5,
                    fillColor: '#FF5722',
                    color: '#FFFFFF',
                    weight: 1,
                    opacity: 0.9,
                    fillOpacity: 0.85
                }}).bindPopup(`
                    <div style="font-size:12px;">
                        <span class="badge badge-telemetry">Telemetry Ping</span><br>
                        <strong>Thời gian:</strong> ${{p.time}}<br>
                        <strong>Tọa độ lũy kế (s):</strong> ${{p.s_m.toFixed(1)}} m<br>
                        <strong>Vi sai tâm đường (d⊥):</strong> ${{p.d_perp.toFixed(1)}} m<br>
                        <strong>Vận tốc dẫn xuất:</strong> ${{p.speed.toFixed(1)}} km/h<br>
                        <strong>current_station_id:</strong> ${{p.curr_st}}
                    </div>
                `);
                layerTelemetry.addLayer(marker);
            }}
        }});
    }}

    // F. Draw Discrepancy Highlights (Purple)
    discrepancyPoints.forEach(d => {{
        const marker = L.circleMarker([d.lat, d.lon], {{
            radius: 9,
            fillColor: '#9C27B0',
            color: '#FFFFFF',
            weight: 2.5,
            opacity: 1,
            fillOpacity: 0.9
        }}).bindPopup(`
            <div style="font-size:12px; min-width:220px;">
                <span class="badge" style="background:#f3e5f5; color:#7b1fa2; border:1px solid #ce93d8;">ĐIỂM VI SAI NỔI BẬT</span>
                <h4 style="margin:6px 0 4px 0; color:#7b1fa2;">[${{d.id}}] ${{d.name}}</h4>
                <strong>Loại:</strong> ${{d.type}}<br>
                <strong>Giải trình:</strong> ${{d.desc}}<br>
                <strong>Tọa độ:</strong> ${{d.lat.toFixed(6)}}, ${{d.lon.toFixed(6)}}
            </div>
        `);
        layerDiscrepancies.addLayer(marker);
    }});

    // Add all to map by default
    layerTimbusShape.addTo(map);
    layerTimbusStations.addTo(map);
    layerOsmShape.addTo(map);
    layerOsmStations.addTo(map);
    layerTelemetry.addTo(map);
    layerDiscrepancies.addTo(map);

    // 5. Layer Controls
    const baseMaps = {{
        "Bản đồ CartoDB Voyager": cartoLight,
        "OpenStreetMap Chuẩn": osmStandard,
        "Vệ tinh Esri Satellite": esriSat
    }};

    const overlayMaps = {{
        "🟩 TimBus Tim đường (Master Polyline)": layerTimbusShape,
        "🟩 TimBus 40 Trạm dừng": layerTimbusStations,
        "🟦 OSM Tim đường (Ways)": layerOsmShape,
        "🟦 OSM 38 Trạm dừng": layerOsmStations,
        "🟧 GPS Xe buýt Thực tế (Telemetry)": layerTelemetry,
        "🟪 Điểm vi sai / Trạm mới (Discrepancies)": layerDiscrepancies
    }};

    L.control.layers(baseMaps, overlayMaps, {{ collapsed: false, position: 'topright' }}).addTo(map);

    function fitBoundsAll() {{
        map.fitBounds(tbPolyGo.getBounds(), {{ padding: [30, 30] }});
    }}

    // Initial zoom to fit route
    fitBoundsAll();
</script>

</body>
</html>
"""

# Write to both locations
with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html_content)

with open(ROOT_OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"[SUCCESS] Da tao thanh cong file ban do HTML tuong tac:")
print(f"  1. {OUTPUT_HTML}")
print(f"  2. {ROOT_OUTPUT_HTML}")
print("Co the mo truc tiep bang trinh duyet (Chrome / Edge)!")

