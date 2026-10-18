import os
import math
import json
import urllib.request
import ssl
import time
import folium

BBOX = "105.8200,21.0100,105.8700,21.0400"
API_KEY_FILE = "TOMTOM_API_KEY.txt"
BROAD_DATA_FILE = "traffic_broad_data.json"
SPECIFIC_DATA_FILE = "traffic_specific_data.json"
MAP_FILE = "hanoi_traffic_hybrid.html"
TILES_DIR = "osm_tiles"

def get_api_key():
    with open(API_KEY_FILE, "r") as f:
        return f.read().strip()

def fetch_broad_incidents():
    if os.path.exists(BROAD_DATA_FILE):
        print("[1] Dang doc du lieu so bo (Broad) tu file local...")
        with open(BROAD_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
            
    print("[1] Dang goi API Incident Details (1 request) de quet so bo...")
    api_key = get_api_key()
    url = f"https://api.tomtom.com/traffic/services/5/incidentDetails?key={api_key}&bbox={BBOX}&language=en-GB&fields={{incidents{{type,geometry{{type,coordinates}},properties{{iconCategory,magnitudeOfDelay,delay,length}}}}}}"
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx) as response:
        data = json.loads(response.read().decode())
        geojson_data = {
            "type": "FeatureCollection",
            "features": data.get("incidents", [])
        }
        with open(BROAD_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)
        return geojson_data

def fetch_specific_segments(incidents_geojson, top_n=5):
    if os.path.exists(SPECIFIC_DATA_FILE):
        print("[2] Dang doc du lieu chi tiet (Specific) tu file local...")
        with open(SPECIFIC_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    print(f"[2] Dang phan tich de tim {top_n} tuyen duong tac nhat...")
    features = incidents_geojson.get("features", [])
    
    # Tính toán chỉ số delay_density = delay / length
    # Chỉ xét những incident có length > 0 và là LineString
    valid_incidents = []
    for feat in features:
        props = feat.get("properties", {})
        delay = props.get("delay") or 0
        length = props.get("length") or 0
        geom_type = feat.get("geometry", {}).get("type", "")
        if length > 0 and geom_type == "LineString":
            delay_density = delay / length
            feat["properties"]["delay_density"] = delay_density
            valid_incidents.append(feat)
            
    # Sort giảm dần theo độ nghiêm trọng (delay / length)
    valid_incidents.sort(key=lambda x: x["properties"]["delay_density"], reverse=True)
    top_incidents = valid_incidents[:top_n]
    
    print(f"[3] Dang goi API Flow Segment Data cho {len(top_incidents)} diem tac nhat...")
    api_key = get_api_key()
    detailed_segments = []
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for idx, incident in enumerate(top_incidents):
        # Lấy tọa độ ở giữa của đoạn đường để query segment
        coords = incident["geometry"]["coordinates"]
        mid_idx = len(coords) // 2
        lon, lat = coords[mid_idx]
        
        print(f"  -> Query diem {idx+1}/{len(top_incidents)} tai toa do {lat},{lon}...")
        url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?key={api_key}&point={lat},{lon}"
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, context=ctx) as response:
                seg_data = json.loads(response.read().decode())
                
                # Chuyển đổi data của segment thành GeoJSON Feature
                flow = seg_data.get("flowSegmentData", {})
                flow_coords = flow.get("coordinates", {}).get("coordinate", [])
                
                # Format toạ độ về dạng [lon, lat] cho GeoJSON
                line_coords = [[c["longitude"], c["latitude"]] for c in flow_coords]
                
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": line_coords
                    },
                    "properties": {
                        "currentSpeed": flow.get("currentSpeed"),
                        "freeFlowSpeed": flow.get("freeFlowSpeed"),
                        "currentTravelTime": flow.get("currentTravelTime"),
                        "confidence": flow.get("confidence"),
                        "original_delay": incident["properties"].get("delay"),
                        "original_length": incident["properties"].get("length"),
                        "delay_density": incident["properties"].get("delay_density")
                    }
                }
                detailed_segments.append(feature)
            # Ngủ 0.5s để tránh rate limit
            time.sleep(0.5)
        except Exception as e:
            print(f"  Loi khi query {lat},{lon}: {e}")
            
    specific_geojson = {
        "type": "FeatureCollection",
        "features": detailed_segments
    }
    
    with open(SPECIFIC_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(specific_geojson, f, ensure_ascii=False, indent=2)
        
    return specific_geojson

def create_hybrid_map(broad_data, specific_data):
    print("[4] Dang ve ban do bieu dien ket qua...")
    hanoi_coords = (21.025, 105.845)
    
    # Ban do offline (dữ liệu đã tải từ bước trước)
    m = folium.Map(
        location=hanoi_coords, 
        zoom_start=15, 
        tiles=f"{TILES_DIR}/{{z}}/{{x}}/{{y}}.png", 
        attr="Offline OpenStreetMap",
        min_zoom=14,
        max_zoom=16
    )
    
    # ==========================================
    # LAYER 1: BROAD DATA (Dữ liệu sơ bộ nền)
    # ==========================================
    def broad_style(feature):
        return {"color": "orange", "weight": 3, "opacity": 0.4}
        
    folium.GeoJson(
        broad_data,
        name="1. Toan bo un tac (So bo - 1 Request)",
        style_function=broad_style,
        tooltip=folium.GeoJsonTooltip(fields=['delay', 'length'], aliases=['Tre (giay):', 'Chieu dai (m):'])
    ).add_to(m)
    
    # ==========================================
    # LAYER 2: SPECIFIC DATA (Top các điểm lấy số thực)
    # ==========================================
    def specific_style(feature):
        # Đường tắc nghiêm trọng màu tím đậm, dày hơn để nổi bật
        return {"color": "#8b00ff", "weight": 7, "opacity": 0.9}
        
    # Tạo nội dung HTML cho Popup để hiển thị chi tiết số thực
    for feat in specific_data.get("features", []):
        props = feat.get("properties", {})
        html_content = f"""
        <div style='width: 250px'>
            <h4 style='color: #8b00ff; margin-top:0'>Phân Tích Chi Tiết</h4>
            <b>Tốc độ hiện tại:</b> <span style='color:red'>{props.get('currentSpeed')} km/h</span><br>
            <b>Tốc độ thông thoáng:</b> {props.get('freeFlowSpeed')} km/h<br>
            <b>Tỷ lệ tốc độ:</b> {round(props.get('currentSpeed', 1) / max(props.get('freeFlowSpeed', 1), 1) * 100, 1)}%<br>
            <hr style='margin: 5px 0'>
            <b>Thời gian di chuyển:</b> {props.get('currentTravelTime')} giây<br>
            <b>Độ tin cậy dữ liệu:</b> {props.get('confidence')}<br>
            <b>Chỉ số Kẹt (Giây/Mét):</b> {round(props.get('delay_density', 0), 3)}
        </div>
        """
        iframe = folium.IFrame(html=html_content, width=280, height=200)
        popup = folium.Popup(iframe, max_width=280)
        
        # Thêm từng đường detail vào bản đồ cùng popup
        folium.GeoJson(
            feat,
            style_function=specific_style,
            popup=popup,
            tooltip="CLick vao day de xem thong so thuc!"
        ).add_to(m)
    
    # Thêm nhóm layer control (do add thủ công ở trên nên thêm 1 Group ảo để toggle)
    folium.LayerControl().add_to(m)
    
    m.save(MAP_FILE)
    print(f"Hoan thanh! Moi ban mo file {MAP_FILE}")

if __name__ == "__main__":
    # Xoá file specific cũ để ép code query API lấy dữ liệu chi tiết thật (vì là demo)
    if os.path.exists(SPECIFIC_DATA_FILE):
        os.remove(SPECIFIC_DATA_FILE)
    if os.path.exists(BROAD_DATA_FILE):
        os.remove(BROAD_DATA_FILE)
        
    broad_geojson = fetch_broad_incidents()
    specific_geojson = fetch_specific_segments(broad_geojson, top_n=5)
    create_hybrid_map(broad_geojson, specific_geojson)
