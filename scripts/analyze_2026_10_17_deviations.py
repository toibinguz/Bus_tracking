"""
Phân tích toàn diện độ lệch quỹ đạo Telemetry ngày 17/10/2026 so với tim đường OSM tĩnh.
Sử dụng phép chiếu vuông góc vector hóa bằng NumPy (Equirectangular local tangent plane tại vĩ độ Hà Nội)
để kiểm định toàn bộ ~380.000 bản ghi trong 108 batches của ngày 17/10/2026 chỉ trong vài giây.
"""

import os
import sys
import glob
import json
import math
import numpy as np
from collections import defaultdict, Counter

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EARTH_R = 6371008.8
COS_LAT0 = math.cos(math.radians(21.0285))

def build_segments_arrays(ways):
    """
    Trích xuất mảng các đoạn thẳng AB từ danh sách ways của một variant:
    Trả về (ax, ay, bx, by, seg_len, cum_len, street_names)
    trong hệ tọa độ mét phẳng cục bộ để chiếu vector hóa cực nhanh.
    """
    ax_list, ay_list, bx_list, by_list, slen_list, clen_list, names_list = [], [], [], [], [], [], []
    cum = 0.0
    for w in ways:
        coords = w.get("coordinates", [])
        wname = w.get("name", "") or ""
        for i in range(len(coords) - 1):
            lon1, lat1 = coords[i][0], coords[i][1]
            lon2, lat2 = coords[i + 1][0], coords[i + 1][1]
            x1 = math.radians(lon1) * EARTH_R * COS_LAT0
            y1 = math.radians(lat1) * EARTH_R
            x2 = math.radians(lon2) * EARTH_R * COS_LAT0
            y2 = math.radians(lat2) * EARTH_R
            dx = x2 - x1
            dy = y2 - y1
            L = math.hypot(dx, dy)
            if L < 0.05:
                continue
            ax_list.append(x1)
            ay_list.append(y1)
            bx_list.append(x2)
            by_list.append(y2)
            slen_list.append(L)
            clen_list.append(cum)
            names_list.append(wname)
            cum += L
    return {
        "ax": np.array(ax_list, dtype=np.float64),
        "ay": np.array(ay_list, dtype=np.float64),
        "bx": np.array(bx_list, dtype=np.float64),
        "by": np.array(by_list, dtype=np.float64),
        "slen": np.array(slen_list, dtype=np.float64),
        "clen": np.array(clen_list, dtype=np.float64),
        "names": names_list,
        "total_len": cum
    }

def project_points_vectorized(lats, lons, seg_data):
    """
    Chiếu mảng điểm (lats, lons) kích thước (N,) lên mảng đoạn thẳng kích thước (M,).
    Trả về:
      - min_dist: (N,) khoảng cách vuông góc ngắn nhất tới tim đường (m)
      - chainage: (N,) lý trình dọc tuyến (m)
      - proj_lat, proj_lon: (N,) tọa độ hình chiếu trên tim đường OSM
      - best_seg_idx: (N,) chỉ số đoạn đường gần nhất
    """
    px = np.radians(lons) * EARTH_R * COS_LAT0  # (N,)
    py = np.radians(lats) * EARTH_R             # (N,)

    ax = seg_data["ax"][None, :]  # (1, M)
    ay = seg_data["ay"][None, :]
    bx = seg_data["bx"][None, :]
    by = seg_data["by"][None, :]
    slen2 = (seg_data["slen"] ** 2)[None, :]

    dx = bx - ax
    dy = by - ay

    # Chiếu theo lô 2000 điểm để tiết kiệm RAM
    N = len(lats)
    min_dist = np.empty(N, dtype=np.float64)
    chainage = np.empty(N, dtype=np.float64)
    proj_lat = np.empty(N, dtype=np.float64)
    proj_lon = np.empty(N, dtype=np.float64)
    best_seg = np.empty(N, dtype=np.int32)

    batch_size = 2000
    for start in range(0, N, batch_size):
        end = min(N, start + batch_size)
        b_px = px[start:end, None]  # (B, 1)
        b_py = py[start:end, None]

        t = ((b_px - ax) * dx + (b_py - ay) * dy) / slen2
        t_clamped = np.clip(t, 0.0, 1.0)

        qx = ax + t_clamped * dx
        qy = ay + t_clamped * dy

        dist2 = (b_px - qx) ** 2 + (b_py - qy) ** 2
        idx = np.argmin(dist2, axis=1)
        row_arange = np.arange(end - start)

        best_d = np.sqrt(dist2[row_arange, idx])
        best_t = t_clamped[row_arange, idx]
        best_qx = qx[row_arange, idx]
        best_qy = qy[row_arange, idx]

        min_dist[start:end] = best_d
        chainage[start:end] = seg_data["clen"][idx] + best_t * seg_data["slen"][idx]
        proj_lat[start:end] = np.degrees(best_qy / EARTH_R)
        proj_lon[start:end] = np.degrees(best_qx / (EARTH_R * COS_LAT0))
        best_seg[start:end] = idx

    return min_dist, chainage, proj_lat, proj_lon, best_seg

def main():
    from scripts.fuse_telemetry_with_osm import orient_osm_ways

    with open("data/fused_osm/master_fused_routes_segments.json", encoding="utf-8") as f:
        fused_catalog = json.load(f)

    routes_meta = fused_catalog["routes"]

    # Chuẩn bị bộ chiếu vector hóa cho toàn bộ 46 tuyến sạch
    route_projectors = {}
    station_lookup = {}  # (rid, dir, st_id) -> station info
    terminal_stations = {}  # (rid, dir) -> set of first 2 and last 2 station_ids

    for rid_str, rinfo in routes_meta.items():
        rid = int(rid_str)
        rno = rinfo["route_no"]
        candidates = [rno, rno.lstrip("0"), "0" + rno if len(rno) == 1 else rno]
        osm_path = next(
            (f"ground_truth_route_station/output/routes/route_{c}_metadata.json"
             for c in candidates
             if os.path.exists(f"ground_truth_route_station/output/routes/route_{c}_metadata.json")),
            None
        )
        with open(osm_path, encoding="utf-8") as f:
            osm_meta = json.load(f)

        v_segs = {}
        for v in osm_meta["variants"]:
            oways = orient_osm_ways(v.get("ways", []))
            v_segs[v["variant_index"]] = build_segments_arrays(oways)

        dir_map = {}
        for d_str, dinfo in rinfo["directions"].items():
            d = int(d_str)
            dir_map[d] = dinfo["matched_osm_variant_index"]
            sts = dinfo["stations"]
            for s in sts:
                station_lookup[(rid, d, s["telemetry_station_id"])] = s
            if len(sts) >= 4:
                term_ids = {sts[0]["telemetry_station_id"], sts[1]["telemetry_station_id"],
                            sts[-2]["telemetry_station_id"], sts[-1]["telemetry_station_id"]}
            else:
                term_ids = {s["telemetry_station_id"] for s in sts}
            terminal_stations[(rid, d)] = term_ids

        route_projectors[rid] = {
            "route_no": rno,
            "route_name": rinfo["route_name"],
            "variants_seg": v_segs,
            "dir_to_variant": dir_map
        }

    # Đọc toàn bộ 108 batch files của ngày 2026-10-17
    batch_files = sorted(glob.glob("data/telemetry_sync/raw_batches/2026-10-17/bus/*.jsonl"))
    print(f"[*] Đang nạp {len(batch_files)} batch files của ngày 2026-10-17...")

    records_by_route_dir = defaultdict(list)
    total_raw = 0
    excluded_route_pings = 0
    off_duty_pings = 0

    for fp in batch_files:
        bname = os.path.basename(fp) # batch_HHMMSS.jsonl
        hh = bname.replace("batch_", "")[:2]
        with open(fp, encoding="utf-8") as f:
            for line in f:
                total_raw += 1
                rec = json.loads(line)
                rid = rec.get("route_id")
                if rid not in route_projectors:
                    excluded_route_pings += 1
                    continue
                d = rec.get("direction")
                if d not in (0, 1):
                    off_duty_pings += 1
                    continue
                rec["_hour"] = hh
                records_by_route_dir[(rid, d)].append(rec)

    print(f"[*] Tổng bản ghi ngày 17/10/2026: {total_raw:,}")
    print(f"    - Thuộc 3 tuyến loại bỏ (E10TC, 123, E11): {excluded_route_pings:,}")
    print(f"    - Xe nghỉ tại bãi / ngoài ca (direction = -1): {off_duty_pings:,}")
    active_count = sum(len(v) for v in records_by_route_dir.values())
    print(f"    - Xe đang bật ca chạy trên 46 tuyến sạch (direction = 0, 1): {active_count:,}")

    # Thống kê tổng hợp
    all_Matched_dists = []
    moving_dists = []
    stopped_dists = []

    hourly_stats = defaultdict(lambda: {"total": 0, "moving": 0, "off_40m_all": 0, "off_40m_moving": 0, "dists_moving": []})
    route_stats = {}
    root_causes_moving = Counter()
    hotspot_segments = defaultdict(lambda: {"count": 0, "dists": [], "lats": [], "lons": [], "route_no": "", "from_name": "", "to_name": ""})

    for (rid, d), recs in sorted(records_by_route_dir.items()):
        rproj = route_projectors[rid]
        rno = rproj["route_no"]
        v_idx = rproj["dir_to_variant"][d]
        other_v_idx = 1 - v_idx if (1 - v_idx) in rproj["variants_seg"] else v_idx

        lats = np.array([r["lat"] for r in recs], dtype=np.float64)
        lons = np.array([r["lon"] for r in recs], dtype=np.float64)
        speeds = np.array([float(r.get("speed", 0.0) or 0.0) for r in recs], dtype=np.float64)

        # Chiếu lên variant đúng chiều
        d_Assigned, ch_Assigned, plat, plon, seg_idx = project_points_vectorized(lats, lons, rproj["variants_seg"][v_idx])
        # Chiếu lên variant chiều ngược lại (để kiểm tra lỗi ngược chiều / trễ đổi chiều)
        d_Other, _, _, _, _ = project_points_vectorized(lats, lons, rproj["variants_seg"][other_v_idx])
        # Khoảng cách tốt nhất tới bất kỳ chiều nào của tuyến
        d_Best = np.minimum(d_Assigned, d_Other)

        all_Matched_dists.append(d_Best)
        is_moving = speeds > 3.0
        moving_dists.append(d_Best[is_moving])
        stopped_dists.append(d_Best[~is_moving])

        # Thống kê theo tuyến
        if rno not in route_stats:
            route_stats[rno] = {
                "route_id": rid,
                "route_name": rproj["route_name"],
                "total_pings": 0,
                "moving_pings": 0,
                "dists_all": [],
                "dists_moving": [],
                "off_40m_moving": 0,
                "off_100m_moving": 0
            }
        rs = route_stats[rno]
        rs["total_pings"] += len(recs)
        rs["moving_pings"] += int(np.sum(is_moving))
        rs["dists_all"].append(d_Best)
        rs["dists_moving"].append(d_Best[is_moving])
        rs["off_40m_moving"] += int(np.sum(d_Best[is_moving] > 40.0))
        rs["off_100m_moving"] += int(np.sum(d_Best[is_moving] > 100.0))

        term_set = terminal_stations.get((rid, d), set())

        # Phân tích theo giờ & Phân loại nguyên nhân gốc rễ cho từng điểm lệch khi xe chạy
        for i, rec in enumerate(recs):
            hh = rec["_hour"]
            dist_b = float(d_Best[i])
            dist_a = float(d_Assigned[i])
            dist_o = float(d_Other[i])
            spd = float(speeds[i])
            mov = spd > 3.0

            hs = hourly_stats[hh]
            hs["total"] += 1
            if dist_b > 40.0:
                hs["off_40m_all"] += 1
            if mov:
                hs["moving"] += 1
                hs["dists_moving"].append(dist_b)
                if dist_b > 40.0:
                    hs["off_40m_moving"] += 1

            # Kiểm tra các điểm lệch > 40m so với chiều được gán (dist_a > 40.0) khi đang di chuyển
            if mov and dist_a > 40.0:
                cs = rec.get("current_station_id", 0)
                ns = rec.get("next_station_id", 0)
                if dist_o <= 35.0:
                    root_causes_moving["1. Lệch chiều (Xe chạy trên đường chiều ngược lại / Trễ đổi cờ direction ở đầu bến)"] += 1
                elif cs in term_set or ns in term_set:
                    root_causes_moving["2. Ra/vào khuôn viên Bến xe đầu cuối hoặc Quay đầu xuất bến"] += 1
                elif dist_b <= 90.0:
                    root_causes_moving["3. Đường gom đại lộ rộng / Vòng xoay / Nút giao cầu vượt (40m - 90m)"] += 1
                else:
                    root_causes_moving["4. Lệch lộ trình thực tế / Đi đường vòng ngoài tim đường OSM (> 90m)"] += 1
                    # Ghi nhận hotspot theo phân đoạn
                    st_from = station_lookup.get((rid, d, cs), {})
                    st_to = station_lookup.get((rid, d, ns), {})
                    seg_key = f"{rno}|d{d}|{cs}->{ns}"
                    hspot = hotspot_segments[seg_key]
                    hspot["count"] += 1
                    hspot["dists"].append(dist_b)
                    hspot["lats"].append(float(lats[i]))
                    hspot["lons"].append(float(lons[i]))
                    hspot["route_no"] = rno
                    hspot["from_id"] = cs
                    hspot["to_id"] = ns
                    hspot["from_name"] = st_from.get("station_name", f"Trạm #{cs}")
                    hspot["to_name"] = st_to.get("station_name", f"Trạm #{ns}")

    all_arr = np.concatenate(all_Matched_dists)
    mov_arr = np.concatenate(moving_dists)
    stp_arr = np.concatenate(stopped_dists)

    def summarize_array(arr):
        n = len(arr)
        return {
            "count": int(n),
            "mean_m": round(float(np.mean(arr)), 2),
            "median_m": round(float(np.median(arr)), 2),
            "p90_m": round(float(np.percentile(arr, 90)), 2),
            "p95_m": round(float(np.percentile(arr, 95)), 2),
            "strict_25m_cnt": int(np.sum(arr <= 25.0)),
            "strict_25m_pct": round(float(np.mean(arr <= 25.0) * 100), 2),
            "tolerant_25_40m_cnt": int(np.sum((arr > 25.0) & (arr <= 40.0))),
            "tolerant_25_40m_pct": round(float(np.mean((arr > 25.0) & (arr <= 40.0)) * 100), 2),
            "total_on_route_40m_pct": round(float(np.mean(arr <= 40.0) * 100), 2),
            "off_40_100m_cnt": int(np.sum((arr > 40.0) & (arr <= 100.0))),
            "off_40_100m_pct": round(float(np.mean((arr > 40.0) & (arr <= 100.0)) * 100), 2),
            "off_gt_100m_cnt": int(np.sum(arr > 100.0)),
            "off_gt_100m_pct": round(float(np.mean(arr > 100.0) * 100), 2)
        }

    report = {
        "overall_active": summarize_array(all_arr),
        "moving_gt_3kmh": summarize_array(mov_arr),
        "stopped_le_3kmh": summarize_array(stp_arr),
        "root_causes_moving_gt_40m": dict(root_causes_moving),
        "hourly": {},
        "routes_ranking_by_off_route": [],
        "top_hotspots": []
    }

    for hh in sorted(hourly_stats.keys()):
        hs = hourly_stats[hh]
        m_arr = np.array(hs["dists_moving"]) if hs["dists_moving"] else np.array([0.0])
        report["hourly"][hh] = {
            "total_pings": hs["total"],
            "moving_pings": hs["moving"],
            "off_40m_all_pct": round(hs["off_40m_all"] / hs["total"] * 100, 2) if hs["total"] else 0.0,
            "off_40m_moving_cnt": hs["off_40m_moving"],
            "off_40m_moving_pct": round(hs["off_40m_moving"] / hs["moving"] * 100, 2) if hs["moving"] else 0.0,
            "median_moving_m": round(float(np.median(m_arr)), 2)
        }

    for rno, rs in route_stats.items():
        m_arr = np.concatenate(rs["dists_moving"]) if rs["dists_moving"] else np.array([0.0])
        a_arr = np.concatenate(rs["dists_all"]) if rs["dists_all"] else np.array([0.0])
        off_pct = round(rs["off_40m_moving"] / rs["moving_pings"] * 100, 2) if rs["moving_pings"] else 0.0
        report["routes_ranking_by_off_route"].append({
            "route_no": rno,
            "route_id": rs["route_id"],
            "route_name": rs["route_name"],
            "total_pings": rs["total_pings"],
            "moving_pings": rs["moving_pings"],
            "on_route_40m_moving_pct": round(100.0 - off_pct, 2),
            "off_40m_moving_cnt": rs["off_40m_moving"],
            "off_40m_moving_pct": off_pct,
            "off_100m_moving_cnt": rs["off_100m_moving"],
            "median_moving_m": round(float(np.median(m_arr)), 2),
            "p90_moving_m": round(float(np.percentile(m_arr, 90)), 2),
            "on_route_40m_all_pct": round(float(np.mean(a_arr <= 40.0) * 100), 2)
        })

    report["routes_ranking_by_off_route"].sort(key=lambda x: x["off_40m_moving_pct"], reverse=True)

    # Top hotspots
    sorted_hotspots = sorted(hotspot_segments.items(), key=lambda x: x[1]["count"], reverse=True)
    for k, v in sorted_hotspots[:25]:
        report["top_hotspots"].append({
            "segment_key": k,
            "route_no": v["route_no"],
            "from_station": f"{v['from_name']} (#{v['from_id']})",
            "to_station": f"{v['to_name']} (#{v['to_id']})",
            "off_route_pings_count": v["count"],
            "median_deviation_m": round(float(np.median(v["dists"])), 1),
            "max_deviation_m": round(float(np.max(v["dists"])), 1),
            "center_lat": round(float(np.median(v["lats"])), 5),
            "center_lon": round(float(np.median(v["lons"])), 5)
        })

    out_json = "data/fused_osm/deviation_analysis_2026_10_17.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n================ KẾT QUẢ THỐNG KÊ ĐỘ LỆCH NGÀY 17/10/2026 ================")
    print("1. Tổng thể (Xe đang bật ca direction=0,1):", json.dumps(report["overall_active"], ensure_ascii=False))
    print("2. Khi xe đang di chuyển (speed > 3 km/h):", json.dumps(report["moving_gt_3kmh"], ensure_ascii=False))
    print("3. Khi xe dừng đỗ (speed <= 3 km/h):", json.dumps(report["stopped_le_3kmh"], ensure_ascii=False))
    print("\n4. Phân loại Nguyên nhân gây lệch (>40m so với chiều gán) khi xe đang di chuyển:")
    for k, cnt in sorted(report["root_causes_moving_gt_40m"].items()):
        print(f"   - {k}: {cnt:,} bản ghi")

    print("\n5. Top 12 Tuyến có tỷ lệ lệch (>40m khi di chuyển) cao nhất:")
    for r in report["routes_ranking_by_off_route"][:12]:
        print(f"   - Tuyến {r['route_no']:5s}: Lệch >40m = {r['off_40m_moving_pct']:5.2f}% ({r['off_40m_moving_cnt']:4d}/{r['moving_pings']:4d} pings), Bám tuyến = {r['on_route_40m_moving_pct']:5.2f}%, Med = {r['median_moving_m']:4.1f}m | {r['route_name']}")

    print("\n6. Top 12 Điểm nóng (Hotspot Segments) gây lệch lộ trình (>90m khi xe chạy):")
    for h in report["top_hotspots"][:12]:
        print(f"   - Tuyến {h['route_no']:5s} [{h['from_station']} -> {h['to_station']}]: {h['off_route_pings_count']:3d} pings, lệch trung vị {h['median_deviation_m']}m @ ({h['center_lat']}, {h['center_lon']})")

if __name__ == "__main__":
    main()
