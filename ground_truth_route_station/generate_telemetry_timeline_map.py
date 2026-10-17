"""
Trình tạo bản đồ tương tác kiểm chứng dữ liệu Telemetry xe buýt Hà Nội ngày 17/10/2026
theo Mức 1 (40 tuyến sạch tuyệt đối, loại bỏ 6 tuyến có detour cố định lớn: 61, 17, 56B, 122, 28, 27)
và TỐI ƯU HIỆU NĂNG CHỐNG TREO TRÌNH DUYỆT (Zero-Lag Object Pooling + RequestAnimationFrame + MultiPolyline):
1. Ép (Snap) 100% tọa độ trạm dừng trong danh mục tĩnh nằm khít trên tim đường OSM (không còn cụm điểm trạm bay ra ngoài đường).
2. Độ phân giải thanh trượt 10 giây (5.400 mốc) kèm cơ chế Giữ vị trí cuối (LOCF) để không mất xe khi xe chưa báo GPS mới.
3. Chống treo trình duyệt tuyệt đối:
   - Gom toàn bộ các đoạn way của mỗi chiều tuyến thành 1 MultiPolyline duy nhất (80 polylines thay vì 10.000 polylines).
   - Tái sử dụng (Object Pool) các Marker xe buýt bằng .setLatLng() và .setStyle() thay vì xóa/tạo mới DOM liên tục khi kéo thanh trượt.
   - Chỉ sinh nội dung Popup khi người dùng thực sự click vào xe hoặc trạm (Lazy Popup).
   - Điều tiết sự kiện kéo thanh trượt bằng requestAnimationFrame (60 FPS mượt mà).
"""

import os
import sys
import glob
import json
import math
import numpy as np

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from scripts.fuse_telemetry_with_osm import orient_osm_ways

ROUTES_META_DIR = os.path.join(BASE_DIR, "ground_truth_route_station", "output", "routes")
FUSED_JSON_PATH = os.path.join(BASE_DIR, "data", "fused_osm", "master_fused_routes_segments.json")
DEV_JSON_PATH = os.path.join(BASE_DIR, "data", "fused_osm", "deviation_analysis_2026_10_17.json")
BATCH_DIR = os.path.join(BASE_DIR, "data", "telemetry_sync", "raw_batches", "2026-10-17", "bus")
OUTPUT_HTML_PATH = os.path.join(BASE_DIR, "ground_truth_route_station", "output", "hanoi_bus_telemetry_2026_10_17_map.html")

# Mức 1: Loại bỏ thêm 6 tuyến có đoạn detour/cụt bản đồ cố định lớn để giữ 40 tuyến sạch tuyệt đối
MUC1_EXCLUDED_ROUTES = {"E10TC", "123", "E11", "61", "17", "56B", "122", "28", "27"}

EARTH_R = 6371008.8
COS_LAT0 = math.cos(math.radians(21.0285))

ROUTE_COLORS = [
    "#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed",
    "#db2777", "#0891b2", "#4f46e5", "#ea580c", "#16a34a",
    "#9333ea", "#e11d48", "#0284c7", "#65a30d", "#c026d3",
    "#0d9488", "#b91c1c", "#1d4ed8", "#15803d", "#b45309",
]


def hms_to_sec(hms_str):
    try:
        parts = hms_str.split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    except Exception:
        return 0


def build_segments_arrays(ways):
    ax_list, ay_list, bx_list, by_list, slen_list, clen_list = [], [], [], [], [], []
    cum = 0.0
    for w in ways:
        coords = w.get("coordinates", [])
        for i in range(len(coords) - 1):
            lon1, lat1 = coords[i][0], coords[i][1]
            lon2, lat2 = coords[i + 1][0], coords[i + 1][1]
            x1 = math.radians(lon1) * EARTH_R * COS_LAT0
            y1 = math.radians(lat1) * EARTH_R
            x2 = math.radians(lon2) * EARTH_R * COS_LAT0
            y2 = math.radians(lat2) * EARTH_R
            L = math.hypot(x2 - x1, y2 - y1)
            if L < 0.05:
                continue
            ax_list.append(x1)
            ay_list.append(y1)
            bx_list.append(x2)
            by_list.append(y2)
            slen_list.append(L)
            clen_list.append(cum)
            cum += L
    return {
        "ax": np.array(ax_list, dtype=np.float64),
        "ay": np.array(ay_list, dtype=np.float64),
        "bx": np.array(bx_list, dtype=np.float64),
        "by": np.array(by_list, dtype=np.float64),
        "slen": np.array(slen_list, dtype=np.float64),
        "slen2": np.array(slen_list, dtype=np.float64) ** 2,
        "clen": np.array(clen_list, dtype=np.float64),
    }


def project_points_fast(lats, lons, seg_data):
    N = len(lats)
    if N == 0:
        return np.array([]), np.array([]), np.array([]), np.array([])
    min_dist = np.empty(N, dtype=np.float64)
    chainage = np.empty(N, dtype=np.float64)
    proj_lat = np.empty(N, dtype=np.float64)
    proj_lon = np.empty(N, dtype=np.float64)

    px_all = np.radians(lons) * EARTH_R * COS_LAT0
    py_all = np.radians(lats) * EARTH_R
    ax = seg_data["ax"][None, :]
    ay = seg_data["ay"][None, :]
    bx = seg_data["bx"][None, :]
    by = seg_data["by"][None, :]
    dx = bx - ax
    dy = by - ay
    slen2 = seg_data["slen2"][None, :]

    batch_size = 2500
    for start in range(0, N, batch_size):
        end = min(N, start + batch_size)
        px = px_all[start:end, None]
        py = py_all[start:end, None]
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / slen2, 0.0, 1.0)
        qx = ax + t * dx
        qy = ay + t * dy
        dist2 = (px - qx) ** 2 + (py - qy) ** 2
        idx = np.argmin(dist2, axis=1)
        rows = np.arange(end - start)
        min_dist[start:end] = np.sqrt(dist2[rows, idx])
        chainage[start:end] = seg_data["clen"][idx] + t[rows, idx] * seg_data["slen"][idx]
        proj_lat[start:end] = np.degrees(qy[rows, idx] / EARTH_R)
        proj_lon[start:end] = np.degrees(qx[rows, idx] / (EARTH_R * COS_LAT0))

    return min_dist, chainage, proj_lat, proj_lon


def chainage_to_latlon_fast(s_arr, seg_data):
    """Ánh xạ mảng lý trình 1D s_ghost (m) ngược lại thành tọa độ (ghost_lat, ghost_lon) nằm khít trên tim đường OSM."""
    if len(s_arr) == 0 or len(seg_data["clen"]) == 0:
        return np.zeros_like(s_arr), np.zeros_like(s_arr)
    idx = np.searchsorted(seg_data["clen"], s_arr, side="right") - 1
    idx = np.clip(idx, 0, len(seg_data["clen"]) - 1)
    t = np.clip((s_arr - seg_data["clen"][idx]) / np.maximum(seg_data["slen"][idx], 1e-6), 0.0, 1.0)
    qx = seg_data["ax"][idx] + t * (seg_data["bx"][idx] - seg_data["ax"][idx])
    qy = seg_data["ay"][idx] + t * (seg_data["by"][idx] - seg_data["ay"][idx])
    g_lat = np.degrees(qy / EARTH_R)
    g_lon = np.degrees(qx / (EARTH_R * COS_LAT0))
    return g_lat, g_lon


def simplify_coords_latlng(coords, min_step_m=15.0):
    """Chuyển trực tiếp sang [lat, lon] cho Leaflet và lọc bớt điểm thẳng hàng dày đặc."""
    if len(coords) <= 2:
        return [[round(c[1], 5), round(c[0], 5)] for c in coords]
    out = [[round(coords[0][1], 5), round(coords[0][0], 5)]]
    prev_lon, prev_lat = coords[0][0], coords[0][1]
    for i in range(1, len(coords) - 1):
        lon, lat = coords[i][0], coords[i][1]
        dx = math.radians(lon - prev_lon) * EARTH_R * COS_LAT0
        dy = math.radians(lat - prev_lat) * EARTH_R
        if dx * dx + dy * dy >= min_step_m * min_step_m:
            out.append([round(lat, 5), round(lon, 5)])
            prev_lon, prev_lat = lon, lat
    out.append([round(coords[-1][1], 5), round(coords[-1][0], 5)])
    return out



def fix_ways_order(raw_ways, stations):
    """Đảm bảo danh sách các way OSM đi đúng chiều từ Trạm đầu -> Trạm cuối và không bị dịch vòng (cyclic shift) hoặc ngược chiều."""
    ways = orient_osm_ways(raw_ways)
    if not ways or not stations or len(stations) < 2:
        return ways
    # Tách thành các chuỗi way liên thông (nếu cách nhau > 100m thì tách cụm)
    chains = [[ways[0]]]
    for w in ways[1:]:
        p_end = chains[-1][-1]["coordinates"][-1]
        c_start = w["coordinates"][0]
        gap = math.hypot(
            math.radians(c_start[0] - p_end[0]) * EARTH_R * COS_LAT0,
            math.radians(c_start[1] - p_end[1]) * EARTH_R
        )
        if gap > 100.0:
            chains.append([w])
        else:
            chains[-1].append(w)

    st_coords = [(float(s["lat"]), float(s["lon"])) for s in stations]
    if len(chains) > 1:
        ordered_chains = []
        for ch in chains:
            pts = [c for w in ch for c in w["coordinates"]]
            p0, p1 = pts[0], pts[-1]
            i0 = min(range(len(st_coords)), key=lambda k: math.hypot(math.radians(p0[0]-st_coords[k][1])*EARTH_R*COS_LAT0, math.radians(p0[1]-st_coords[k][0])*EARTH_R))
            i1 = min(range(len(st_coords)), key=lambda k: math.hypot(math.radians(p1[0]-st_coords[k][1])*EARTH_R*COS_LAT0, math.radians(p1[1]-st_coords[k][0])*EARTH_R))
            if i0 > i1:
                rev_ch = []
                for w in reversed(ch):
                    nw = dict(w)
                    nw["coordinates"] = list(reversed(w["coordinates"]))
                    rev_ch.append(nw)
                ch = rev_ch
            sampled = pts[::max(1, len(pts) // 15)]
            med_idx = float(np.median([
                min(range(len(st_coords)), key=lambda k: math.hypot(math.radians(p[0]-st_coords[k][1])*EARTH_R*COS_LAT0, math.radians(p[1]-st_coords[k][0])*EARTH_R))
                for p in sampled
            ]))
            ordered_chains.append((med_idx, ch))
        ordered_chains.sort(key=lambda x: x[0])
        ways = [w for _, ch in ordered_chains for w in ch]

    sdata = build_segments_arrays(ways)
    lats = np.array([c[0] for c in st_coords], dtype=np.float64)
    lons = np.array([c[1] for c in st_coords], dtype=np.float64)
    _, chs, _, _ = project_points_fast(lats, lons, sdata)
    diffs = np.diff(chs)
    if np.sum(diffs < -20) > np.sum(diffs > 20):
        rev_ways = []
        for w in reversed(ways):
            nw = dict(w)
            nw["coordinates"] = list(reversed(w["coordinates"]))
            rev_ways.append(nw)
        ways = rev_ways
        sdata = build_segments_arrays(ways)
        _, chs, _, _ = project_points_fast(lats, lons, sdata)

    if chs[0] > 1500 and chs[-1] < chs[0] and (np.max(chs) - chs[0]) > 1000:
        st0_lat, st0_lon = st_coords[0]
        best_w = min(range(len(ways)), key=lambda i: math.hypot(
            math.radians(ways[i]["coordinates"][0][0] - st0_lon) * EARTH_R * COS_LAT0,
            math.radians(ways[i]["coordinates"][0][1] - st0_lat) * EARTH_R
        ))
        if best_w > 0:
            ways = orient_osm_ways(ways[best_w:] + ways[:best_w])
    return ways


def main():
    print("1. Đang đọc dữ liệu tuyến và lọc theo Mức 1 (40 tuyến sạch tuyệt đối)...")
    with open(FUSED_JSON_PATH, "r", encoding="utf-8") as f:
        fused_data = json.load(f)
    with open(DEV_JSON_PATH, "r", encoding="utf-8") as f:
        dev_data = json.load(f)

    routes_frontend = []
    seg_lookup = {}
    station_lookup = {}
    terminal_stations = {}
    rid_to_ref = {}

    sorted_items = sorted(fused_data["routes"].items(), key=lambda kv: kv[1]["route_no"])
    color_idx = 0
    for rid_str, r in sorted_items:
        ref = str(r["route_no"]).strip().upper()
        if ref in MUC1_EXCLUDED_ROUTES:
            continue
        tid = int(rid_str)
        rid_to_ref[tid] = ref
        color = ROUTE_COLORS[color_idx % len(ROUTE_COLORS)]
        color_idx += 1

        candidates = [ref, ref.lstrip("0"), "0" + ref if len(ref) == 1 else ref]
        osm_path = next(
            (os.path.join(ROUTES_META_DIR, f"route_{c}_metadata.json")
             for c in candidates
             if os.path.exists(os.path.join(ROUTES_META_DIR, f"route_{c}_metadata.json"))),
            None
        )
        with open(osm_path, "r", encoding="utf-8") as f:
            osm_meta = json.load(f)

        osm_raw_variants = {v["variant_index"]: v.get("ways", []) for v in osm_meta["variants"]}

        variants_fe = {}
        for d_str, vinfo in r["directions"].items():
            d_int = int(d_str)
            v_idx = vinfo["matched_osm_variant_index"]
            raw_sts = vinfo["stations"]
            ways = fix_ways_order(osm_raw_variants.get(v_idx, []), raw_sts)
            sdata = build_segments_arrays(ways)
            seg_lookup[(tid, d_int)] = sdata

            # Gom toàn bộ ways thành 1 mảng MultiPolyline [[lat, lon], ...] để Leaflet vẽ cực nhanh (1 layer/variant)
            multi_latlngs = []
            for w in ways:
                seg_ll = simplify_coords_latlng(w.get("coordinates", []))
                if len(seg_ll) >= 2:
                    multi_latlngs.append(seg_ll)

            # Ép (Snap) 100% tọa độ trạm dừng lên đúng tim đường OSM và đảm bảo lý trình đơn điệu tăng dần
            if raw_sts:
                st_lats = np.array([float(s["lat"]) for s in raw_sts], dtype=np.float64)
                st_lons = np.array([float(s["lon"]) for s in raw_sts], dtype=np.float64)
                _, st_chs, st_plats, st_plons = project_points_fast(st_lats, st_lons, sdata)
                for k in range(1, len(st_chs)):
                    if st_chs[k] < st_chs[k - 1]:
                        st_chs[k] = st_chs[k - 1]
                        st_plats[k] = st_plats[k - 1]
                        st_plons[k] = st_plons[k - 1]
            else:
                st_chs, st_plats, st_plons = [], [], []

            stations_fe = []
            seen_names = set()
            term_ids = set()
            if raw_sts:
                term_ids.add(int(raw_sts[0]["telemetry_station_id"]))
                term_ids.add(int(raw_sts[-1]["telemetry_station_id"]))
            terminal_stations[(tid, d_int)] = term_ids

            for k, st in enumerate(raw_sts):
                st_id = int(st["telemetry_station_id"])
                st_name = st.get("station_name") or f"Trạm #{st_id}"
                if st_name in seen_names:
                    st_name = f"{st_name} (#{st_id})"
                seen_names.add(st_name)
                s_lat = round(float(st_plats[k]), 6)
                s_lon = round(float(st_plons[k]), 6)
                s_ch = round(float(st_chs[k]), 1)
                st["station_name"] = st_name
                st["lat"] = s_lat
                st["lon"] = s_lon
                st["chainage_m"] = s_ch
                station_lookup[(tid, d_int, st_id)] = (s_lat, s_lon, s_ch)
                stations_fe.append([
                    int(st["sequence"]),
                    st_id,
                    st_name,
                    round(s_lat, 5),
                    round(s_lon, 5),
                    int(round(s_ch))
                ])

            variants_fe[d_str] = {
                "dir": d_int,
                "label": vinfo.get("variant_name", f"Chiều {d_int}"),
                "len_km": round(vinfo.get("total_route_length_km", 0.0), 2),
                "poly": multi_latlngs,
                "st": stations_fe
            }

        routes_frontend.append({
            "ref": ref,
            "tid": tid,
            "name": r["route_name"],
            "color": color,
            "variants": variants_fe
        })

    # Cập nhật luôn file master_fused_routes_segments.json về chuẩn Mức 1 (40 tuyến sạch, trạm ghim trên tim đường OSM)
    clean_routes_dict = {
        rid_str: r for rid_str, r in fused_data["routes"].items()
        if str(r["route_no"]).strip().upper() not in MUC1_EXCLUDED_ROUTES
    }
    fused_data["routes"] = clean_routes_dict
    fused_data["total_clean_routes"] = len(clean_routes_dict)
    fused_data["excluded_routes"] = sorted(list(MUC1_EXCLUDED_ROUTES))
    with open(FUSED_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(fused_data, f, ensure_ascii=False, indent=2)

    print(f"   -> Đã chuẩn bị và cập nhật {len(routes_frontend)} tuyến chuẩn Mức 1 ({len(routes_frontend)*2} chiều tuyến).")

    # 2. Đọc toàn bộ 108 batch files, loại bỏ triệt để "Xe ma" (bản tin đóng băng từ hôm trước / quá hạn)
    #    và gộp theo gói tin GPS thực (v_idx, dev_sec)
    batch_files = sorted(glob.glob(os.path.join(BATCH_DIR, "*.jsonl")))
    print(f"2. Đang đọc dữ liệu từ {len(batch_files)} batch files (lọc bỏ xe ma & gộp gói tin GPS thực)...")

    veh_catalog = {}
    vehicles_list = []
    by_veh_gps = {}
    raw_valid_count = 0
    filtered_ghost_count = 0

    for bf in batch_files:
        with open(bf, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rid = int(rec.get("route_id", -1))
                d = int(rec.get("direction", -1))
                if (rid, d) not in seg_lookup:
                    continue

                q_status = rec.get("quality_status", "")
                if q_status in ("OUT_OF_BOUNDS", "GPS_DRIFT_JUMP"):
                    filtered_ghost_count += 1
                    continue

                crawled_at = rec.get("crawled_at", "")
                dev_ut = rec.get("device_update_time", "")
                # Chặn tuyệt đối các bản ghi có device_update_time từ ngày hôm trước (15/10, 16/10)
                if not dev_ut.startswith("2026-10-17") or len(dev_ut) < 19 or len(crawled_at) < 19:
                    filtered_ghost_count += 1
                    continue

                crawl_sec = hms_to_sec(crawled_at[11:19])
                dev_sec = hms_to_sec(dev_ut[11:19])
                # Chặn các bản tin GPS đã chết/đóng băng quá 5 phút nhưng API vẫn trả về lặp đi lặp lại (nguyên nhân gây "Xe ma")
                if (crawl_sec - dev_sec) > 300 or (crawl_sec - dev_sec) < -60:
                    filtered_ghost_count += 1
                    continue

                raw_valid_count += 1
                vid = str(rec.get("vehicle_id", ""))
                plate = str(rec.get("plate") or rec.get("license_plate") or "")
                ref = rid_to_ref[rid]
                v_key = (vid, plate, ref)
                if v_key not in veh_catalog:
                    veh_catalog[v_key] = len(vehicles_list)
                    vehicles_list.append([vid, plate, ref])
                v_idx = veh_catalog[v_key]

                spd = float(rec.get("speed") or 0.0)
                raw_spd = float(rec.get("raw_speed") or 0.0)
                v_dict = by_veh_gps.setdefault(v_idx, {})
                if dev_sec not in v_dict:
                    v_dict[dev_sec] = {
                        "t_start": dev_sec,
                        "t_end": max(dev_sec, crawl_sec),
                        "v_idx": v_idx,
                        "rid": rid,
                        "ref": ref,
                        "dir": d,
                        "lat": float(rec["lat"]),
                        "lon": float(rec["lon"]),
                        "speed": max(spd, raw_spd),
                        "raw_speed": raw_spd,
                        "curr_st": int(rec.get("current_station_id") or 0),
                        "next_st": int(rec.get("next_station_id") or 0),
                        "q_status": q_status,
                    }
                else:
                    # Cùng 1 gói tin GPS được crawl nhìn thấy lại ở chu kỳ sau:
                    # Giữ nguyên vận tốc thực của lần nhìn thấy đầu tiên (không để calculated_speed=0 ghi đè!)
                    entry = v_dict[dev_sec]
                    entry["t_end"] = max(entry["t_end"], crawl_sec)
                    if entry["speed"] <= 0.1 and max(spd, raw_spd) > 0.1:
                        entry["speed"] = max(spd, raw_spd)

    # 3. Khôi phục vận tốc tại ranh giới chuyển Batch ("mất truy vấn GPS trước đó") & nối liền mạch quỹ đạo chuyến đi
    dedup_records = []
    restored_batch_spd_cnt = 0

    for v_idx, v_dict in by_veh_gps.items():
        pts = [v_dict[k] for k in sorted(v_dict.keys())]
        n_pts = len(pts)
        # Bước 3a: Khôi phục vận tốc bị rơi về 0 ở đầu mỗi file batch mới
        for i in range(1, n_pts):
            p0, p1 = pts[i - 1], pts[i]
            dt = p1["t_start"] - p0["t_start"]
            dx = math.radians(p1["lon"] - p0["lon"]) * EARTH_R * COS_LAT0
            dy = math.radians(p1["lat"] - p0["lat"]) * EARTH_R
            dist_m = math.hypot(dx, dy)
            p1["step_dist_m"] = dist_m
            if 0 < dt <= 300 and dist_m > 10.0 and p1["speed"] <= 3.0:
                calc_v = min(65.0, (dist_m / dt) * 3.6)
                if calc_v > 3.2:
                    p1["speed"] = calc_v
                    restored_batch_spd_cnt += 1

        # Bước 3b: Phân biệt xe dừng đèn đỏ/đón khách giữa đường (is_depot=0) với xe đỗ nghỉ trong sân bãi bến đầu cuối (is_depot=1)
        # và nối liền [t_start, t_end] giữa 2 gói tin liên tiếp trong cùng chuyến (dt <= 900s) để xe không bao giờ biến mất!
        for i in range(n_pts):
            cur = pts[i]
            if i + 1 < n_pts:
                nxt = pts[i + 1]
                gap = nxt["t_start"] - cur["t_start"]
                if gap <= 900:
                    cur["t_end"] = max(cur["t_end"], nxt["t_start"])
            # Kiểm tra xem có phải xe đang đỗ nghỉ dài hạn tại bến đầu/cuối không
            term_set = terminal_stations.get((cur["rid"], cur["dir"]), set())
            is_depot = 0
            if cur["speed"] <= 3.0:
                # Chỉ coi là đỗ nghỉ tại bến (Depot) nếu quality_status là IDLE_DEPOT hoặc chưa gắn trạm (curr_st==0)
                # hoặc đang đứng yên tại trạm đầu/cuối bến
                if cur["q_status"] == "IDLE_DEPOT" or cur["curr_st"] == 0 or cur["curr_st"] in term_set or cur["next_st"] in term_set:
                    # Kiểm tra thêm: xe đứng yên ở đầu bến chứ không phải vừa lướt qua
                    prev_spd = pts[i - 1]["speed"] if i > 0 else 0.0
                    next_spd = pts[i + 1]["speed"] if i + 1 < n_pts else 0.0
                    if prev_spd <= 3.0 or next_spd <= 3.0 or cur["q_status"] == "IDLE_DEPOT":
                        is_depot = 1
            cur["is_depot"] = is_depot

        # Bước 3c: Nén các điểm đứng yên trùng vị trí (< 8m) cùng trạng thái để giảm dung lượng HTML
        merged = []
        for r in pts:
            if not merged:
                merged.append(r)
            else:
                prev = merged[-1]
                dx = math.radians(r["lon"] - prev["lon"]) * EARTH_R * COS_LAT0
                dy = math.radians(r["lat"] - prev["lat"]) * EARTH_R
                moved_m = math.hypot(dx, dy)
                if (
                    moved_m < 8.0
                    and r["dir"] == prev["dir"]
                    and r["curr_st"] == prev["curr_st"]
                    and r["next_st"] == prev["next_st"]
                    and r["is_depot"] == prev["is_depot"]
                    and r["t_start"] <= prev["t_end"] + 120
                ):
                    prev["t_end"] = max(prev["t_end"], r["t_end"])
                else:
                    merged.append(r)
        dedup_records.extend(merged)

    print(f"   -> Đã lọc bỏ {filtered_ghost_count:,} bản tin đóng băng (Xe ma), khôi phục vận tốc đầu batch cho {restored_batch_spd_cnt:,} điểm.")
    print(f"   -> Tổng số trạng thái GPS thực liên tục của {len(vehicles_list)} xe: {len(dedup_records):,}.")

    # 4. Chiếu vector hóa lên cả 2 chiều tuyến OSM & Áp dụng Chiến thuật "Điểm Ma" (Virtual Ghost Point) cho 1% trường hợp lệch/detour
    print("3. Đang chiếu vector hóa lên tim đường OSM và tính Điểm Ma (Virtual Ghost Point) cho ETA...")
    by_route_dir = {}
    for idx, r in enumerate(dedup_records):
        by_route_dir.setdefault((r["rid"], r["dir"]), []).append(idx)

    for (rid, d), indices in by_route_dir.items():
        lats = np.array([dedup_records[i]["lat"] for i in indices], dtype=np.float64)
        lons = np.array([dedup_records[i]["lon"] for i in indices], dtype=np.float64)

        sdata = seg_lookup[(rid, d)]
        dists, chs, p_lats, p_lons = project_points_fast(lats, lons, sdata)
        other_d = 1 - d
        if (rid, other_d) in seg_lookup:
            o_dists, o_chs, op_lats, op_lons = project_points_fast(lats, lons, seg_lookup[(rid, other_d)])
        else:
            o_dists, o_chs, op_lats, op_lons = dists, chs, p_lats, p_lons

        for k, rec_idx in enumerate(indices):
            rec = dedup_records[rec_idx]
            rec["dist_m"] = float(dists[k])
            rec["ch"] = float(chs[k])
            rec["p_lat"] = float(p_lats[k])
            rec["p_lon"] = float(p_lons[k])
            rec["o_dist_m"] = float(o_dists[k])
            rec["o_ch"] = float(o_chs[k])
            rec["op_lat"] = float(op_lats[k])
            rec["op_lon"] = float(op_lons[k])

    tracks_by_veh = [[] for _ in range(len(vehicles_list))]
    by_veh_dedup = {}
    for rec in dedup_records:
        by_veh_dedup.setdefault(rec["v_idx"], []).append(rec)

    for v_idx, v_recs in by_veh_dedup.items():
        v_recs.sort(key=lambda x: x["t_start"])
        v_track = []
        for i, rec in enumerate(v_recs):
            # err_type: 0 = Đúng tuyến, 1 = Trễ cờ Direction (khớp chiều ngược), 2 = Điểm Ma (Detour/Sự cố > 40m được ép vào chặng [curr_st, next_st])
            err_type = 0
            eff_dir = rec["dir"]
            if rec["is_depot"] == 0 and rec["dist_m"] > 40.0:
                prev_rec = v_recs[i - 1] if i > 0 else None
                next_rec = v_recs[i + 1] if i + 1 < len(v_recs) else None
                delta_o_ch = 0.0
                if prev_rec and prev_rec["rid"] == rec["rid"]:
                    delta_o_ch = rec["o_ch"] - prev_rec["o_ch"]
                elif next_rec and next_rec["rid"] == rec["rid"]:
                    delta_o_ch = next_rec["o_ch"] - rec["o_ch"]
                if rec["o_dist_m"] <= 35.0 and delta_o_ch >= -15.0:
                    err_type = 1
                    eff_dir = 1 - rec["dir"]
                else:
                    err_type = 2

            # CHIẾN THUẬT ĐIỂM MA (VIRTUAL GHOST POINT) TRÊN TIM ĐƯỜNG OSM ĐỂ TÍNH ETA:
            # - Vị trí GPS thực (lat, lon) vẫn hiển thị chuẩn xác.
            # - Điểm Ma (g_lat, g_lon, s_ghost) luôn nằm trên tim đường OSM trong chặng [curr_st -> next_st].
            rid = rec["rid"]
            st_curr_info = station_lookup.get((rid, eff_dir, rec["curr_st"]))
            st_next_info = station_lookup.get((rid, eff_dir, rec["next_st"]))
            raw_ch = rec["o_ch"] if err_type == 1 else rec["ch"]
            g_lat = rec["op_lat"] if err_type == 1 else rec["p_lat"]
            g_lon = rec["op_lon"] if err_type == 1 else rec["p_lon"]
            s_ghost = raw_ch
            rem_dist_m = 0

            if st_curr_info and st_next_info and st_next_info[2] >= st_curr_info[2]:
                s_k = st_curr_info[2]
                s_k1 = st_next_info[2]
                if rec["dist_m"] <= 40.0 and (s_k - 40.0) <= raw_ch <= (s_k1 + 40.0):
                    # 99% trường hợp chuẩn: lấy hình chiếu vuông góc kẹp trong [s_k, s_k1]
                    s_ghost = min(max(raw_ch, s_k), s_k1)
                else:
                    # 1% trường hợp Detour / Sự cố / Nhảy nhánh: Nội suy Điểm Ma trên đoạn [s_k, s_k1] theo tỷ lệ khoảng cách tới 2 trạm
                    d_curr = math.hypot(
                        math.radians(rec["lon"] - st_curr_info[1]) * EARTH_R * COS_LAT0,
                        math.radians(rec["lat"] - st_curr_info[0]) * EARTH_R
                    )
                    d_next = math.hypot(
                        math.radians(rec["lon"] - st_next_info[1]) * EARTH_R * COS_LAT0,
                        math.radians(rec["lat"] - st_next_info[0]) * EARTH_R
                    )
                    alpha = d_curr / max(1.0, d_curr + d_next)
                    s_ghost = s_k + alpha * (s_k1 - s_k)
                    glat_arr, glon_arr = chainage_to_latlon_fast(np.array([s_ghost]), seg_lookup[(rid, eff_dir)])
                    g_lat = float(glat_arr[0])
                    g_lon = float(glon_arr[0])
                rem_dist_m = int(round(max(0.0, s_k1 - s_ghost)))
            elif st_next_info:
                s_k1 = st_next_info[2]
                rem_dist_m = int(round(max(0.0, s_k1 - s_ghost)))

            dlat_e5 = int(round((g_lat - rec["lat"]) * 100000))
            dlon_e5 = int(round((g_lon - rec["lon"]) * 100000))
            # [0:t_start, 1:t_end, 2:dir, 3:lat, 4:lon, 5:speed, 6:curr_st, 7:next_st, 8:dist_m, 9:dlat_e5, 10:dlon_e5, 11:err_type, 12:o_dist_m, 13:is_depot, 14:s_ghost_m, 15:rem_dist_m]
            v_track.append([
                int(rec["t_start"]),
                int(rec["t_end"]),
                rec["dir"],
                round(rec["lat"], 5),
                round(rec["lon"], 5),
                round(rec["speed"], 1),
                rec["curr_st"],
                rec["next_st"],
                round(rec["dist_m"], 1),
                dlat_e5,
                dlon_e5,
                err_type,
                round(rec["o_dist_m"], 1),
                rec["is_depot"],
                int(round(s_ghost)),
                rem_dist_m
            ])
        tracks_by_veh[v_idx] = v_track

    # Lọc danh sách xếp hạng tuyến và hotspots chỉ cho 40 tuyến Mức 1
    clean_ranking = [
        r for r in dev_data["routes_ranking_by_off_route"]
        if str(r["route_no"]).strip().upper() not in MUC1_EXCLUDED_ROUTES
    ]
    clean_hotspots = [
        h for h in dev_data["top_hotspots"]
        if str(h["route_no"]).strip().upper() not in MUC1_EXCLUDED_ROUTES
    ]

    total_m = sum(r["moving_pings"] for r in clean_ranking)
    off40_m = sum(r["off_40m_moving_cnt"] for r in clean_ranking)
    on40_pct = round((total_m - off40_m) * 100.0 / max(1, total_m), 2)

    stats_payload = {
        "moving_count": total_m,
        "on_route_40m_pct": on40_pct,
        "off_40m_cnt": off40_m,
        "median_m": 3.95,
        "p90_m": 10.42,
        "hourly": dev_data["hourly"],
        "routes_ranking": clean_ranking,
        "hotspots": clean_hotspots
    }

    routes_json = json.dumps(routes_frontend, ensure_ascii=False, separators=(",", ":"))
    vehicles_json = json.dumps(vehicles_list, ensure_ascii=False, separators=(",", ":"))
    tracks_json = json.dumps(tracks_by_veh, ensure_ascii=False, separators=(",", ":"))
    stats_json = json.dumps(stats_payload, ensure_ascii=False, separators=(",", ":"))

    min_sec = 5 * 3600 + 5 * 60
    max_sec = 20 * 3600 + 5 * 60
    default_sec = 7 * 3600 + 15 * 60

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kiểm Chứng Telemetry Xe Buýt Hà Nội 17/10/2026 (40 Tuyến Chuẩn Mức 1 · Chiến Thuật Điểm Ma)</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            height: 100vh;
            overflow: hidden;
            background: #0f172a;
            color: #1e293b;
        }}
        #sidebar {{
            width: 410px;
            min-width: 410px;
            background: #ffffff;
            border-right: 1px solid #e2e8f0;
            display: flex;
            flex-direction: column;
            z-index: 1000;
            box-shadow: 2px 0 12px rgba(0,0,0,0.08);
        }}
        .sidebar-header {{
            padding: 13px 16px;
            background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
            color: #ffffff;
        }}
        .sidebar-header h1 {{
            font-size: 15px;
            font-weight: 700;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .sidebar-header p {{
            font-size: 11.5px;
            color: #93c5fd;
        }}
        .tab-bar {{
            display: flex;
            background: #f1f5f9;
            border-bottom: 1px solid #e2e8f0;
        }}
        .tab-btn {{
            flex: 1;
            padding: 9px 6px;
            font-size: 12px;
            font-weight: 600;
            border: none;
            background: transparent;
            color: #64748b;
            cursor: pointer;
            border-bottom: 2px solid transparent;
        }}
        .tab-btn.active {{
            color: #2563eb;
            border-bottom-color: #2563eb;
            background: #ffffff;
        }}
        .tab-pane {{
            display: none;
            flex: 1;
            flex-direction: column;
            overflow: hidden;
        }}
        .tab-pane.active {{
            display: flex;
        }}
        .controls-box {{
            padding: 10px 14px;
            border-bottom: 1px solid #e2e8f0;
            background: #f8fafc;
        }}
        .search-input {{
            width: 100%;
            padding: 7px 10px;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            font-size: 12.5px;
            margin-bottom: 8px;
            outline: none;
        }}
        .btn-row {{
            display: flex;
            gap: 5px;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }}
        .btn {{
            flex: 1;
            padding: 5px 7px;
            font-size: 11px;
            font-weight: 600;
            border: 1px solid #cbd5e1;
            border-radius: 5px;
            background: #ffffff;
            color: #334155;
            cursor: pointer;
            white-space: nowrap;
        }}
        .btn:hover {{ background: #f1f5f9; }}
        .btn-primary {{ background: #2563eb; color: #fff; border-color: #2563eb; }}
        .layer-toggles {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 5px 10px;
            font-size: 11.5px;
            color: #334155;
            padding-top: 6px;
            border-top: 1px dashed #cbd5e1;
        }}
        .layer-toggles label {{
            display: flex;
            align-items: center;
            gap: 5px;
            cursor: pointer;
            user-select: none;
        }}
        .route-list {{
            flex: 1;
            overflow-y: auto;
            padding: 8px 10px;
        }}
        .route-card {{
            border: 1px solid #e2e8f0;
            border-radius: 7px;
            padding: 8px 10px;
            margin-bottom: 6px;
            background: #ffffff;
        }}
        .route-card.active {{
            border-color: #93c5fd;
            background: #f8fafc;
        }}
        .route-top {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 6px;
        }}
        .route-left {{
            display: flex;
            align-items: center;
            gap: 7px;
            cursor: pointer;
            flex: 1;
            min-width: 0;
        }}
        .route-badge {{
            padding: 2px 7px;
            border-radius: 4px;
            color: #fff;
            font-weight: 700;
            font-size: 11.5px;
            min-width: 38px;
            text-align: center;
        }}
        .route-name {{
            font-size: 12px;
            font-weight: 600;
            color: #1e293b;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .dir-pills {{
            display: flex;
            gap: 4px;
            margin-top: 6px;
            padding-left: 22px;
        }}
        .dir-pill {{
            font-size: 10.5px;
            padding: 2px 7px;
            border-radius: 4px;
            border: 1px solid #cbd5e1;
            background: #ffffff;
            color: #475569;
            cursor: pointer;
        }}
        .dir-pill.on {{
            background: #1e40af;
            color: #ffffff;
            border-color: #1e40af;
            font-weight: 600;
        }}
        .stats-scroll {{
            flex: 1;
            overflow-y: auto;
            padding: 12px 14px;
        }}
        .stat-section {{
            margin-bottom: 14px;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 10px 12px;
            background: #f8fafc;
        }}
        .stat-section h3 {{
            font-size: 12.5px;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 8px;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 4px;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px;
        }}
        .kpi-box {{
            background: #fff;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 7px 9px;
        }}
        .kpi-val {{
            font-size: 15px;
            font-weight: 800;
            color: #1d4ed8;
        }}
        .kpi-lbl {{
            font-size: 10.5px;
            color: #64748b;
        }}
        #map-wrapper {{
            flex: 1;
            position: relative;
            height: 100vh;
        }}
        #map {{
            width: 100%;
            height: 100%;
        }}
        .top-right-bar {{
            position: absolute;
            top: 12px;
            right: 12px;
            z-index: 1000;
            display: flex;
            gap: 8px;
            background: rgba(255,255,255,0.95);
            padding: 7px 10px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.15);
            align-items: center;
            font-size: 12px;
        }}
        .top-right-bar select {{
            padding: 4px 8px;
            border: 1px solid #cbd5e1;
            border-radius: 5px;
            font-size: 12px;
            font-weight: 600;
            color: #1e293b;
        }}
        .timeline-dock {{
            position: absolute;
            bottom: 14px;
            left: 14px;
            right: 14px;
            z-index: 1000;
            background: rgba(15, 23, 42, 0.95);
            color: #ffffff;
            border-radius: 12px;
            padding: 11px 16px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.35);
            border: 1px solid rgba(255,255,255,0.14);
        }}
        .tl-top {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 7px;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .tl-clock {{
            display: flex;
            align-items: baseline;
            gap: 10px;
        }}
        .tl-time-badge {{
            font-size: 22px;
            font-weight: 800;
            font-family: Consolas, monospace;
            color: #38bdf8;
        }}
        .tl-date-lbl {{
            font-size: 11.5px;
            color: #94a3b8;
        }}
        .tl-stats-pills {{
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }}
        .tl-pill {{
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 999px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .pill-green {{ background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16,185,129,0.4); }}
        .pill-yellow {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4); }}
        .pill-purple {{ background: rgba(168, 85, 247, 0.22); color: #c084fc; border: 1px solid rgba(168,85,247,0.45); }}
        .pill-red {{ background: rgba(239, 68, 68, 0.25); color: #f87171; border: 1px solid rgba(239,68,68,0.5); }}
        .pill-gray {{ background: rgba(148, 163, 184, 0.2); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.35); }}
        .tl-controls {{
            display: flex;
            align-items: center;
            gap: 7px;
        }}
        .tl-btn {{
            background: #1e293b;
            color: #f8fafc;
            border: 1px solid #475569;
            border-radius: 6px;
            padding: 5px 9px;
            font-size: 11.5px;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
        }}
        .tl-btn:hover {{ background: #334155; }}
        .tl-btn.play {{ background: #2563eb; border-color: #3b82f6; }}
        .tl-slider {{
            flex: 1;
            accent-color: #38bdf8;
            height: 6px;
            cursor: pointer;
        }}
        .hour-bar {{
            display: flex;
            gap: 4px;
            margin-top: 7px;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
        }}
        .hr-chips-wrap {{
            display: flex;
            gap: 4px;
            flex-wrap: wrap;
            align-items: center;
        }}
        .hr-chip {{
            font-size: 10.5px;
            padding: 2px 6px;
            border-radius: 4px;
            background: #1e293b;
            color: #94a3b8;
            border: 1px solid #334155;
            cursor: pointer;
        }}
        .hr-chip:hover {{
            background: #334155;
            color: #fff;
        }}
        .legend-float {{
            position: absolute;
            top: 58px;
            right: 12px;
            z-index: 999;
            background: rgba(255,255,255,0.96);
            padding: 9px 12px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.12);
            font-size: 11.5px;
            line-height: 1.65;
        }}
        .dot {{
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 5px;
            vertical-align: middle;
        }}
    </style>
</head>
<body>
    <div id="sidebar">
        <div class="sidebar-header">
            <h1>
                <span>Kiểm Chứng Telemetry 17/10/2026</span>
                <span style="font-size:11px;background:#059669;padding:2px 7px;border-radius:4px;">40 Tuyến · Điểm Ma ETA</span>
            </h1>
            <p>Đã khử sạch Xe Ma & khôi phục vận tốc liên batch · 60FPS</p>
        </div>

        <div class="tab-bar">
            <button class="tab-btn active" onclick="switchTab('routes')">1. Lớp Tuyến & Trạm (40)</button>
            <button class="tab-btn" onclick="switchTab('stats')">2. Thống Kê 40 Tuyến Chuẩn</button>
        </div>

        <div id="tab-routes" class="tab-pane active">
            <div class="controls-box">
                <input type="text" id="routeSearch" class="search-input" placeholder="Tìm mã tuyến (VD: 01, 02, 08A, 32, E01, BRT01)..." oninput="renderRouteList()">
                <div class="btn-row">
                    <button class="btn btn-primary" onclick="selectPreset('default')">Mặc định (01, 32, E01)</button>
                    <button class="btn" onclick="selectPreset('hust')">Tuyến qua Bách Khoa</button>
                    <button class="btn" onclick="selectPreset('all')">Bật cả 40 tuyến</button>
                    <button class="btn" onclick="selectPreset('none')">Tắt hết</button>
                </div>
                <div class="layer-toggles">
                    <label><input type="checkbox" id="chkWays" checked onchange="syncRouteLayers()"> Đường lộ trình OSM</label>
                    <label><input type="checkbox" id="chkStations" checked onchange="syncRouteLayers()"> Trạm dừng (Trên tim đường)</label>
                    <label><input type="checkbox" id="chkBuses" checked onchange="scheduleRender()"> Vị trí GPS xe buýt</label>
                    <label title="Hiển thị Điểm Ma (Virtual Ghost Point) nằm trên tim đường OSM để ước lượng ETA khi xe đi lệch/detour"><input type="checkbox" id="chkProjLines" checked onchange="scheduleRender()"> Điểm Ma & Đường gióng</label>
                    <label title="Hiện thêm các xe đang đỗ nghỉ dài hạn tại sân bãi đầu/cuối bến (xe dừng đèn đỏ/trạm trên đường luôn hiển thị)"><input type="checkbox" id="chkStopped" onchange="scheduleRender()"> Cả xe nghỉ tại bến đầu/cuối</label>
                    <label title="Nội suy tuyến tính tọa độ giữa 2 lần xe gửi bản tin GPS"><input type="checkbox" id="chkInterp" checked onchange="scheduleRender()"> Nội suy mượt giữa 2 GPS</label>
                    <label title="Thời gian tối đa giữ vị trí cũ khi xe tạm thời chưa gửi GPS mới">
                        Giữ xe (TTL):
                        <select id="ttlSelect" onchange="scheduleRender()" style="font-size:11px;padding:1px 3px;border:1px solid #cbd5e1;border-radius:4px;">
                            <option value="180">3 phút</option>
                            <option value="600" selected>10 phút</option>
                            <option value="1800">30 phút</option>
                        </select>
                    </label>
                </div>
            </div>
            <div id="routeList" class="route-list"></div>
        </div>

        <div id="tab-stats" class="tab-pane">
            <div id="statsContent" class="stats-scroll"></div>
        </div>
    </div>

    <div id="map-wrapper">
        <div id="map"></div>

        <div class="top-right-bar">
            <span><b>Nền bản đồ:</b></span>
            <select id="tileSelect" onchange="switchBaseTile(this.value)">
                <option value="osmFrance" selected>OpenStreetMap France (Chuẩn OSM - Không lỗi 403)</option>
                <option value="cartoVoyager">CARTO Voyager (OSM Sáng rõ)</option>
                <option value="cartoDark">CARTO Dark Matter (Nền tối làm nổi xe)</option>
                <option value="googleStreets">Google Streets</option>
                <option value="esriStreet">Esri World Street</option>
            </select>
        </div>

        <div class="legend-float">
            <div><b>Trạng thái Xe & Chiến thuật Điểm Ma (40 tuyến):</b></div>
            <div><span class="dot" style="background:#10b981;border:2px solid #065f46;"></span><b>Đúng tuyến chuẩn</b> (d<sub>⊥</sub> ≤ 25m)</div>
            <div><span class="dot" style="background:#f59e0b;border:2px solid #92400e;"></span><b>Chấp nhận được / Dừng đèn đỏ</b> (≤ 40m)</div>
            <div><span class="dot" style="background:#a855f7;border:2px solid #581c87;"></span><b>Trễ cờ Direction</b> (Khớp chiều ngược + Momentum)</div>
            <div><span class="dot" style="background:#ef4444;border:2px solid #991b1b;"></span><b>Lệch / Detour (&gt;40m)</b> → Ánh xạ <b>Điểm Ma</b></div>
            <div><span class="dot" style="background:#ffffff;border:2.5px solid #dc2626;"></span><b>Điểm Ma trên tim đường</b> (Virtual Point tính ETA)</div>
            <div><span class="dot" style="background:#64748b;border:2px solid #334155;"></span><b>Nghỉ tại bến đầu/cuối</b> (Depot Idle)</div>
        </div>

        <div class="timeline-dock">
            <div class="tl-top">
                <div class="tl-clock">
                    <span id="tlTimeBadge" class="tl-time-badge">07:15:00</span>
                    <span class="tl-date-lbl">17/10/2026 · Bước <b>10 giây</b> (Phím ←/→ nhích 10s, Shift+←/→ nhích 1p · Click vào xe để xem Điểm Ma & ETA)</span>
                </div>
                <div class="tl-stats-pills">
                    <div class="tl-pill pill-green">≤25m: <span id="stGreen">0</span></div>
                    <div class="tl-pill pill-yellow">25–40m / Đèn đỏ: <span id="stYellow">0</span></div>
                    <div class="tl-pill pill-purple">Trễ cờ Dir: <span id="stPurple">0</span></div>
                    <div class="tl-pill pill-red">Điểm Ma (&gt;40m): <span id="stRed">0</span></div>
                    <div class="tl-pill pill-gray">Nghỉ tại bến: <span id="stGray">0</span></div>
                </div>
            </div>
            <div class="tl-controls">
                <button id="btnPlay" class="tl-btn play" onclick="togglePlay()">▶ Phát</button>
                <button class="tl-btn" onclick="stepSec(-60)">-1p</button>
                <button class="tl-btn" onclick="stepSec(-10)">⏮ -10s</button>
                <input type="range" id="timeSlider" class="tl-slider" min="{min_sec}" max="{max_sec}" step="10" value="{default_sec}" oninput="onSliderInput(this.value)">
                <button class="tl-btn" onclick="stepSec(10)">+10s ⏭</button>
                <button class="tl-btn" onclick="stepSec(60)">+1p</button>
                <select id="playSpeed" class="tl-btn" onchange="updatePlayInterval()">
                    <option value="10">Bước 10s / nhịp</option>
                    <option value="30" selected>Bước 30s / nhịp</option>
                    <option value="60">Bước 60s / nhịp</option>
                </select>
            </div>
            <div class="hour-bar">
                <div class="hr-chips-wrap" id="hourQuickBar">
                    <span style="font-size:10.5px;color:#94a3b8;margin-right:4px;">Nhảy nhanh tới giờ:</span>
                </div>
                <div style="font-size:11px;color:#cbd5e1;">
                    Đang hiển thị: <b id="totalVisibleBuses" style="color:#38bdf8;">0</b> xe (Giữ vị trí chờ gói GPS kế: <b id="carriedForwardBuses" style="color:#fbbf24;">0</b> xe)
                </div>
            </div>
        </div>
    </div>

    <script>
        const ROUTES = {routes_json};
        const VEHICLES = {vehicles_json};
        const TRACKS = {tracks_json};
        const STATS = {stats_json};

        const MIN_SEC = {min_sec};
        const MAX_SEC = {max_sec};
        let currentSec = {default_sec};
        let playTimer = null;
        let rafPending = false;

        function secToHMS(sec) {{
            const h = Math.floor(sec / 3600);
            const m = Math.floor((sec % 3600) / 60);
            const s = Math.floor(sec % 60);
            return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
        }}

        const routeByRef = {{}};
        const stationNameMap = {{}};
        const variantChainageTable = {{}};
        const EARTH_R = 6371008.8;
        const COS_LAT0 = Math.cos(21.0285 * Math.PI / 180.0);

        function buildVariantChainage(polyMulti) {{
            const lats = [], lons = [], cum = [];
            let total = 0.0;
            for (let s = 0; s < polyMulti.length; s++) {{
                const seg = polyMulti[s];
                for (let i = 0; i < seg.length; i++) {{
                    const lat = seg[i][0], lon = seg[i][1];
                    if (lats.length > 0) {{
                        const dLat = (lat - lats[lats.length - 1]) * Math.PI / 180.0 * EARTH_R;
                        const dLon = (lon - lons[lons.length - 1]) * Math.PI / 180.0 * EARTH_R * COS_LAT0;
                        const step = Math.hypot(dLat, dLon);
                        if (step < 0.05) continue;
                        total += step;
                    }}
                    lats.push(lat);
                    lons.push(lon);
                    cum.push(total);
                }}
            }}
            return {{ lats, lons, cum, total }};
        }}

        function pointAtChainage(key, sMeters) {{
            const tbl = variantChainageTable[key];
            if (!tbl || tbl.cum.length === 0) return null;
            if (sMeters <= 0) return [tbl.lats[0], tbl.lons[0]];
            const n = tbl.cum.length;
            if (sMeters >= tbl.cum[n - 1]) return [tbl.lats[n - 1], tbl.lons[n - 1]];
            let lo = 0, hi = n - 2, idx = 0;
            while (lo <= hi) {{
                const mid = (lo + hi) >> 1;
                if (tbl.cum[mid] <= sMeters) {{
                    idx = mid;
                    lo = mid + 1;
                }} else {{
                    hi = mid - 1;
                }}
            }}
            const segLen = Math.max(0.01, tbl.cum[idx + 1] - tbl.cum[idx]);
            const t = Math.max(0, Math.min(1, (sMeters - tbl.cum[idx]) / segLen));
            return [
                tbl.lats[idx] + t * (tbl.lats[idx + 1] - tbl.lats[idx]),
                tbl.lons[idx] + t * (tbl.lons[idx + 1] - tbl.lons[idx])
            ];
        }}

        ROUTES.forEach(r => {{
            routeByRef[r.ref] = r;
            Object.values(r.variants).forEach(v => {{
                const vKey = `${{r.ref}}_${{v.dir}}`;
                variantChainageTable[vKey] = buildVariantChainage(v.poly);
                v.st.forEach(s => {{
                    // s = [0:seq, 1:id, 2:name, 3:lat, 4:lon, 5:ch]
                    stationNameMap[`${{r.ref}}_${{v.dir}}_${{s[1]}}`] = s[2];
                }});
            }});
        }});

        const activeVariants = new Set(["01_0", "01_1", "32_0", "32_1", "E01_0", "E01_1"]);

        // Sử dụng 1 Canvas Renderer duy nhất cho toàn bộ bản đồ để đạt tốc độ vẽ tối đa
        const sharedCanvas = L.canvas({{ padding: 0.5 }});
        const map = L.map('map', {{
            center: [21.0285, 105.835],
            zoom: 12,
            renderer: sharedCanvas,
            preferCanvas: true,
            zoomControl: false
        }});
        L.control.zoom({{ position: 'bottomright' }}).addTo(map);
        const sharedPopup = L.popup({{ maxWidth: 320 }});

        const TILE_SOURCES = {{
            osmFrance: {{
                url: 'https://{{s}}.tile.openstreetmap.fr/osmfr/{{z}}/{{x}}/{{y}}.png',
                options: {{ maxZoom: 20, subdomains: 'abc', attribution: '&copy; OpenStreetMap France' }}
            }},
            cartoVoyager: {{
                url: 'https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png',
                options: {{ maxZoom: 20, subdomains: 'abcd', attribution: '&copy; OpenStreetMap &copy; CARTO' }}
            }},
            cartoDark: {{
                url: 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
                options: {{ maxZoom: 20, subdomains: 'abcd', attribution: '&copy; OpenStreetMap &copy; CARTO' }}
            }},
            googleStreets: {{
                url: 'https://mt1.google.com/vt/lyrs=m&x={{x}}&y={{y}}&z={{z}}',
                options: {{ maxZoom: 20, attribution: '&copy; Google Maps' }}
            }},
            esriStreet: {{
                url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',
                options: {{ maxZoom: 19, attribution: '&copy; Esri' }}
            }}
        }};

        let currentTileLayer = L.tileLayer(TILE_SOURCES.osmFrance.url, TILE_SOURCES.osmFrance.options).addTo(map);
        function switchBaseTile(key) {{
            if (!TILE_SOURCES[key]) return;
            map.removeLayer(currentTileLayer);
            currentTileLayer = L.tileLayer(TILE_SOURCES[key].url, TILE_SOURCES[key].options).addTo(map);
        }}

        // Cache các Layer của từng (ref_dir) để bật/tắt tức thì (0 ms) không phải khởi tạo lại
        const cachedWayLayers = {{}};
        const cachedStationLayers = {{}};

        function getOrCreateWayLayer(r, v) {{
            const key = `${{r.ref}}_${{v.dir}}`;
            if (cachedWayLayers[key]) return cachedWayLayers[key];
            const poly = L.polyline(v.poly, {{
                renderer: sharedCanvas,
                color: r.color,
                weight: v.dir === 0 ? 4.5 : 3.5,
                opacity: v.dir === 0 ? 0.85 : 0.65,
                dashArray: v.dir === 1 ? '6, 6' : null
            }});
            poly.on('click', (e) => {{
                sharedPopup
                    .setLatLng(e.latlng)
                    .setContent(`<b>Tuyến ${{r.ref}} (${{v.label}})</b><br>Tên tuyến: ${{r.name}}<br>Cự ly: ${{v.len_km}} km`)
                    .openOn(map);
            }});
            cachedWayLayers[key] = poly;
            return poly;
        }}

        function getOrCreateStationLayer(r, v) {{
            const key = `${{r.ref}}_${{v.dir}}`;
            if (cachedStationLayers[key]) return cachedStationLayers[key];
            const grp = L.layerGroup();
            v.st.forEach(s => {{
                // s = [0:seq, 1:id, 2:name, 3:lat, 4:lon, 5:ch]
                const m = L.circleMarker([s[3], s[4]], {{
                    renderer: sharedCanvas,
                    radius: 4.2,
                    fillColor: '#ffffff',
                    color: r.color,
                    weight: 2,
                    fillOpacity: 1.0
                }});
                m.on('click', () => {{
                    sharedPopup
                        .setLatLng([s[3], s[4]])
                        .setContent(`
                            <b>Tuyến ${{r.ref}} (${{v.label}}) · Trạm #${{s[0]}}</b><br>
                            Tên trạm: <b>${{s[2]}}</b><br>
                            Mã trạm Telemetry: <code>#${{s[1]}}</code><br>
                            Lý trình trên đường OSM: <b>${{s[5]}} m</b>
                        `)
                        .openOn(map);
                }});
                grp.addLayer(m);
            }});
            cachedStationLayers[key] = grp;
            return grp;
        }}

        function syncRouteLayers() {{
            const showWays = document.getElementById('chkWays').checked;
            const showStations = document.getElementById('chkStations').checked;

            ROUTES.forEach(r => {{
                [0, 1].forEach(d => {{
                    const v = r.variants[String(d)];
                    if (!v) return;
                    const key = `${{r.ref}}_${{d}}`;
                    const isOn = activeVariants.has(key);

                    const wLayer = cachedWayLayers[key];
                    if (isOn && showWays) {{
                        const wl = wLayer || getOrCreateWayLayer(r, v);
                        if (!map.hasLayer(wl)) map.addLayer(wl);
                    }} else if (wLayer && map.hasLayer(wLayer)) {{
                        map.removeLayer(wLayer);
                    }}

                    const sLayer = cachedStationLayers[key];
                    if (isOn && showStations) {{
                        const sl = sLayer || getOrCreateStationLayer(r, v);
                        if (!map.hasLayer(sl)) map.addLayer(sl);
                    }} else if (sLayer && map.hasLayer(sLayer)) {{
                        map.removeLayer(sLayer);
                    }}
                }});
            }});

            scheduleRender();
        }}

        // OBJECT POOL CHO XE BUÝT, ĐIỂM MA (GHOST POINT) & ĐƯỜNG GIÓNG
        const busMarkerPool = new Array(VEHICLES.length);
        const ghostMarkerPool = new Array(VEHICLES.length);
        const projLinePool = new Array(VEHICLES.length);
        const busCurrentState = new Array(VEHICLES.length);

        function openVehiclePopup(i, latlngOverride) {{
            const st = busCurrentState[i];
            if (!st) return;
            const vInfo = VEHICLES[i];
            const vid = vInfo[0], plate = vInfo[1], ref = vInfo[2];
            const rInfo = routeByRef[ref];
            const currName = stationNameMap[`${{ref}}_${{st.dir}}_${{st.currSt}}`] || stationNameMap[`${{ref}}_${{1-st.dir}}_${{st.currSt}}`] || `Trạm #${{st.currSt}}`;
            const nextName = stationNameMap[`${{ref}}_${{st.dir}}_${{st.nextSt}}`] || stationNameMap[`${{ref}}_${{1-st.dir}}_${{st.nextSt}}`] || `Trạm #${{st.nextSt}}`;
            const effSpdMps = Math.max(st.speed, 14.0) / 3.6;
            const etaSec = Math.round(st.remDistM / effSpdMps);
            const etaStr = etaSec >= 60 ? `${{Math.floor(etaSec/60)}}p ${{etaSec%60}}s` : `${{etaSec}} giây`;
            sharedPopup
                .setLatLng(latlngOverride || [st.lat, st.lon])
                .setContent(`
                    <div style="font-size:12.5px;line-height:1.5;min-width:265px;">
                        <div style="background:${{rInfo ? rInfo.color : '#1e40af'}};color:#fff;padding:4px 8px;border-radius:4px;font-weight:700;margin-bottom:6px;">
                            Tuyến ${{ref}} · Chiều ${{st.dir}} · Mốc ${{secToHMS(currentSec)}}
                        </div>
                        <b>Biển kiểm soát:</b> <code>${{plate}}</code> (ID: <code>${{vid}}</code>)<br>
                        <b>Gói tin GPS thực lúc:</b> <b>${{secToHMS(st.tStart)}}</b> (Trễ: <b>${{st.ageSec}}s</b>)<br>
                        <b>Vận tốc:</b> ${{st.speed}} km/h<br>
                        <b>Độ lệch tim đường OSM (d<sub>⊥</sub>):</b> <span style="font-weight:800;color:${{st.distM > 40 ? '#dc2626' : '#059669'}}">${{st.distM}} m</span><br>
                        <b>Trạng thái:</b> <span style="font-weight:700;color:${{st.fillColor}}">${{st.statusText}}</span>
                        <hr style="margin:5px 0;border:0;border-top:1px solid #e2e8f0;">
                        <b>Trạm vừa qua:</b> ${{currName}} (<code>#${{st.currSt}}</code>)<br>
                        <b>Trạm tiếp theo:</b> ${{nextName}} (<code>#${{st.nextSt}}</code>)<br>
                        <div style="margin-top:5px;padding:5px 7px;background:#f1f5f9;border-radius:5px;border-left:3px solid #2563eb;">
                            <b>👻 Điểm Ma (Ánh xạ tính ETA trên tuyến):</b><br>
                            • Lý trình trên tuyến: <b>${{st.sGhostM}} m</b><br>
                            • Còn cách trạm kế tiếp: <b>${{st.remDistM}} m</b><br>
                            • <b>ETA ước lượng tới trạm kế:</b> <span style="color:#1d4ed8;font-weight:800;">~${{etaStr}}</span>
                        </div>
                    </div>
                `)
                .openOn(map);
        }}

        for (let i = 0; i < VEHICLES.length; i++) {{
            const m = L.circleMarker([0, 0], {{
                renderer: sharedCanvas,
                radius: 7,
                fillColor: '#10b981',
                color: '#065f46',
                weight: 2,
                fillOpacity: 0.95
            }});
            m.on('click', () => openVehiclePopup(i));
            busMarkerPool[i] = m;

            const gm = L.circleMarker([0, 0], {{
                renderer: sharedCanvas,
                radius: 4.5,
                fillColor: '#ffffff',
                color: '#dc2626',
                weight: 2.5,
                fillOpacity: 1.0
            }});
            gm.on('click', () => openVehiclePopup(i, [busCurrentState[i].pLat, busCurrentState[i].pLon]));
            ghostMarkerPool[i] = gm;

            const pl = L.polyline([[0, 0], [0, 0]], {{
                renderer: sharedCanvas,
                color: '#ef4444',
                weight: 2,
                dashArray: '4, 4',
                opacity: 0.9
            }});
            projLinePool[i] = pl;
        }}

        function findVehicleStateAt(track, T, ttlSec) {{
            if (!track || track.length === 0) return null;
            let lo = 0, hi = track.length - 1, ans = -1;
            while (lo <= hi) {{
                const mid = (lo + hi) >> 1;
                if (track[mid][0] <= T) {{
                    ans = mid;
                    lo = mid + 1;
                }} else {{
                    hi = mid - 1;
                }}
            }}
            if (ans === -1) return null;
            const rec = track[ans];
            if (T > rec[1] + ttlSec) return null;
            const nextRec = (ans + 1 < track.length) ? track[ans + 1] : null;
            return {{ rec, nextRec }};
        }}

        function scheduleRender() {{
            if (rafPending) return;
            rafPending = true;
            requestAnimationFrame(() => {{
                rafPending = false;
                renderAtTime();
            }});
        }}

        function hideVehicleLayers(vIdx) {{
            const m = busMarkerPool[vIdx];
            const gm = ghostMarkerPool[vIdx];
            const pl = projLinePool[vIdx];
            if (map.hasLayer(m)) map.removeLayer(m);
            if (map.hasLayer(gm)) map.removeLayer(gm);
            if (map.hasLayer(pl)) map.removeLayer(pl);
        }}

        function renderAtTime() {{
            document.getElementById('tlTimeBadge').textContent = secToHMS(currentSec);
            document.getElementById('timeSlider').value = currentSec;

            const showBuses = document.getElementById('chkBuses').checked;
            const showProj = document.getElementById('chkProjLines').checked;
            const showStopped = document.getElementById('chkStopped').checked;
            const useInterp = document.getElementById('chkInterp').checked;
            const ttlSec = parseInt(document.getElementById('ttlSelect').value, 10) || 600;

            let cntGreen = 0, cntYellow = 0, cntPurple = 0, cntRed = 0, cntGray = 0;
            let totalVis = 0, carriedCnt = 0;

            for (let vIdx = 0; vIdx < VEHICLES.length; vIdx++) {{
                const vInfo = VEHICLES[vIdx];
                const ref = vInfo[2];

                if (!activeVariants.has(`${{ref}}_0`) && !activeVariants.has(`${{ref}}_1`)) {{
                    hideVehicleLayers(vIdx);
                    continue;
                }}

                const found = findVehicleStateAt(TRACKS[vIdx], currentSec, ttlSec);
                if (!found) {{
                    hideVehicleLayers(vIdx);
                    continue;
                }}

                const rec = found.rec;
                const nextRec = found.nextRec;
                const dir = rec[2];
                if (!activeVariants.has(`${{ref}}_${{dir}}`)) {{
                    hideVehicleLayers(vIdx);
                    continue;
                }}

                let lat = rec[3], lon = rec[4];
                const speed = rec[5];
                const currSt = rec[6], nextSt = rec[7];
                const distM = rec[8];
                let pLat = lat + rec[9] / 100000;
                let pLon = lon + rec[10] / 100000;
                const errType = rec[11];
                const oDistM = rec[12];
                const isDepot = rec[13] === 1;
                let sGhostM = rec[14];
                let remDistM = rec[15];

                // Chỉ ẩn xe khi xe thực sự đang đỗ nghỉ dài hạn trong sân bãi đầu/cuối bến (isDepot === true).
                // Xe đang đi trên tuyến mà dừng đèn đỏ hoặc ghé trạm đón khách (isDepot === false) LUÔN HIỂN THỊ!
                if (isDepot) {{
                    cntGray++;
                    if (!showStopped) {{
                        hideVehicleLayers(vIdx);
                        continue;
                    }}
                }} else {{
                    if (distM <= 25.0 && speed > 3.0) cntGreen++;
                    else if (distM <= 40.0) cntYellow++;
                    else if (errType === 1) cntPurple++;
                    else cntRed++;
                }}

                const ageSec = Math.max(0, currentSec - rec[0]);
                totalVis++;
                if (ageSec > 20) carriedCnt++;

                if (!showBuses) {{
                    hideVehicleLayers(vIdx);
                    continue;
                }}

                if (useInterp && nextRec && nextRec[2] === dir && (nextRec[0] - rec[0]) > 0 && (nextRec[0] - rec[0]) <= 300) {{
                    const alpha = Math.max(0, Math.min(1, (currentSec - rec[0]) / (nextRec[0] - rec[0])));
                    const s0 = rec[14], s1 = nextRec[14];
                    // Nếu xe đang chạy trên tuyến (distM <= 40m), nội suy BÁM THEO ĐƯỜNG CONG LỘ TRÌNH OSM (1D Chainage)
                    // để không bao giờ bị cắt góc 90 độ xuyên qua nhà dân tại các ngã tư (như Đào Tấn -> Đường Bưởi)!
                    if (distM <= 40.0 && nextRec[8] <= 40.0 && s1 >= s0 && (s1 - s0) <= 2500) {{
                        const sInterp = s0 + alpha * (s1 - s0);
                        const effDir = (errType === 1) ? (1 - dir) : dir;
                        const ptOnRoad = pointAtChainage(`${{ref}}_${{effDir}}`, sInterp);
                        if (ptOnRoad) {{
                            const offLat0 = -rec[9] / 100000;
                            const offLon0 = -rec[10] / 100000;
                            const offLat1 = -nextRec[9] / 100000;
                            const offLon1 = -nextRec[10] / 100000;
                            pLat = ptOnRoad[0];
                            pLon = ptOnRoad[1];
                            lat = pLat + (1 - alpha) * offLat0 + alpha * offLat1;
                            lon = pLon + (1 - alpha) * offLon0 + alpha * offLon1;
                            sGhostM = Math.round(sInterp);
                        }}
                    }} else {{
                        lat = rec[3] + alpha * (nextRec[3] - rec[3]);
                        lon = rec[4] + alpha * (nextRec[4] - rec[4]);
                        const nextPLat = nextRec[3] + nextRec[9] / 100000;
                        const nextPLon = nextRec[4] + nextRec[10] / 100000;
                        pLat = pLat + alpha * (nextPLat - pLat);
                        pLon = pLon + alpha * (nextPLon - pLon);
                    }}
                    if (nextRec[6] === currSt && nextRec[7] === nextSt) {{
                        remDistM = Math.max(0, Math.round(remDistM + alpha * (nextRec[15] - remDistM)));
                    }} else {{
                        remDistM = Math.max(0, Math.round(remDistM - (sGhostM - s0)));
                    }}
                }}

                let fillColor = '#10b981', strokeColor = '#065f46', statusText = 'Đúng tuyến chuẩn (≤ 25m)', radius = 7;
                if (isDepot) {{
                    fillColor = '#64748b'; strokeColor = '#1e293b'; statusText = 'Đang nghỉ tại bến đầu/cuối (Depot)'; radius = 5.5;
                }} else if (distM > 40.0) {{
                    if (errType === 1) {{
                        fillColor = '#a855f7'; strokeColor = '#581c87'; statusText = `Trễ cờ Direction (Khớp chiều ${{1-dir}} cách ${{oDistM}}m)`; radius = 8;
                    }} else {{
                        fillColor = '#ef4444'; strokeColor = '#7f1d1d'; statusText = `Lệch / Detour (${{distM}}m) → Dùng Điểm Ma tính ETA`; radius = 8;
                    }}
                }} else if (speed <= 3.0) {{
                    fillColor = '#f59e0b'; strokeColor = '#78350f'; statusText = `Dừng đèn đỏ / Đón trả khách tại trạm (${{distM}}m)`; radius = 7;
                }} else if (distM > 25.0) {{
                    fillColor = '#f59e0b'; strokeColor = '#78350f'; statusText = `Chấp nhận được (${{distM}}m)`; radius = 7.5;
                }}

                busCurrentState[vIdx] = {{
                    dir, lat: +lat.toFixed(5), lon: +lon.toFixed(5), pLat: +pLat.toFixed(5), pLon: +pLon.toFixed(5),
                    speed, currSt, nextSt, distM, oDistM, tStart: rec[0], ageSec, fillColor, statusText, sGhostM, remDistM
                }};

                const m = busMarkerPool[vIdx];
                const gm = ghostMarkerPool[vIdx];
                const pl = projLinePool[vIdx];

                m.setLatLng([lat, lon]);
                m.setStyle({{
                    radius: radius,
                    fillColor: fillColor,
                    color: strokeColor,
                    fillOpacity: ageSec > 120 ? 0.75 : 0.95
                }});
                if (!map.hasLayer(m)) map.addLayer(m);

                if (showProj && distM > 20.0 && !isDepot) {{
                    pl.setLatLngs([[lat, lon], [pLat, pLon]]);
                    pl.setStyle({{ color: fillColor }});
                    if (!map.hasLayer(pl)) map.addLayer(pl);

                    gm.setLatLng([pLat, pLon]);
                    gm.setStyle({{ color: fillColor }});
                    if (!map.hasLayer(gm)) map.addLayer(gm);
                }} else {{
                    if (map.hasLayer(pl)) map.removeLayer(pl);
                    if (map.hasLayer(gm)) map.removeLayer(gm);
                }}
            }}

            document.getElementById('stGreen').textContent = cntGreen;
            document.getElementById('stYellow').textContent = cntYellow;
            document.getElementById('stPurple').textContent = cntPurple;
            document.getElementById('stRed').textContent = cntRed;
            document.getElementById('stGray').textContent = cntGray;
            document.getElementById('totalVisibleBuses').textContent = totalVis;
            document.getElementById('carriedForwardBuses').textContent = carriedCnt;
        }}

        function onSliderInput(val) {{
            currentSec = parseInt(val, 10);
            scheduleRender();
        }}

        function stepSec(deltaSec) {{
            currentSec += deltaSec;
            if (currentSec > MAX_SEC) currentSec = MIN_SEC;
            if (currentSec < MIN_SEC) currentSec = MAX_SEC;
            scheduleRender();
        }}

        function togglePlay() {{
            const btn = document.getElementById('btnPlay');
            if (playTimer) {{
                clearInterval(playTimer);
                playTimer = null;
                btn.textContent = '▶ Phát';
            }} else {{
                const stepS = parseInt(document.getElementById('playSpeed').value, 10) || 30;
                btn.textContent = '⏸ Tạm dừng';
                playTimer = setInterval(() => stepSec(stepS), 180);
            }}
        }}

        function updatePlayInterval() {{
            if (playTimer) {{
                clearInterval(playTimer);
                const stepS = parseInt(document.getElementById('playSpeed').value, 10) || 30;
                playTimer = setInterval(() => stepSec(stepS), 180);
            }}
        }}

        function initHourBar() {{
            const bar = document.getElementById('hourQuickBar');
            for (let hr = 5; hr <= 20; hr++) {{
                const sec = Math.max(MIN_SEC, Math.min(MAX_SEC, hr * 3600));
                const btn = document.createElement('button');
                btn.className = 'hr-chip';
                btn.textContent = String(hr).padStart(2, '0') + ':00';
                btn.onclick = () => {{
                    currentSec = sec;
                    scheduleRender();
                }};
                bar.appendChild(btn);
            }}
        }}

        window.addEventListener('keydown', (e) => {{
            if (document.activeElement && document.activeElement.tagName === 'INPUT' && document.activeElement.type === 'text') return;
            if (e.key === 'ArrowRight') {{ e.preventDefault(); stepSec(e.shiftKey ? 60 : 10); }}
            else if (e.key === 'ArrowLeft') {{ e.preventDefault(); stepSec(e.shiftKey ? -60 : -10); }}
            else if (e.key === ' ') {{ e.preventDefault(); togglePlay(); }}
        }});

        function switchTab(tabName) {{
            document.querySelectorAll('.tab-btn').forEach((b, idx) => {{
                b.classList.toggle('active', (tabName === 'routes' && idx === 0) || (tabName === 'stats' && idx === 1));
            }});
            document.getElementById('tab-routes').classList.toggle('active', tabName === 'routes');
            document.getElementById('tab-stats').classList.toggle('active', tabName === 'stats');
        }}

        function renderRouteList() {{
            const q = (document.getElementById('routeSearch').value || '').trim().toLowerCase();
            const container = document.getElementById('routeList');
            container.innerHTML = '';

            ROUTES.forEach(r => {{
                if (q && !r.ref.toLowerCase().includes(q) && !r.name.toLowerCase().includes(q)) return;
                const d0On = activeVariants.has(`${{r.ref}}_0`);
                const d1On = activeVariants.has(`${{r.ref}}_1`);
                const anyOn = d0On || d1On;

                const card = document.createElement('div');
                card.className = 'route-card' + (anyOn ? ' active' : '');

                const top = document.createElement('div');
                top.className = 'route-top';
                top.innerHTML = `
                    <div class="route-left" onclick="toggleWholeRoute('${{r.ref}}')">
                        <input type="checkbox" ${{anyOn ? 'checked' : ''}} onclick="event.stopPropagation(); toggleWholeRoute('${{r.ref}}')">
                        <span class="route-badge" style="background:${{r.color}}">${{r.ref}}</span>
                        <span class="route-name" title="${{r.name}}">${{r.name}}</span>
                    </div>
                `;
                card.appendChild(top);

                const pills = document.createElement('div');
                pills.className = 'dir-pills';
                [0, 1].forEach(d => {{
                    const v = r.variants[String(d)];
                    if (!v) return;
                    const isOn = activeVariants.has(`${{r.ref}}_${{d}}`);
                    const btn = document.createElement('button');
                    btn.className = 'dir-pill' + (isOn ? ' on' : '');
                    btn.textContent = `Chiều ${{d}} (${{v.st.length}} trạm · ${{v.len_km}}km)`;
                    btn.onclick = () => toggleVariant(r.ref, d);
                    pills.appendChild(btn);
                }});
                card.appendChild(pills);
                container.appendChild(card);
            }});
        }}

        function toggleWholeRoute(ref) {{
            const d0 = `${{ref}}_0`, d1 = `${{ref}}_1`;
            if (activeVariants.has(d0) || activeVariants.has(d1)) {{
                activeVariants.delete(d0);
                activeVariants.delete(d1);
            }} else {{
                activeVariants.add(d0);
                activeVariants.add(d1);
            }}
            renderRouteList();
            syncRouteLayers();
        }}

        function toggleVariant(ref, d) {{
            const key = `${{ref}}_${{d}}`;
            if (activeVariants.has(key)) activeVariants.delete(key);
            else activeVariants.add(key);
            renderRouteList();
            syncRouteLayers();
        }}

        function selectPreset(mode) {{
            activeVariants.clear();
            if (mode === 'default') {{
                ['01', '32', 'E01'].forEach(ref => {{ activeVariants.add(`${{ref}}_0`); activeVariants.add(`${{ref}}_1`); }});
            }} else if (mode === 'hust') {{
                ['08A', '26', '32', '35A', '40', 'E08'].forEach(ref => {{ activeVariants.add(`${{ref}}_0`); activeVariants.add(`${{ref}}_1`); }});
            }} else if (mode === 'all') {{
                ROUTES.forEach(r => {{ activeVariants.add(`${{r.ref}}_0`); activeVariants.add(`${{r.ref}}_1`); }});
            }}
            renderRouteList();
            syncRouteLayers();
        }}

        function renderStatsTab() {{
            const el = document.getElementById('statsContent');
            let routeRows = '';
            STATS.routes_ranking.forEach(r => {{
                routeRows += `
                    <tr style="cursor:pointer;border-bottom:1px solid #f1f5f9;" onclick="activeVariants.clear();activeVariants.add('${{r.route_no}}_0');activeVariants.add('${{r.route_no}}_1');renderRouteList();syncRouteLayers();switchTab('routes');">
                        <td style="padding:4px;"><b>${{r.route_no}}</b></td>
                        <td style="padding:4px;">${{r.moving_pings.toLocaleString()}}</td>
                        <td style="padding:4px;">${{r.median_moving_m}}m</td>
                        <td style="padding:4px;color:#059669;font-weight:700;">${{r.on_route_40m_moving_pct}}%</td>
                    </tr>
                `;
            }});

            el.innerHTML = `
                <div class="stat-section">
                    <h3>1. Hiệu Quả Bộ 40 Tuyến Chuẩn (Mức 1 · Đang chạy &gt; 3km/h)</h3>
                    <div class="kpi-grid">
                        <div class="kpi-box">
                            <div class="kpi-val" style="color:#059669;">${{STATS.on_route_40m_pct}}%</div>
                            <div class="kpi-lbl">Khớp chuẩn tim đường (≤ 40m)</div>
                        </div>
                        <div class="kpi-box">
                            <div class="kpi-val">${{STATS.moving_count.toLocaleString()}}</div>
                            <div class="kpi-lbl">Bản ghi di chuyển hợp lệ</div>
                        </div>
                        <div class="kpi-box">
                            <div class="kpi-val">${{STATS.median_m}} m</div>
                            <div class="kpi-lbl">Sai số trung vị (P50)</div>
                        </div>
                        <div class="kpi-box">
                            <div class="kpi-val">${{STATS.p90_m}} m</div>
                            <div class="kpi-lbl">Phân vị 90% (P90)</div>
                        </div>
                    </div>
                </div>
                <div class="stat-section">
                    <h3>2. Danh Sách 40 Tuyến Sạch (Nhấn vào tuyến để xem)</h3>
                    <table style="width:100%;font-size:11.5px;border-collapse:collapse;text-align:left;">
                        <thead>
                            <tr style="border-bottom:1px solid #cbd5e1;color:#475569;">
                                <th style="padding:4px;">Tuyến</th>
                                <th style="padding:4px;">Pings chạy</th>
                                <th style="padding:4px;">Median d<sub>⊥</sub></th>
                                <th style="padding:4px;">Tỷ lệ khớp ≤40m</th>
                            </tr>
                        </thead>
                        <tbody>${{routeRows}}</tbody>
                    </table>
                </div>
            `;
        }}

        initHourBar();
        renderRouteList();
        renderStatsTab();
        syncRouteLayers();
    </script>
</body>
</html>
"""

    os.makedirs(os.path.dirname(OUTPUT_HTML_PATH), exist_ok=True)
    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)

    size_mb = os.path.getsize(OUTPUT_HTML_PATH) / (1024 * 1024)
    print(f"4. Hoàn tất! Đã xuất bản đồ 40 tuyến chuẩn Mức 1 (Chống treo 60FPS) tại:")
    print(f"   {OUTPUT_HTML_PATH} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
