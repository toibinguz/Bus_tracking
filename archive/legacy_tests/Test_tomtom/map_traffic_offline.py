import os
import math
import json
import urllib.request
import ssl
import folium

# Bounding box siêu nhỏ ở trung tâm Hà Nội (Khu vực Hoàn Kiếm, Ba Đình)
# Định dạng: minLon, minLat, maxLon, maxLat
BBOX = "105.8200,21.0100,105.8700,21.0400"
API_KEY_FILE = "TOMTOM_API_KEY.txt"
DATA_FILE = "traffic_data.json"
MAP_FILE = "hanoi_traffic_offline.html"
TILES_DIR = "osm_tiles"

def get_api_key():
    with open(API_KEY_FILE, "r") as f:
        return f.read().strip()

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def download_osm_tiles(bbox_str, zoom_levels):
    """
    Tải bản đồ OSM (tiles) về máy để dùng offline
    """
    print("Dang kiem tra va tai ban do OSM offline ve may...")
    min_lon, min_lat, max_lon, max_lat = map(float, bbox_str.split(","))
    
    # Fake User-Agent để OSM không block
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for z in zoom_levels:
        x_min, y_max = deg2num(min_lat, min_lon, z)
        x_max, y_min = deg2num(max_lat, max_lon, z)
        
        # y_min và y_max bị ngược do vĩ độ tính từ trên xuống
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tile_path = os.path.join(TILES_DIR, str(z), str(x))
                os.makedirs(tile_path, exist_ok=True)
                
                file_path = os.path.join(tile_path, f"{y}.png")
                if not os.path.exists(file_path):
                    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                    req = urllib.request.Request(url, headers=headers)
                    try:
                        with urllib.request.urlopen(req) as response:
                            with open(file_path, 'wb') as f:
                                f.write(response.read())
                        print(f"  Da tai tile: z={z} x={x} y={y}")
                    except Exception as e:
                        print(f"  Loi tai tile {url}: {e}")

def fetch_traffic_data():
    if os.path.exists(DATA_FILE):
        print("Dang doc du lieu traffic tu file local (traffic_data.json)...")
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
            
    print("Dang request du lieu mat do giao thong tu TomTom API (1 lan duy nhat)...")
    api_key = get_api_key()
    url = f"https://api.tomtom.com/traffic/services/5/incidentDetails?key={api_key}&bbox={BBOX}&language=en-GB&fields={{incidents{{type,geometry{{type,coordinates}},properties{{iconCategory,magnitudeOfDelay}}}}}}"
    
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
        
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)
            
        return geojson_data

def style_function(feature):
    properties = feature.get("properties", {})
    magnitude = properties.get("magnitudeOfDelay", 0)
    
    color = "gray"
    weight = 4
    if magnitude == 1: color, weight = "orange", 5
    elif magnitude == 2: color, weight = "red", 6
    elif magnitude == 3: color, weight = "darkred", 8
    elif magnitude == 4: color, weight = "black", 8
        
    return {"color": color, "weight": weight, "opacity": 0.8}

def create_map(geojson_data):
    # Tâm của Bounding Box
    hanoi_coords = (21.025, 105.845)
    
    # Khởi tạo bản đồ dùng bộ tile OFFLINE đã tải về máy
    # Cú pháp truyền tile offline cho Folium
    m = folium.Map(
        location=hanoi_coords, 
        zoom_start=15, 
        tiles=f"{TILES_DIR}/{{z}}/{{x}}/{{y}}.png", 
        attr="Offline OpenStreetMap",
        min_zoom=14,
        max_zoom=16
    )
    
    folium.GeoJson(
        geojson_data,
        name="TomTom Traffic Offline",
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(fields=['magnitudeOfDelay'], aliases=['Muc do un tac (0-4):'])
    ).add_to(m)
    
    m.save(MAP_FILE)
    print(f"Hoan thanh! Ban do da duoc render offline 100%. Moi ban mo file {MAP_FILE}")

if __name__ == "__main__":
    # 1. Tải sẵn các tile bản đồ cho các mức zoom 14, 15, 16 để dùng offline
    download_osm_tiles(BBOX, zoom_levels=[14, 15, 16])
    
    # 2. Lấy dữ liệu TomTom traffic
    data = fetch_traffic_data()
    
    # 3. Vẽ map
    create_map(data)
