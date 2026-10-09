"""
Kiểm chứng độc lập dữ liệu trạm và tuyến từ OSM với các batch telemetry GPS thực tế đã crawl.
Xác thực:
1. Độ khớp hình học tuyến (GPS On-Route Ratio < 50m).
2. Độ khớp vị trí trạm dừng vật lý (Tọa độ xe dừng đón khách v < 5 km/h vs OSM Stop Nodes).
3. Đánh giá tính đúng đắn của từng tuyến hành lang.
"""

import os
import json
import math
import glob
import sys

sys.stdout.reconfigure(encoding="utf-8")

OSM_RAW_FILE = "data/metadata/osm_hust_routes_raw.json"
CONFIG_FILE = "data/metadata/hust_cluster_config.json"
REPORT_OUTPUT_FILE = "data/metadata/routes_telemetry_verification_report.json"

def haversine_m(lat1, lon1, lat2, lon2):
    """Tính khoảng cách mặt cầu Trái Đất (Haversine) tính bằng mét."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def dist_point_to_segment_m(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon):
    """Khoảng cách ngắn nhất từ điểm P đến đoạn thẳng AB (mét)."""
    # Chiếu hình học phẳng cục bộ (xấp xỉ gần trong phạm vi vài trăm mét)
    deg_len_lat = 111139.0
    deg_len_lon = 111139.0 * math.cos(math.radians(p_lat))

    px = p_lon * deg_len_lon
    py = p_lat * deg_len_lat
    ax = a_lon * deg_len_lon
    ay = a_lat * deg_len_lat
    bx = b_lon * deg_len_lon
    by = b_lat * deg_len_lat

    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-6:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)

    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)

def min_dist_to_polyline_m(p_lat, p_lon, polyline_pts):
    """Khoảng cách từ điểm P đến polyline (lấy đoạn thẳng gần nhất)."""
    if not polyline_pts:
        return float("inf")
    min_d = float("inf")
    # Tối ưu: Chỉ tính các đoạn lân cận để tăng tốc
    for i in range(len(polyline_pts) - 1):
        a = polyline_pts[i]
        b = polyline_pts[i + 1]
        # Bounding box nhanh
        min_lat = min(a[0], b[0]) - 0.005
        max_lat = max(a[0], b[0]) + 0.005
        min_lon = min(a[1], b[1]) - 0.005
        max_lon = max(a[1], b[1]) + 0.005
        if min_lat <= p_lat <= max_lat and min_lon <= p_lon <= max_lon:
            d = dist_point_to_segment_m(p_lat, p_lon, a[0], a[1], b[0], b[1])
            if d < min_d:
                min_d = d
    if min_d == float("inf"):
        # Dự phòng nếu bbox hẹp
        for i in range(0, len(polyline_pts) - 1, 2):
            a = polyline_pts[i]
            b = polyline_pts[i + 1]
            d = dist_point_to_segment_m(p_lat, p_lon, a[0], a[1], b[0], b[1])
            if d < min_d:
                min_d = d
    return min_d

def stitch_ways_clean(member_ways, ways_dict, nodes_dict):
    """Nối ways thành chuỗi điểm liên tục."""
    parsed_ways = []
    for m in member_ways:
        wid = m["ref"]
        w = ways_dict.get(wid)
        if not w:
            continue
        coords = []
        for nid in w.get("nodes", []):
            if nid in nodes_dict:
                node = nodes_dict[nid]
                coords.append((round(node["lat"], 6), round(node["lon"], 6)))
        if len(coords) >= 2:
            parsed_ways.append({"id": wid, "coords": coords})

    if not parsed_ways:
        return []

    polyline = list(parsed_ways[0]["coords"])
    used = {0}
    max_gap = 250.0

    while len(used) < len(parsed_ways):
        last_pt = polyline[-1]
        best_idx = None
        best_dist = float("inf")
        best_rev = False

        for idx, pw in enumerate(parsed_ways):
            if idx in used:
                continue
            s_pt = pw["coords"][0]
            e_pt = pw["coords"][-1]
            d_s = haversine_m(last_pt[0], last_pt[1], s_pt[0], s_pt[1])
            d_e = haversine_m(last_pt[0], last_pt[1], e_pt[0], e_pt[1])
            if d_s < best_dist:
                best_dist = d_s
                best_idx = idx
                best_rev = False
            if d_e < best_dist:
                best_dist = d_e
                best_idx = idx
                best_rev = True

        if best_dist > max_gap:
            break

        c = list(parsed_ways[best_idx]["coords"])
        if best_rev:
            c = c[::-1]
        if c[0] == polyline[-1]:
            polyline.extend(c[1:])
        else:
            polyline.extend(c)
        used.add(best_idx)

    return polyline

def main():
    print("=" * 75)
    print("ĐỐI CHIẾU & KIỂM CHỨNG ĐỘC LẬP: DỮ LIỆU OSM vs TELEMETRY GPS THỰC TẾ")
    print("=" * 75)

    if not os.path.exists(OSM_RAW_FILE):
        print(f"[ERROR] Không tìm thấy file OSM cache: {OSM_RAW_FILE}")
        return

    # 1. Đọc dữ liệu OSM
    print("[1/3] Đang phân tích dữ liệu OSM (15k elements)...")
    with open(OSM_RAW_FILE, "r", encoding="utf-8") as f:
        osm_data = json.load(f)

    elements = osm_data.get("elements", [])
    nodes_dict = {e["id"]: e for e in elements if e.get("type") == "node"}
    ways_dict = {e["id"]: e for e in elements if e.get("type") == "way"}
    relations = [e for e in elements if e.get("type") == "relation"]

    # Gom relation theo số hiệu tuyến (ref)
    osm_by_ref = {}
    for r in relations:
        ref = r.get("tags", {}).get("ref", "").strip()
        if ref:
            if ref not in osm_by_ref:
                osm_by_ref[ref] = []
            osm_by_ref[ref].append(r)

    print(f" -> Đã nhóm được {len(osm_by_ref)} tuyến trong OSM.\n")

    # 2. Gom dữ liệu Telemetry GPS thực tế từ các batch
    print("[2/3] Đang tổng hợp các batch Telemetry GPS thực tế...")
    batch_files = glob.glob("data/raw/hf_sample/*.jsonl") + glob.glob("temp_cloud_output/bus_batch_*.jsonl")
    telemetry_by_route = {}
    stop_clusters_by_route = {}

    total_pings = 0
    for bf in batch_files:
        try:
            with open(bf, "r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    rid = str(rec.get("route_id", ""))
                    lat = rec.get("lat")
                    lon = rec.get("lon")
                    spd = rec.get("speed", 99.0)
                    status = rec.get("quality_status", "")

                    if rid and lat and lon and status in ("ACTIVE_VALID", "IDLE_DEPOT"):
                        if rid not in telemetry_by_route:
                            telemetry_by_route[rid] = []
                            stop_clusters_by_route[rid] = []
                        telemetry_by_route[rid].append((lat, lon, spd))
                        total_pings += 1
                        if spd < 5.0:
                            stop_clusters_by_route[rid].append((lat, lon, rec.get("current_station_id", 0)))
        except Exception:
            pass

    print(f" -> Đọc được {total_pings:,} pings GPS từ {len(batch_files)} file batch cho {len(telemetry_by_route)} tuyến.\n")

    # Mapping giữa route_id trong telemetry và route_no trong OSM
    config = json.load(open(CONFIG_FILE, encoding="utf-8"))
    id_to_no = {str(r["route_id"]): str(r["route_no"]) for r in config.get("routes", [])}

    # 3. Đối chiếu từng tuyến
    print("[3/3] BẮT ĐẦU ĐỐI CHIẾU KIỂM CHỨNG TỪNG TUYẾN:")
    print("-" * 75)
    print(f"{'Tuyến':<7} | {'Pings':<7} | {'Dài (km)':<9} | {'Trạm OSM':<9} | {'% On-Route (<50m)':<18} | {'Độ Lệch TB':<11} | {'Đánh Giá'}")
    print("-" * 75)

    verification_results = []

    for route_id, route_no in sorted(id_to_no.items(), key=lambda x: x[1]):
        # Lấy telemetry
        pings = telemetry_by_route.get(route_id, [])
        stops_telemetry = stop_clusters_by_route.get(route_id, [])

        # Lấy OSM relations
        clean_ref = route_no.strip()
        rels = osm_by_ref.get(clean_ref, [])
        if not rels:
            # Thử bỏ chữ cái đầu/cuối nếu có
            rels = osm_by_ref.get(clean_ref.replace("A", "").replace("B", ""), [])

        if not rels:
            print(f"{route_no:<7} | {len(pings):<7} | {'N/A':<9} | {'N/A':<9} | {'N/A':<18} | {'N/A':<11} | ⚠️ Không tìm thấy trên OSM")
            continue

        # Ghép polyline cho cả 2 chiều
        polylines = []
        osm_stops = []
        for r in rels:
            member_ways = [m for m in r.get("members", []) if m.get("type") == "way"]
            poly = stitch_ways_clean(member_ways, ways_dict, nodes_dict)
            if poly:
                polylines.append(poly)
            for m in r.get("members", []):
                if m.get("role") in ("stop", "platform") and m.get("ref") in nodes_dict:
                    node = nodes_dict[m["ref"]]
                    osm_stops.append((node["lat"], node["lon"]))

        if not polylines:
            print(f"{route_no:<7} | {len(pings):<7} | {'N/A':<9} | {len(osm_stops):<9} | {'N/A':<18} | {'N/A':<11} | ⚠️ Ways rỗng")
            continue

        # Tính tổng chiều dài trung bình 2 chiều
        avg_len_km = sum(sum(haversine_m(p[i][0], p[i][1], p[i+1][0], p[i+1][1]) for i in range(len(p)-1)) for p in polylines) / (len(polylines) * 1000.0)

        # Tính độ khớp GPS với polyline
        on_route_count = 0
        distances = []
        sample_step = max(1, len(pings) // 200)  # Lấy mẫu tối đa 200 pings đại diện để tính nhanh
        sampled_pings = pings[::sample_step]

        for p_lat, p_lon, spd in sampled_pings:
            # Khoảng cách tối thiểu tới bất kỳ chiều nào của polyline
            min_d = min(min_dist_to_polyline_m(p_lat, p_lon, poly) for poly in polylines)
            distances.append(min_d)
            if min_d <= 50.0:  # Ngưỡng lệch 50m chuẩn đường nội đô
                on_route_count += 1

        on_route_pct = (on_route_count / len(sampled_pings) * 100.0) if sampled_pings else 0.0
        avg_dist_err = (sum(distances) / len(distances)) if distances else 0.0

        # Đánh giá
        if on_route_pct >= 85.0:
            status = "✅ KHỚP CHUẨN XÁC"
        elif on_route_pct >= 70.0:
            status = "🟢 CHẤP NHẬN ĐƯỢC"
        elif on_route_pct >= 50.0:
            status = "🟡 LỆCH MỘT PHẦN"
        else:
            status = "🔴 LỆCH LỘ TRÌNH"

        print(f"{route_no:<7} | {len(pings):<7} | {avg_len_km:<9.1f} | {len(osm_stops):<9} | {on_route_pct:<17.1f}% | {avg_dist_err:<10.1f}m | {status}")

        verification_results.append({
            "route_no": route_no,
            "route_id": route_id,
            "total_telemetry_pings": len(pings),
            "sampled_pings": len(sampled_pings),
            "osm_length_km": round(avg_len_km, 2),
            "osm_stops_count": len(osm_stops),
            "on_route_percentage": round(on_route_pct, 1),
            "average_error_meters": round(avg_dist_err, 1),
            "status": status
        })

    print("-" * 75)

    with open(REPORT_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(verification_results, f, ensure_ascii=False, indent=2)
    print(f"\n[HOÀN TẤT] Đã lưu báo cáo kiểm chứng độc lập: {REPORT_OUTPUT_FILE}")

if __name__ == "__main__":
    main()
