import os
import sys
import json
import urllib.request
import ssl
import time

sys.stdout.reconfigure(encoding='utf-8')

API_KEY_FILE = "Test_tomtom/TOMTOM_API_KEY.txt"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get_api_key():
    with open(API_KEY_FILE, "r") as f:
        return f.read().strip()

def fetch_incident_details(api_key, bbox):
    fields = "{incidents{type,geometry{type,coordinates},properties{iconCategory,magnitudeOfDelay,delay,length}}}"
    url = f"https://api.tomtom.com/traffic/services/5/incidentDetails?key={api_key}&bbox={bbox}&language=en-GB&fields={fields}"
    req = urllib.request.Request(url, headers={"User-Agent": "Benchmark/1.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
            return json.loads(r.read().decode()).get("incidents", [])
    except Exception as e:
        print(f"Error fetching incident: {e}")
        return []

def fetch_flow_segment(api_key, lat, lon):
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?key={api_key}&point={lat},{lon}"
    req = urllib.request.Request(url, headers={"User-Agent": "Benchmark/1.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
            d = json.loads(r.read().decode())
            return d.get("flowSegmentData", {})
    except Exception as e:
        print(f"Error fetching flow at {lat},{lon}: {e}")
        return {}

def main():
    api_key = get_api_key()
    print("=" * 110)
    print("THỰC NGHIỆM ĐỐI SOÁT ĐA TẦNG GIAO THÔNG TOMTOM: TỪ RẤT TẮC -> THÔNG THOÁNG")
    print("=" * 110)
    
    # 1. Quét incident diện rộng
    print("[1] Đang quét Incident Details diện rộng...")
    bbox = "105.8000,21.0000,105.8800,21.0500"
    incidents = fetch_incident_details(api_key, bbox)
    print(f"  -> Ghi nhận {len(incidents)} sự cố trong khu vực.")
    
    # Danh sách các điểm thử nghiệm theo từng phân tầng:
    # 1. Rất tắc (Major / Severe)
    # 2. Tắc vừa (Moderate)
    # 3. Ùn ứ nhẹ (Minor / Construction slowdown)
    # 4. Thông thoáng hoàn toàn (Free flow)
    
    test_spots = [
        # Nhóm 1: Rất tắc (Major Jam)
        {"level": "RẤT TẮC", "name": "Nút giao Tràng Thi - Quán Sứ", "lat": 21.02755, "lon": 105.84601, "inc_mag": 3, "inc_delay": 219, "inc_len": 263.7},
        {"level": "RẤT TẮC", "name": "Hàng Đậu - Quán Thánh", "lat": 21.03957, "lon": 105.85109, "inc_mag": 3, "inc_delay": 245, "inc_len": 220.4},
        
        # Nhóm 2: Tắc vừa (Moderate Jam)
        {"level": "TẮC VỪA", "name": "Phố Trần Hưng Đạo", "lat": 21.02626, "lon": 105.85166, "inc_mag": 3, "inc_delay": 97, "inc_len": 195.1},
        {"level": "TẮC VỪA", "name": "Khu vực Giảng Võ - Cát Linh", "lat": 21.02851, "lon": 105.82512, "inc_mag": 2, "inc_delay": 65, "inc_len": 180.0},
        
        # Nhóm 3: Ùn ứ nhẹ / Giảm tốc thi công (Minor / Slow)
        {"level": "ÙN Ứ NHẸ", "name": "Đoạn thi công Giải Phóng", "lat": 21.00125, "lon": 105.84152, "inc_mag": 1, "inc_delay": 25, "inc_len": 150.0},
        {"level": "ÙN Ứ NHẸ", "name": "Nút giao Ngã Tư Sở", "lat": 21.00282, "lon": 105.81985, "inc_mag": 1, "inc_delay": 20, "inc_len": 200.0},
        
        # Nhóm 4: Thông thoáng hoàn toàn (Free Flow - Không có Incident)
        {"level": "THÔNG THOÁNG", "name": "Đại lộ Thăng Long (Cao tốc)", "lat": 21.00280, "lon": 105.77120, "inc_mag": 0, "inc_delay": 0, "inc_len": 0},
        {"level": "THÔNG THOÁNG", "name": "Đường Võ Chí Công (Cầu Nhật Tân)", "lat": 21.07120, "lon": 105.80850, "inc_mag": 0, "inc_delay": 0, "inc_len": 0},
        {"level": "THÔNG THOÁNG", "name": "Đường Hoàng Diệu (Khu Ba Đình)", "lat": 21.03600, "lon": 105.83900, "inc_mag": 0, "inc_delay": 0, "inc_len": 0}
    ]
    
    print(f"\n[2] Bắt đầu gọi Flow Segment cho {len(test_spots)} điểm thuộc 4 phân tầng...")
    
    results = []
    for idx, spot in enumerate(test_spots):
        print(f"  [{idx+1}/{len(test_spots)}] Đang đo: {spot['name']} ({spot['level']})...")
        flow = fetch_flow_segment(api_key, spot["lat"], spot["lon"])
        time.sleep(0.15) # Politeness
        
        curr_speed = flow.get("currentSpeed")
        free_speed = flow.get("freeFlowSpeed")
        curr_time = flow.get("currentTravelTime")
        free_time = flow.get("freeFlowTravelTime")
        confidence = flow.get("confidence")
        
        if curr_speed is None or free_speed is None:
            print(f"    -> Bỏ qua (không có dữ liệu)")
            continue
            
        flow_delay = max(0, curr_time - free_time) if (curr_time and free_time) else 0
        speed_ratio = (curr_speed / free_speed) * 100 if free_speed > 0 else 100.0
        
        results.append({
            "stt": idx + 1,
            "level": spot["level"],
            "name": spot["name"],
            "lat": spot["lat"],
            "lon": spot["lon"],
            "inc_mag": spot["inc_mag"],
            "inc_delay": spot["inc_delay"],
            "free_speed": free_speed,
            "curr_speed": curr_speed,
            "speed_ratio": round(speed_ratio, 1),
            "free_time": free_time,
            "curr_time": curr_time,
            "flow_delay": flow_delay,
            "confidence": round(confidence, 2) if confidence else None
        })
        
    print("\n" + "=" * 125)
    print(f"{'MỨC ĐỘ':<13} | {'ĐỊA ĐIỂM':<30} | {'V_TỰ DO':<7} | {'V_THỰC':<7} | {'TỶ LỆ %':<8} | {'INC DELAY':<9} | {'FLOW DELAY':<10} | {'ĐÁNH GIÁ TRẠNG THÁI'}")
    print("-" * 125)
    for r in results:
        status_eval = "Đường kẹt cứng" if r["speed_ratio"] < 40 else ("Chậm vừa" if r["speed_ratio"] < 70 else ("Hơi chậm" if r["speed_ratio"] < 90 else "Thông suốt"))
        print(f"{r['level']:<13} | {r['name']:<30} | {r['free_speed']:<7} | {r['curr_speed']:<7} | {r['speed_ratio']:<7}% | {r['inc_delay']:<7}s | {r['flow_delay']:<8}s | {status_eval}")
    print("=" * 125)
    
    with open("data/benchmark_multilevel_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n[*] Đã lưu toàn bộ kết quả vào: data/benchmark_multilevel_results.json")

if __name__ == "__main__":
    main()

