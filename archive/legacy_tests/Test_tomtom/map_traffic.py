import os
import json
import urllib.request
import ssl
import folium

# Khu vực bounding box của trung tâm Hà Nội
# Định dạng: minLon, minLat, maxLon, maxLat
BBOX = "105.7000,20.9500,105.9500,21.1000"
API_KEY_FILE = "TOMTOM_API_KEY.txt"
DATA_FILE = "traffic_data.json"
MAP_FILE = "hanoi_traffic.html"

def get_api_key():
    with open(API_KEY_FILE, "r") as f:
        return f.read().strip()

def fetch_traffic_data():
    # CHỈ REQUEST 1 LẦN: Nếu đã có file local, dùng luôn file local để tiết kiệm request API
    # Xoá file traffic_data.json nếu muốn request lại dữ liệu mới nhất
    if os.path.exists(DATA_FILE):
        print("Dang doc du lieu tu file local (traffic_data.json) de tiet kiem API...")
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
            
    print("Dang request du lieu mat do giao thong tu TomTom API (chi goi 1 lan)...")
    api_key = get_api_key()
    # Sử dụng Incident Details API. API này lấy các điểm ùn tắc/sự cố (Jams/Congestion) 
    # và trả về dưới dạng GeoJSON vector. Đây là cách tiết kiệm nhất thay vì request hàng chục tile ảnh.
    url = f"https://api.tomtom.com/traffic/services/5/incidentDetails?key={api_key}&bbox={BBOX}&language=en-GB&fields={{incidents{{type,geometry{{type,coordinates}},properties{{iconCategory,magnitudeOfDelay}}}}}}"
    
    # Bỏ qua xác thực SSL trong trường hợp bị lỗi ssl cục bộ
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx) as response:
        data = json.loads(response.read().decode())
        
        # Chuyển đổi format thành chuẩn GeoJSON FeatureCollection
        geojson_data = {
            "type": "FeatureCollection",
            "features": data.get("incidents", [])
        }
        
        # Lưu lại để lần sau không bị mất request API
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)
            
        return geojson_data

def style_function(feature):
    # ĐỒNG BỘ TOẠ ĐỘ:
    # TomTom API trả về hệ toạ độ EPSG:4326 (Kinh độ, Vĩ độ) chuẩn của GeoJSON.
    # Folium/Leaflet sử dụng bản đồ nền OSM là EPSG:3857 (Web Mercator), nhưng mặc định 
    # tự động đồng bộ và convert từ EPSG:4326 sang bản đồ khi dùng folium.GeoJson. 
    # Do đó, tọa độ đã được đồng bộ chính xác lên đường.
    
    properties = feature.get("properties", {})
    magnitude = properties.get("magnitudeOfDelay", 0)
    
    # Màu sắc hiển thị dựa trên mức độ ùn tắc
    color = "gray"
    weight = 4
    if magnitude == 1:
        color = "orange" # Ùn tắc nhẹ
        weight = 5
    elif magnitude == 2:
        color = "red" # Ùn tắc vừa
        weight = 6
    elif magnitude == 3:
        color = "darkred" # Ùn tắc nặng
        weight = 8
    elif magnitude == 4:
        color = "black" # Đóng đường / Tắc nghẽn hoàn toàn
        weight = 8
        
    return {
        "color": color,
        "weight": weight,
        "opacity": 0.8
    }

def create_map(geojson_data):
    # Tâm bản đồ Hà Nội (Vĩ độ, Kinh độ)
    hanoi_coords = (21.0285, 105.8542)
    
    # Đổi sang CartoDB positron (vẫn dùng dữ liệu OSM, miễn phí và rất chi tiết)
    # vì server gốc của OpenStreetMap dạo này thường chặn request mở trực tiếp từ file:// (bị lỗi Access Blocked)
    m = folium.Map(location=hanoi_coords, zoom_start=13, tiles="CartoDB positron", max_zoom=19)
    
    # Thêm dữ liệu GeoJSON lên bản đồ
    folium.GeoJson(
        geojson_data,
        name="TomTom Mật Độ Giao Thông",
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=['magnitudeOfDelay'], 
            aliases=['Mức độ ùn tắc (0-4):']
        )
    ).add_to(m)
    
    folium.LayerControl().add_to(m)
    
    m.save(MAP_FILE)
    print(f"Hoan thanh! Moi ban mo file {MAP_FILE} bang trinh duyet web de xem ket qua.")

if __name__ == "__main__":
    data = fetch_traffic_data()
    create_map(data)
