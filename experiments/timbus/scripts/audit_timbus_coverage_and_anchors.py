#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audit toàn diện độ phủ và bộ trạm neo (terminal + penultimate) của TimBus trên toàn bộ 176 tuyến BusMap.
Sửa các lỗ hổng phương pháp của kịch bản cũ:
1. Dùng danh sách xe đang chạy thực tế từ BusMap (`live_busmap_snapshot_176.json`), chọn tối đa 3 xe giữa tuyến.
2. Truy vấn ĐÍCH DANH từng biển số (`vehicle_param=plate`, `route_param=""`), không bao giờ quét rỗng `vehicle_param=""`.
3. Kiểm tra ĐỘC LẬP cả 2 chiều `go (0)` và `re (1)`.
4. Ưu tiên neo chuẩn theo `routes.json` (`Stops[-1]` rồi `Stops[-2]`) theo đúng hướng dẫn người dùng;
   nếu rỗng hoặc tuyến không có trong `routes.json`, đối chiếu thêm neo từ `hanoi_bus_system.db` (`last` rồi `penult`).
5. Xuất kết quả chi tiết ra `experiments/timbus/data/timbus_full_audit_176.json`.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experiments.timbus.timbus_tracker import TimBusClient  # noqa: E402
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel  # noqa: E402

SNAPSHOT_PATH = ROOT / "experiments/timbus/data/live_busmap_snapshot_176.json"
ROUTES_JSON_PATH = ROOT / "experiments/timbus/routes.json"
BUSMAP_DB_PATH = ROOT / "data/hanoi_bus_system.db"
OUT_PATH = ROOT / "experiments/timbus/data/timbus_full_audit_176.json"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6378137.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * r * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def match_routes_json_key(route_code: str, rj_map: Dict[str, Dict[str, Any]]) -> Tuple[Optional[str], str]:
    c = route_code.strip().upper()
    if c in rj_map:
        return c, "exact"
    for suffix in ("CT", "TC"):
        if c.endswith(suffix) and c[: -len(suffix)] in rj_map:
            return c[: -len(suffix)], f"stripped_{suffix}"
    if c + "CT" in rj_map:
        return c + "CT", "added_CT"
    if c + "TC" in rj_map:
        return c + "TC", "added_TC"
    return None, "none"


def load_shape_models() -> Dict[Tuple[int, str], ShapeProjectionModel]:
    con = sqlite3.connect(f"file:{BUSMAP_DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT route_id, direction, point_order, lat, lon, cum_distance_m "
        "FROM canonical_shape_master ORDER BY route_id, direction, point_order"
    ).fetchall()
    con.close()
    grouped: Dict[Tuple[int, str], List[Tuple[int, float, float, float]]] = {}
    for rid, dstr, pord, lat, lon, cum in rows:
        grouped.setdefault((int(rid), str(dstr)), []).append((int(pord), float(lat), float(lon), float(cum)))
    models: Dict[Tuple[int, str], ShapeProjectionModel] = {}
    for key, pts in grouped.items():
        if len(pts) >= 2:
            models[key] = ShapeProjectionModel.build(pts)
    return models


def load_bm_terminals() -> Dict[Tuple[int, int], Tuple[Optional[int], Optional[int], float]]:
    con = sqlite3.connect(f"file:{BUSMAP_DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT route_id, direction, station_order, station_id, cum_distance_m "
        "FROM canonical_station_master ORDER BY route_id, direction, station_order"
    ).fetchall()
    con.close()
    grouped: Dict[Tuple[int, int], List[Tuple[int, int, float]]] = {}
    for rid, dstr, sord, sid, cum in rows:
        d_int = 0 if dstr == "go" else 1
        grouped.setdefault((int(rid), d_int), []).append((int(sord), int(sid), float(cum)))
    out: Dict[Tuple[int, int], Tuple[Optional[int], Optional[int], float]] = {}
    for key, lst in grouped.items():
        last_sid = lst[-1][1] if lst else None
        penult_sid = lst[-2][1] if len(lst) >= 2 else None
        total_m = lst[-1][2] if lst else 0.0
        out[key] = (last_sid, penult_sid, total_m)
    return out


def pick_representative_buses(
    buses: List[Dict[str, Any]],
    shape_model: Optional[ShapeProjectionModel],
    total_m: float,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Ưu tiên tối đa 3 xe đang nằm giữa hành trình (tránh xe nằm sát đầu/cuối bến)."""
    if not buses:
        return []
    scored = []
    for b in buses:
        lat = float(b.get("Lat", 0.0))
        lng = float(b.get("Lng", 0.0))
        plate = TimBusClient.normalize_plate(str(b.get("VehicleNumber") or ""))
        if not plate or lat == 0.0 or lng == 0.0:
            continue
        if shape_model is not None and total_m > 0:
            s_m, ct_m, _ = shape_model.project_point(lat, lng)
            ratio = s_m / total_m
            # Ưu tiên xe có tốc độ > 0 và nằm giữa tuyến [0.15, 0.85], ct <= 35m
            spd = float(b.get("Speed", 0.0))
            mid_score = (0 if ct_m <= 35.0 else 10, 0 if 0.15 <= ratio <= 0.85 else 1, 0 if spd > 0 else 1, abs(ratio - 0.5))
        else:
            s_m, ct_m = 0.0, 0.0
            mid_score = (0, 0, 0, 0.0)
        scored.append((mid_score, {
            "plate": plate,
            "lat": lat,
            "lng": lng,
            "speed_bm": float(b.get("Speed", 0.0)),
            "s_bm": round(s_m, 1),
            "ct_bm": round(ct_m, 1),
        }))
    scored.sort(key=lambda x: x[0])
    return [x[1] for x in scored[:limit]]


def probe_pair(task: Dict[str, Any]) -> Dict[str, Any]:
    rid = task["route_id"]
    rcode = task["route_code"]
    d = task["direction"]
    reps = task["rep_buses"]
    rj_last = task["rj_last_sid"]
    rj_penult = task["rj_penult_sid"]
    bm_last = task["bm_last_sid"]
    bm_penult = task["bm_penult_sid"]
    shape_model: Optional[ShapeProjectionModel] = task["shape_model"]

    if not reps:
        return {
            **{k: task[k] for k in ("route_id", "route_code", "direction", "rj_code", "rj_match_type", "rj_last_sid", "rj_penult_sid", "bm_last_sid", "bm_penult_sid", "bus_count_bm")},
            "status": "NO_ACTIVE_BUSMAP_FLEET",
            "working_anchor_source": None,
            "working_station_id": None,
            "working_penult_id": None,
            "hits": [],
        }

    # Xây dựng danh sách candidate anchors giữ đúng thứ tự ưu tiên:
    # 1) routes.json last -> routes.json penultimate
    # 2) hanoi_bus_system.db last -> hanoi_bus_system.db penultimate (chỉ thử nếu (1) rỗng)
    candidates: List[Tuple[str, int]] = []
    seen_sid = set()
    for src, sid in (
        ("rj_last", rj_last),
        ("rj_penult", rj_penult),
        ("bm_last", bm_last),
        ("bm_penult", bm_penult),
    ):
        if sid and int(sid) > 0 and int(sid) not in seen_sid:
            seen_sid.add(int(sid))
            candidates.append((src, int(sid)))

    anchor_results: Dict[str, Any] = {}
    first_working_src: Optional[str] = None
    first_working_sid: Optional[int] = None
    hits: List[Dict[str, Any]] = []
    errors = 0

    for src, sid in candidates:
        # Nếu đã trúng từ nhóm routes.json rồi thì không cần thử sang bm_* nữa (trừ kiểm tra trạm kế cuối đã nằm sẵn)
        if first_working_src is not None and src.startswith("bm_"):
            break
        src_hits = []
        for b in reps:
            try:
                rec = TimBusClient.query_targeted_vehicle(
                    station_id=sid,
                    route_code="",
                    plate=b["plate"],
                    direction=d,
                    timeout=3,
                )
            except Exception:
                errors += 1
                rec = None
            if rec is not None:
                dist_bm_tb = haversine_m(b["lat"], b["lng"], rec.latitude, rec.longitude)
                if shape_model is not None:
                    s_tb, ct_tb, _ = shape_model.project_point(rec.latitude, rec.longitude)
                else:
                    s_tb, ct_tb = 0.0, 0.0
                src_hits.append({
                    "plate": b["plate"],
                    "tb_route": rec.route,
                    "tb_dest": rec.destination_name,
                    "tb_speed_kmh": rec.speed_kmh,
                    "tb_status": rec.status,
                    "dist_bm_tb_m": round(dist_bm_tb, 1),
                    "s_bm_m": b["s_bm"],
                    "s_tb_m": round(s_tb, 1),
                    "ct_tb_m": round(ct_tb, 1),
                    "dist_to_anchor_m": rec.distance_to_queried_station_m,
                })
            time.sleep(0.03)
        anchor_results[f"{src}:{sid}"] = len(src_hits)
        if src_hits and first_working_src is None:
            first_working_src = src
            first_working_sid = sid
            hits = src_hits
            # Nếu routes.json last đã trúng thì vẫn test nhanh routes.json penultimate cho 1 xe để xác nhận bảo hiểm/so khớp
            if src == "rj_last" and rj_penult and rj_penult != rj_last:
                try:
                    rec_p = TimBusClient.query_targeted_vehicle(
                        station_id=int(rj_penult),
                        route_code="",
                        plate=hits[0]["plate"],
                        direction=d,
                        timeout=3,
                    )
                    anchor_results[f"rj_penult_verify:{rj_penult}"] = 1 if rec_p else 0
                except Exception:
                    anchor_results[f"rj_penult_verify:{rj_penult}"] = -1
            break

    status = "TIMBUS_ACTIVE" if hits else ("TIMBUS_EMPTY_ALL_ANCHORS" if errors == 0 else "TIMBUS_EMPTY_WITH_ERRORS")
    return {
        "route_id": rid,
        "route_code": rcode,
        "direction": d,
        "rj_code": task["rj_code"],
        "rj_match_type": task["rj_match_type"],
        "rj_last_sid": rj_last,
        "rj_penult_sid": rj_penult,
        "bm_last_sid": bm_last,
        "bm_penult_sid": bm_penult,
        "bus_count_bm": task["bus_count_bm"],
        "rep_plates": [b["plate"] for b in reps],
        "status": status,
        "working_anchor_source": first_working_src,
        "working_station_id": first_working_sid,
        "anchor_probes": anchor_results,
        "hits": hits,
    }


def main() -> None:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    rj_list = json.loads(ROUTES_JSON_PATH.read_text(encoding="utf-8"))
    rj_map = {r["FleetCode"].strip().upper(): r for r in rj_list}
    shape_models = load_shape_models()
    bm_terminals = load_bm_terminals()

    tasks: List[Dict[str, Any]] = []
    for item in snapshot["routes"]:
        rid = int(item["route_id"])
        rcode = str(item["route_code"]).strip()
        d = int(item["direction"])
        d_str = "go" if d == 0 else "re"
        rj_key, rj_match_type = match_routes_json_key(rcode, rj_map)
        rj_last_sid = None
        rj_penult_sid = None
        if rj_key is not None:
            stops = rj_map[rj_key]["StopsGo" if d == 0 else "StopsReturn"]
            if stops:
                rj_last_sid = int(stops[-1]["station_id"])
                if len(stops) >= 2:
                    rj_penult_sid = int(stops[-2]["station_id"])
        bm_last_sid, bm_penult_sid, total_m = bm_terminals.get((rid, d), (None, None, 0.0))
        sm = shape_models.get((rid, d_str))
        reps = pick_representative_buses(item["buses"], sm, total_m, limit=3)
        tasks.append({
            "route_id": rid,
            "route_code": rcode,
            "direction": d,
            "rj_code": rj_key,
            "rj_match_type": rj_match_type,
            "rj_last_sid": rj_last_sid,
            "rj_penult_sid": rj_penult_sid,
            "bm_last_sid": bm_last_sid,
            "bm_penult_sid": bm_penult_sid,
            "bus_count_bm": item["bus_count"],
            "rep_buses": reps,
            "shape_model": sm,
        })

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(probe_pair, t) for t in tasks]
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(key=lambda x: (x["route_id"], x["direction"]))

    summary = {
        "audited_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_route_dir_pairs": len(results),
        "pairs_with_active_busmap": sum(1 for r in results if r["status"] != "NO_ACTIVE_BUSMAP_FLEET"),
        "pairs_no_busmap": sum(1 for r in results if r["status"] == "NO_ACTIVE_BUSMAP_FLEET"),
        "timbus_active_pairs": sum(1 for r in results if r["status"] == "TIMBUS_ACTIVE"),
        "timbus_empty_pairs": sum(1 for r in results if r["status"] != "NO_ACTIVE_BUSMAP_FLEET" and r["status"] != "TIMBUS_ACTIVE"),
        "by_anchor_source": {},
        "timbus_active_routes": sorted({r["route_code"] for r in results if r["status"] == "TIMBUS_ACTIVE"}),
        "timbus_empty_routes_with_bm_buses": sorted({
            r["route_code"] for r in results
            if r["status"] != "NO_ACTIVE_BUSMAP_FLEET" and r["status"] != "TIMBUS_ACTIVE"
        }),
    }
    for r in results:
        src = r["working_anchor_source"]
        if src:
            summary["by_anchor_source"][src] = summary["by_anchor_source"].get(src, 0) + 1

    OUT_PATH.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
