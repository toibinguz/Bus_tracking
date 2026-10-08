import os
import sys
import json
import urllib.request
import ssl

sys.stdout.reconfigure(encoding='utf-8')

API_KEY_FILE = "Test_tomtom/TOMTOM_API_KEY.txt"
# BBox khu vực nội đô Hà Nội trọng điểm (Hoàn Kiếm, Đống Đa, Ba Đình, Cầu Giấy, Hai Bà Trưng)
BBOX_HANOI = "105.8000,21.0000,105.8800,21.0500"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get_api_key():
    with open(API_KEY_FILE, "r") as f:
        return f.read().strip()

def run_experiment():
    api_key = get_api_key()
    print("=" * 80)
    print("THỰC NGHIỆM ĐỐI SÁNH: VẬN TỐC THỰC TẾ (FLOW) VS VẬN TỐC NỘI SUY (INCIDENT)")
    print("=" * 80)
    
    # 1. Gọi Incident Details quét diện rộng (1 request)
    print("\n[Bước 1/2] Đang gọi TomTom Incident Details (Quét diện rộng Hà Nội)...")
    inc_url = (
        f"https://api.tomtom.com/traffic/services/5/incidentDetails"
        f"?key={api_key}&bbox={BBOX_HANOI}&language=en-GB"
        f"&fields={{incidents{{type,geometry{{type,coordinates}},properties{{magnitudeOfDelay,delay,length}}}}}}"
    )
    req = urllib.request.Request(inc_url, headers={"User-Agent": "TrafficExp/1.0"})
    with urllib.request.urlopen(req, context=ctx) as resp:
        inc_data = json.loads(resp.read().decode())
        
    incidents = inc_data.get("incidents", [])
    print(f"  -> Tổng số sự cố ghi nhận tại Hà Nội lúc này: {len(incidents)}")
    
    # Lọc các sự cố hợp lệ có delay và length
    valid = []
    for inc in incidents:
        props = inc.get("properties", {})
        delay = props.get("delay")
        length = props.get("length")
        geom = inc.get("geometry", {})
        if delay and length and delay > 0 and length > 0 and geom.get("coordinates"):
            props["delay_density"] = delay / length
            valid.append(inc)
            
    # Sắp xếp giảm dần theo delay density
    valid.sort(key=lambda x: x["properties"]["delay_density"], reverse=True)
    sample_incidents = valid[:6] # Lấy mẫu 6 điểm
    
    print(f"\n[Bước 2/2] Gọi TomTom Flow Segment Data cho {len(sample_incidents)} điểm mẫu để đối soát...")
    
    results = []
    for idx, inc in enumerate(sample_incidents):
        props = inc["properties"]
        coords = inc["geometry"]["coordinates"]
        mid_pt = coords[len(coords) // 2]
        lon, lat = mid_pt[0], mid_pt[1]
        
        delay_sec = props["delay"]
        length_m = props["length"]
        mag = props.get("magnitudeOfDelay", 0)
        
        flow_url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?key={api_key}&point={lat},{lon}"
        try:
            freq = urllib.request.Request(flow_url, headers={"User-Agent": "TrafficExp/1.0"})
            with urllib.request.urlopen(freq, context=ctx) as fresp:
                flow_json = json.loads(fresp.read().decode())
                flow = flow_json.get("flowSegmentData", {})
                
            actual_curr_speed = flow.get("currentSpeed") # km/h
            actual_free_speed = flow.get("freeFlowSpeed") # km/h
            travel_time = flow.get("currentTravelTime")
            confidence = flow.get("confidence")
            
            if actual_curr_speed is None or actual_free_speed is None:
                continue
                
            # --- TÍNH TOÁN THEO CÔNG THỨC NỘI SUY CỦA NHÓM ---
            # v_free đổi sang m/s:
            v_free_ms = actual_free_speed / 3.6
            t_free_sec = length_m / v_free_ms
            t_actual_sec = t_free_sec + delay_sec
            v_inferred_ms = length_m / t_actual_sec
            v_inferred_kmh = v_inferred_ms * 3.6
            
            # --- TÍNH TOÁN THEO MAGNITUDE ---
            v_mag_kmh = actual_free_speed * max(0.1, (1.0 - 0.22 * mag))
            
            abs_err = abs(v_inferred_kmh - actual_curr_speed)
            
            results.append({
                "id": idx + 1,
                "lat": lat,
                "lon": lon,
                "length_m": round(length_m, 1),
                "delay_s": delay_sec,
                "magnitude": mag,
                "free_flow_kmh": actual_free_speed,
                "actual_flow_kmh": actual_curr_speed,
                "inferred_kmh": round(v_inferred_kmh, 1),
                "magnitude_kmh": round(v_mag_kmh, 1),
                "abs_error_kmh": round(abs_err, 1),
                "confidence": confidence
            })
            print(f"  Điểm {idx+1}: Lat/Lng={lat:.4f},{lon:.4f} | Delay={delay_sec}s | Tốc độ thực Flow={actual_curr_speed} km/h | Tốc độ Nội suy={v_inferred_kmh:.1f} km/h")
        except Exception as e:
            print(f"  Lỗi gọi flow điểm {idx+1}: {e}")
            
    # Hiển thị bảng kết quả
    print("\n" + "=" * 105)
    print(f"{'STT':<4} | {'Độ dài':<7} | {'Trễ (s)':<7} | {'Mag':<4} | {'V_tự do':<8} | {'V_thực tế':<10} | {'V_nội suy':<10} | {'Sai số (km/h)':<14} | {'Độ tin cậy'}")
    print("-" * 105)
    for r in results:
        print(f"{r['id']:<4} | {r['length_m']:<7} | {r['delay_s']:<7} | {r['magnitude']:<4} | {r['free_flow_kmh']:<8} | {r['actual_flow_kmh']:<10} | {r['inferred_kmh']:<10} | {r['abs_error_kmh']:<14} | {r['confidence']}")
    print("=" * 105)
    
    if results:
        mae = sum(r["abs_error_kmh"] for r in results) / len(results)
        print(f"\n[*] SAI SỐ TUYỆT ĐỐI TRUNG BÌNH (MAE): {mae:.2f} km/h")
        
    with open("data/experiment_tomtom_validation.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("[*] Đã lưu kết quả thực nghiệm chi tiết vào: data/experiment_tomtom_validation.json\n")

if __name__ == "__main__":
    run_experiment()
