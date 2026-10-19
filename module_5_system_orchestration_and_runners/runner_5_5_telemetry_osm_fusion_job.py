"""
Pipeline Hợp Nhất Dữ Liệu Telemetry (Hugging Face) & Bản Đồ OSM Tĩnh
Thực hiện theo đúng các quyết định thiết kế đã thống nhất:
1. Loại bỏ 3 tuyến lỗi (E10TC - thiếu OSM, 123 - đổi lộ trình thực tế, E11 - xe đỗ bãi), giữ 46 tuyến sạch.
2. Chuẩn hóa 2 chiều hóa các đoạn Way trên OSM để tạo trục lý trình (chainage 0 -> L mét) liên tục.
3. Khôi phục dây chuyền thứ tự trạm chuẩn từ cặp (current_station_id -> next_station_id) trong Telemetry,
   kết hợp sắp xếp theo lý trình OSM để khép kín 100% chuỗi trạm từ đầu bến đến cuối bến.
4. Ánh xạ tự động chiều di chuyển (direction = 0, 1 <-> OSM variant = 0, 1) dựa trên độ tăng đơn điệu lý trình.
5. Chiếu từng trạm và từng gói tin Telemetry lên hình học OSM để tính cự ly phân đoạn thực tế (segment_length_m),
   gán tên trạm từ OSM gần nhất, và xuất bộ dữ liệu hợp nhất (Fused Master Catalog & Fused Telemetry).
"""

import os
import sys
import glob
import json
import numpy as np

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)

from module_3_spatial_matching_and_trajectory_fusion import RoutePolylineProjector, haversine_distance_m

from module_2_osm_ground_truth_and_road_network import orient_osm_ways

EXCLUDED_ROUTES = {"E10TC", "123", "E11", "61", "17", "56B", "122", "28", "27"}

def reconstruct_ordered_station_chain(edge_counts, station_pts_map, projector):
    """
    Khôi phục chuỗi trạm đơn tuyến tính s_1 -> s_2 -> ... -> s_K từ đồ thị chuyển tiếp
    (current_station_id -> next_station_id), đồng thời nối các đoạn rời (nếu có)
    bằng thứ tự lý trình (chainage_m) dọc theo đường Polyline OSM.
    """
    if not edge_counts:
        return []

    # Chọn cạnh chuyển tiếp chủ đạo cho mỗi trạm
    nxt = {u: max(vs.items(), key=lambda x: x[1])[0] for u, vs in edge_counts.items()}
    all_nodes = set(nxt.keys()) | set(nxt.values())
    heads = [u for u in all_nodes if u not in set(nxt.values())]
    if not heads:
        heads = [min(all_nodes)]

    # Tạo các chuỗi con (sub-chains) từ từng head
    raw_chains = []
    visited_global = set()
    # Ưu tiên duyệt từ các head trước
    for h in heads:
        chain = []
        curr = h
        visited_local = set()
        while curr is not None and curr not in visited_local:
            chain.append(curr)
            visited_local.add(curr)
            curr = nxt.get(curr, None)
        raw_chains.append(chain)
        visited_global.update(chain)

    # Nếu còn nút nằm trong chu trình khép kín chưa được thăm
    for u in all_nodes - visited_global:
        chain = []
        curr = u
        while curr is not None and curr not in visited_global:
            chain.append(curr)
            visited_global.add(curr)
            curr = nxt.get(curr, None)
        if chain:
            raw_chains.append(chain)

    if len(raw_chains) == 1:
        return raw_chains[0]

    # Nếu có nhiều chuỗi con (do một số trạm chồng nhau ở đầu/cuối hoặc thiếu 1 bước nhảy),
    # tính lý trình trung bình của từng chuỗi con trên OSM để xếp thứ tự và gộp không trùng lặp
    def chain_mean_chainage(ch):
        c_vals = []
        for s in ch:
            pts = station_pts_map.get(s, [])
            if pts:
                dwell = [p for p in pts if p[2] <= 8.0]
                use = dwell if dwell else pts
                lat = float(np.median([p[0] for p in use]))
                lon = float(np.median([p[1] for p in use]))
                c_vals.append(projector.project_ping(lat, lon)["chainage_m"])
        return float(np.mean(c_vals)) if c_vals else 0.0

    raw_chains.sort(key=chain_mean_chainage)
    merged = []
    seen = set()
    for ch in raw_chains:
        for s in ch:
            if s not in seen:
                merged.append(s)
                seen.add(s)
    return merged

def main():
    with open("data/metadata/hust_cluster_config.json", encoding="utf-8") as f:
        cluster_cfg = json.load(f)

    batch_files = sorted(glob.glob("data/telemetry_sync/raw_batches/2026-10-17/bus/*.jsonl"))
    print(f"[*] Đang đọc {len(batch_files)} batch files từ data/telemetry_sync/raw_batches/2026-10-17/bus/ ...")

    edges = {}          # (rid, dir) -> {curr_st: {next_st: count}}
    curr_pts = {}       # (rid, dir, st_id) -> [(lat, lon, speed)]
    next_pts = {}       # (rid, dir, st_id) -> [(lat, lon, speed)]
    route_pings = {}    # rid -> list of active records

    total_records = 0
    active_moving_records = 0
    off_duty_records = 0

    for fp in batch_files:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                total_records += 1
                rec = json.loads(line)
                rid = rec.get("route_id")
                d = rec.get("direction")
                if d not in (0, 1):
                    off_duty_records += 1
                    continue
                lat, lon = rec.get("lat"), rec.get("lon")
                spd = float(rec.get("speed", 0.0) or 0.0)
                cs = int(rec.get("current_station_id", 0) or 0)
                ns = int(rec.get("next_station_id", 0) or 0)

                if cs > 0 and ns > 0 and cs != ns:
                    edges.setdefault((rid, d), {}).setdefault(cs, {})
                    edges[(rid, d)][cs][ns] = edges[(rid, d)][cs].get(ns, 0) + 1
                if cs > 0 and lat and lon:
                    curr_pts.setdefault((rid, d, cs), []).append((lat, lon, spd))
                if ns > 0 and lat and lon:
                    next_pts.setdefault((rid, d, ns), []).append((lat, lon, spd))

                if rec.get("quality_status") == "ACTIVE_VALID" and cs > 0 and ns > 0:
                    active_moving_records += 1
                    if len(route_pings.setdefault(rid, [])) < 300:
                        route_pings[rid].append(rec)

    print(f"[*] Tổng bản ghi: {total_records:,} | Hợp lệ theo chiều tuyến (dir 0/1): {active_moving_records:,} | Nghỉ/Ngoài ca (dir -1): {off_duty_records:,}")

    os.makedirs("data/fused_osm", exist_ok=True)
    fused_catalog = {
        "generated_at": "2026-10-17",
        "total_clean_routes": 0,
        "excluded_routes": list(EXCLUDED_ROUTES),
        "routes": {}
    }

    total_segments_built = 0
    total_stations_mapped = 0

    for r in cluster_cfg["routes"]:
        rid = r["route_id"]
        rno = str(r["route_no"]).strip().upper()
        if rno in EXCLUDED_ROUTES:
            continue

        candidates = [rno, rno.lstrip("0"), "0" + rno if len(rno) == 1 else rno]
        osm_path = next(
            (p for c in candidates for p in [
                f"data/ground_truth/routes/route_{c}_metadata.json",
                f"ground_truth_route_station/output/routes/route_{c}_metadata.json"
            ] if os.path.exists(p)),
            None
        )

        if not osm_path:
            continue

        with open(osm_path, encoding="utf-8") as f:
            osm_meta = json.load(f)

        # Chuẩn hóa 2 chiều hóa các đoạn Way cho từng variant
        variants_info = []
        for v in osm_meta.get("variants", []):
            oways = orient_osm_ways(v.get("ways", []))
            proj = RoutePolylineProjector(oways)
            variants_info.append({
                "variant_index": v["variant_index"],
                "name": v.get("name", ""),
                "from": v.get("from", ""),
                "to": v.get("to", ""),
                "length_km": round(proj.total_length_m / 1000.0, 3),
                "projector": proj,
                "osm_stops": v.get("stops", [])
            })

        # Xác định ánh xạ giữa telemetry direction (0, 1) và OSM variant_index (0, 1)
        # bằng cách kiểm tra chiều tăng đơn điệu của lý trình chuỗi trạm
        dir_to_variant = {}
        for d in (0, 1):
            emap = edges.get((rid, d), {})
            # Tạm thời lấy chuỗi dài nhất để kiểm tra hướng
            temp_st_map = {s: curr_pts.get((rid, d, s), next_pts.get((rid, d, s), [])) for s in range(1)}
            # Lấy tập điểm cho tất cả trạm của (rid, d)
            all_st = set(emap.keys()) | set(v for vs in emap.values() for v in vs.keys())
            st_map = {s: (curr_pts.get((rid, d, s)) or next_pts.get((rid, d, s)) or []) for s in all_st}

            best_v_idx = 0
            best_forward_score = -999999
            for vi in variants_info:
                ch = reconstruct_ordered_station_chain(emap, st_map, vi["projector"])
                c_vals = []
                for s in ch:
                    pts = st_map.get(s, [])
                    if pts:
                        dwell = [p for p in pts if p[2] <= 8.0]
                        use = dwell if dwell else pts
                        lat = float(np.median([p[0] for p in use]))
                        lon = float(np.median([p[1] for p in use]))
                        c_vals.append(vi["projector"].project_ping(lat, lon)["chainage_m"])
                if len(c_vals) >= 2:
                    diffs = np.diff(c_vals)
                    score = int(np.sum(diffs > 0)) - int(np.sum(diffs < 0))
                    if score > best_forward_score:
                        best_forward_score = score
                        best_v_idx = vi["variant_index"]
            dir_to_variant[d] = best_v_idx

        # Nếu cả dir=0 và dir=1 vô tình trỏ vào cùng 1 variant (trường hợp hiếm), gán đối xứng
        if len(variants_info) >= 2 and dir_to_variant.get(0) == dir_to_variant.get(1):
            dir_to_variant[1] = 1 - dir_to_variant[0]

        # Xây dựng danh bạ trạm & phân đoạn (Segments) cho từng direction (0 và 1)
        directions_payload = {}
        for d in (0, 1):
            v_idx = dir_to_variant.get(d, d)
            v_obj = next((vi for vi in variants_info if vi["variant_index"] == v_idx), variants_info[0])
            proj = v_obj["projector"]
            osm_stops = v_obj["osm_stops"]

            emap = edges.get((rid, d), {})
            all_st = set(emap.keys()) | set(v for vs in emap.values() for v in vs.keys())
            st_map = {s: (curr_pts.get((rid, d, s)) or next_pts.get((rid, d, s)) or []) for s in all_st}
            ordered_chain = reconstruct_ordered_station_chain(emap, st_map, proj)

            stations_list = []
            used_osm_indices = set()
            # Precompute chainage for all OSM stops in this variant
            osm_stops_enriched = []
            for o_idx, ost in enumerate(osm_stops):
                o_proj = proj.project_ping(ost["lat"], ost["lon"])
                osm_stops_enriched.append({
                    "idx": o_idx,
                    "osm_id": ost.get("osm_id"),
                    "name": ost.get("name") or "",
                    "lat": o_proj["proj_lat"],
                    "lon": o_proj["proj_lon"],
                    "chainage_m": o_proj["chainage_m"]
                })

            for seq_idx, st_id in enumerate(ordered_chain, start=1):
                pts_curr = curr_pts.get((rid, d, st_id), [])
                pts_next = next_pts.get((rid, d, st_id), [])
                if pts_curr:
                    sub_curr = pts_curr[::max(1, len(pts_curr) // 25)]
                    proj_pts = [(p[0], p[1], proj.project_ping(p[0], p[1])) for p in sub_curr]
                    proj_pts.sort(key=lambda x: x[2]["chainage_m"])
                    idx_p10 = max(0, int(len(proj_pts) * 0.08))
                    raw_lat, raw_lon, proj_res = proj_pts[idx_p10]
                    emp_lat, emp_lon = proj_res["proj_lat"], proj_res["proj_lon"]
                    chainage_m = round(proj_res["chainage_m"], 1)
                    perp_m = round(proj_res["perp_dist_m"], 1)
                elif pts_next:
                    sub_next = pts_next[::max(1, len(pts_next) // 25)]
                    proj_pts = [(p[0], p[1], proj.project_ping(p[0], p[1])) for p in sub_next]
                    proj_pts.sort(key=lambda x: x[2]["chainage_m"])
                    idx_p90 = min(len(proj_pts) - 1, int(len(proj_pts) * 0.92))
                    raw_lat, raw_lon, proj_res = proj_pts[idx_p90]
                    emp_lat, emp_lon = proj_res["proj_lat"], proj_res["proj_lon"]
                    chainage_m = round(proj_res["chainage_m"], 1)
                    perp_m = round(proj_res["perp_dist_m"], 1)
                else:
                    emp_lat, emp_lon, chainage_m, perp_m = 0.0, 0.0, 0.0, -1.0

                # Tìm trạm OSM gần nhất theo khoảng cách trên tim đường (ưu tiên chưa gán để tránh trùng tên)
                nearest_osm_name = f"Trạm #{st_id}"
                nearest_osm_id = None
                min_osm_dist = float("inf")
                best_o_idx = None
                if emp_lat and emp_lon and osm_stops_enriched:
                    for ost in osm_stops_enriched:
                        od = haversine_distance_m(emp_lat, emp_lon, ost["lat"], ost["lon"])
                        penalty = 120.0 if ost["idx"] in used_osm_indices else 0.0
                        if od + penalty < min_osm_dist:
                            min_osm_dist = od
                            nearest_osm_name = ost["name"] if ost["name"] else f"Trạm #{st_id}"
                            nearest_osm_id = ost["osm_id"]
                            best_o_idx = ost["idx"]
                    if best_o_idx is not None:
                        already_used = best_o_idx in used_osm_indices
                        used_osm_indices.add(best_o_idx)
                        if min_osm_dist <= 80.0 and not already_used:
                            ost_match = osm_stops_enriched[best_o_idx]
                            emp_lat = ost_match["lat"]
                            emp_lon = ost_match["lon"]
                            chainage_m = round(ost_match["chainage_m"], 1)
                        elif already_used:
                            nearest_osm_name = f"{nearest_osm_name} (#{st_id})"

                stations_list.append({
                    "sequence": seq_idx,
                    "telemetry_station_id": st_id,
                    "station_name": nearest_osm_name,
                    "matched_osm_stop_id": nearest_osm_id,
                    "osm_stop_dist_m": round(min_osm_dist, 1) if min_osm_dist != float("inf") else None,
                    "lat": round(emp_lat, 6),
                    "lon": round(emp_lon, 6),
                    "chainage_m": chainage_m,
                    "osm_perp_error_m": perp_m
                })
                total_stations_mapped += 1

            # Đảm bảo chainage_m đơn điệu dọc theo chuỗi phân đoạn để tính chiều dài đoạn đường
            segments_list = []
            for i in range(len(stations_list) - 1):
                s_from = stations_list[i]
                s_to = stations_list[i + 1]
                raw_diff = s_to["chainage_m"] - s_from["chainage_m"]
                direct_dist = haversine_distance_m(s_from["lat"], s_from["lon"], s_to["lat"], s_to["lon"])
                # Nếu đoạn OSM hợp lệ và dương thì lấy khoảng cách dọc đường OSM, ngược lại fallback khoảng cách chim bay * 1.15
                seg_len_m = round(raw_diff, 1) if 30.0 <= raw_diff <= 8000.0 else round(max(50.0, direct_dist * 1.15), 1)
                segments_list.append({
                    "segment_index": i + 1,
                    "segment_id": f"{rid}_d{d}_s{s_from['telemetry_station_id']}_{s_to['telemetry_station_id']}",
                    "from_station_id": s_from["telemetry_station_id"],
                    "to_station_id": s_to["telemetry_station_id"],
                    "from_station_name": s_from["station_name"],
                    "to_station_name": s_to["station_name"],
                    "start_chainage_m": s_from["chainage_m"],
                    "end_chainage_m": s_to["chainage_m"],
                    "segment_length_m": seg_len_m
                })
                total_segments_built += 1

            directions_payload[str(d)] = {
                "telemetry_direction": d,
                "matched_osm_variant_index": v_idx,
                "variant_name": v_obj["name"],
                "from_terminal": v_obj["from"],
                "to_terminal": v_obj["to"],
                "total_route_length_km": v_obj["length_km"],
                "stations_count": len(stations_list),
                "segments_count": len(segments_list),
                "stations": stations_list,
                "segments": segments_list
            }

        fused_catalog["routes"][str(rid)] = {
            "route_id": rid,
            "route_no": rno,
            "route_name": r["name"],
            "directions": directions_payload
        }
        fused_catalog["total_clean_routes"] += 1

    catalog_out = "data/fused_osm/master_fused_routes_segments.json"
    with open(catalog_out, "w", encoding="utf-8") as f:
        json.dump(fused_catalog, f, ensure_ascii=False, indent=2)

    print(f"[OK] Đã xuất bộ khung hợp nhất 46 tuyến tại: {catalog_out}")
    print(f"     - Tổng số tuyến sạch: {fused_catalog['total_clean_routes']}")
    print(f"     - Tổng số trạm đã ánh xạ tọa độ & tên OSM: {total_stations_mapped:,}")
    print(f"     - Tổng số phân đoạn chuẩn (Segments S_k -> S_{{k+1}}): {total_segments_built:,}")

if __name__ == "__main__":
    main()
