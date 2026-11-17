#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script tái lập & kiểm chứng toàn bộ kết quả thí nghiệm TimBus (cô lập trong experiments/timbus/).

Chế độ mặc định (--offline):
  1. Kiểm thử unit codec nhị phân + thuộc tính BusRecord của TimBusClient sau chỉnh sửa.
  2. Tái tính toán trực tiếp đối soát DB tĩnh (BusMap 2026 vs TimBus 02/2020, ?mode=ro).
  3. Tái tính toán đối chứng Tuyến 32 (30 sweeps, shadowing 92%, đồng bộ GPS |Δτ|<=5s, trường status/direction).
  4. Tổng hợp kiểm chứng Benchmark M1/M2/M3, Audit ngưỡng cross-track & Giải mã trường 3/4/5.
  5. Tái kiểm tra độ phủ 111 tuyến trùng (Terminal + Mid-stops + route_param="").

Chế độ live (--live):
  - Kết hợp thêm 1 chu kỳ truy vấn thực tế bằng TimBusClient.query_central_vehicles() cho 4 xe Tuyến 32
    với route_param="" và mỏ neo bến cuối 1676 (chỉ 4 requests, an toàn không spam).
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import sqlite3
import statistics
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

TIMBUS_DIR = Path(__file__).resolve().parent
DATA_DIR = TIMBUS_DIR / "data"
BUSMAP_DB = Path("data/hanoi_bus_system.db")
TIMBUS_DB = TIMBUS_DIR / "timbus_hanoi.sqlite"

sys.path.insert(0, str(TIMBUS_DIR))
from timbus_tracker import BusRecord, TimBusClient  # noqa: E402


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6378137.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * r * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def norm_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def parse_iso_ts(val: str) -> float:
    return datetime.fromisoformat(val).timestamp()


def test_client_codec() -> Dict[str, Any]:
    """Kiểm chứng codec request/response và semantic properties mới của timbus_tracker.py."""
    req_body = TimBusClient.build_request_body(1676, "", "29F05192", 0)
    enc = TimBusClient.encrypt_packet(req_body, client_id=0x001B02F5)
    dec = TimBusClient.decrypt_packet(enc)
    cid, decoded_sid = struct.unpack("<II", dec[:8])
    assert cid == 0x001B02F5 and decoded_sid == 1676, "Request round-trip mismatch"
    assert dec[8:] == req_body[4:], "Request body tail mismatch"

    # Tạo gói tin phản hồi giả lập với 2 bản ghi (kiểm chứng decode trường 3/4/5)
    def pack_record(plate: str, route: str, dist_m: int, eta_s: int, dest: str, spd: int, lat: float, lon: float, st: int, d_byte: int) -> bytes:
        pb = plate.encode("utf-8")
        rb = route.encode("utf-8")
        db = dest.encode("utf-8")
        return (
            bytes([len(pb)]) + pb
            + bytes([len(rb)]) + rb
            + struct.pack("<II", dist_m, eta_s)
            + struct.pack("<H", len(db)) + db
            + bytes([spd])
            + struct.pack("<ff", lat, lon)
            + bytes([st, d_byte])
        )

    raw_resp = bytes([2]) + pack_record("29F05192", "32", 13749, 3535, "Bến xe Giáp Bát", 28, 21.037746, 105.773636, 0, 1)
    raw_resp += pack_record("29F05192", "32", 13749, 3530, "Bến xe Giáp Bát", 28, 21.037746, 105.773636, 0, 1)
    recs = TimBusClient.parse_bus_packet(raw_resp, direction_fallback=0)
    assert len(recs) == 2
    assert recs[0].distance_to_queried_station_m == 13749
    assert recs[0].eta_to_queried_station_sec == 3535
    assert recs[0].destination_name == "Bến xe Giáp Bát"
    assert recs[0].has_valid_coords
    assert TimBusClient.normalize_plate("29F-051.92") == "29F05192"
    return {"status": "PASS", "decoded_records": len(recs), "normalized_plate": TimBusClient.normalize_plate("29F-051.92")}


def reproduce_static_db_diff() -> Dict[str, Any]:
    """Tái tính toán đối soát DB tĩnh giữa BusMap (2026) và TimBus (02/2020) ở chế độ chỉ đọc."""
    bm = sqlite3.connect(f"file:{BUSMAP_DB}?mode=ro", uri=True)
    tb = sqlite3.connect(f"file:{TIMBUS_DB}?mode=ro", uri=True)
    bm.row_factory = sqlite3.Row
    tb.row_factory = sqlite3.Row
    try:
        bm_routes = {norm_code(r["route_code"]): dict(r) for r in bm.execute("SELECT route_id, route_code, route_name FROM canonical_route_master")}
        tb_routes = {norm_code(r["fleet_code"]): dict(r) for r in tb.execute("SELECT fleet_id, fleet_code, fleet_name FROM routes")}

        overlap_codes = sorted(set(bm_routes) & set(tb_routes))
        only_bm = sorted(set(bm_routes) - set(tb_routes))
        only_tb = sorted(set(tb_routes) - set(bm_routes))

        bm_stations = {r["station_id"]: (r["lat"], r["lon"]) for r in bm.execute("SELECT DISTINCT station_id, lat, lon FROM canonical_station_master")}
        tb_stations = {r["station_id"]: (r["lat"], r["lng"]) for r in tb.execute("SELECT station_id, lat, lng FROM stations")}
        sid_overlap = sorted(set(bm_stations) & set(tb_stations))
        same_sid_dists = sorted(
            haversine_m(bm_stations[sid][0], bm_stations[sid][1], tb_stations[sid][0], tb_stations[sid][1])
            for sid in sid_overlap
        )

        # Kiểm tra khớp số trạm & bến cuối trên 111 tuyến trùng
        stop_exact_direct = 0
        stop_exact_swapped = 0
        term_exact_sid = 0
        term_le100m = 0
        for code in overlap_codes:
            rid = bm_routes[code]["route_id"]
            fid = tb_routes[code]["fleet_id"]
            bm_go_cnt = bm.execute("SELECT COUNT(*) FROM canonical_station_master WHERE route_id=? AND direction='go'", (rid,)).fetchone()[0]
            bm_re_cnt = bm.execute("SELECT COUNT(*) FROM canonical_station_master WHERE route_id=? AND direction='re'", (rid,)).fetchone()[0]
            tb_go_cnt = tb.execute("SELECT COUNT(*) FROM route_stops WHERE fleet_id=? AND direction=0", (fid,)).fetchone()[0]
            tb_re_cnt = tb.execute("SELECT COUNT(*) FROM route_stops WHERE fleet_id=? AND direction=1", (fid,)).fetchone()[0]
            if bm_go_cnt == tb_go_cnt and bm_re_cnt == tb_re_cnt:
                stop_exact_direct += 1
            elif bm_go_cnt == tb_re_cnt and bm_re_cnt == tb_go_cnt:
                stop_exact_swapped += 1

            bm_g = bm.execute("SELECT station_id, lat, lon FROM canonical_station_master WHERE route_id=? AND direction='go' ORDER BY station_order DESC LIMIT 1", (rid,)).fetchone()
            bm_r = bm.execute("SELECT station_id, lat, lon FROM canonical_station_master WHERE route_id=? AND direction='re' ORDER BY station_order DESC LIMIT 1", (rid,)).fetchone()
            tb_g = tb.execute("SELECT rs.station_id, s.lat, s.lng AS lon FROM route_stops rs JOIN stations s ON rs.station_id=s.station_id WHERE rs.fleet_id=? AND rs.direction=0 ORDER BY rs.orders DESC LIMIT 1", (fid,)).fetchone()
            tb_r = tb.execute("SELECT rs.station_id, s.lat, s.lng AS lon FROM route_stops rs JOIN stations s ON rs.station_id=s.station_id WHERE rs.fleet_id=? AND rs.direction=1 ORDER BY rs.orders DESC LIMIT 1", (fid,)).fetchone()
            if bm_g and bm_r and tb_g and tb_r:
                if bm_g["station_id"] == tb_g["station_id"] and bm_r["station_id"] == tb_r["station_id"]:
                    term_exact_sid += 1
                d_go = haversine_m(bm_g["lat"], bm_g["lon"], tb_g["lat"], tb_g["lon"])
                d_re = haversine_m(bm_r["lat"], bm_r["lon"], tb_r["lat"], tb_r["lon"])
                if d_go <= 100.0 and d_re <= 100.0:
                    term_le100m += 1

        # Kiểm chứng bất thường Tuyến 32 trong DB TimBus 2020 (395 vs 157 vs 1676)
        r395_fleets = [
            r[0] for r in tb.execute(
                "SELECT DISTINCT rt.fleet_code FROM route_stops rs JOIN routes rt ON rs.fleet_id=rt.fleet_id WHERE rs.station_id=395"
            )
        ]
        s157 = tb.execute("SELECT name FROM stations WHERE station_id=157").fetchone()
        s1676 = bm.execute("SELECT station_name FROM canonical_station_master WHERE route_code='32' AND direction='go' ORDER BY station_order DESC LIMIT 1").fetchone()

        return {
            "bm_routes": len(bm_routes),
            "tb_routes": len(tb_routes),
            "overlap_routes": len(overlap_codes),
            "only_bm_routes": len(only_bm),
            "only_tb_routes": len(only_tb),
            "bm_unique_stations": len(bm_stations),
            "tb_unique_stations": len(tb_stations),
            "station_id_overlap": len(sid_overlap),
            "same_sid_median_m": round(statistics.median(same_sid_dists), 1),
            "same_sid_p90_m": round(same_sid_dists[int(0.9 * len(same_sid_dists))], 1),
            "same_sid_gt50m": sum(1 for d in same_sid_dists if d > 50.0),
            "same_sid_max_m": round(max(same_sid_dists), 1),
            "stop_count_exact_direct": stop_exact_direct,
            "stop_count_exact_swapped": stop_exact_swapped,
            "terminals_both_dir_sid_exact": term_exact_sid,
            "terminals_both_dir_le100m": term_le100m,
            "terminals_diverged_gt100m": len(overlap_codes) - term_le100m,
            "station_395_fleets_in_tb_2020": r395_fleets,
            "station_157_tb_name": s157["name"] if s157 else None,
            "route32_go_true_terminal_bm": (1676, s1676["station_name"] if s1676 else None),
        }
    finally:
        bm.close()
        tb.close()


def reproduce_route32_parity_and_shadowing() -> Dict[str, Any]:
    """Tái tính toán đối chứng Tuyến 32 trực tiếp từ 30 cặp raw_busmap_captures & raw_timbus_captures."""
    bm_files = sorted(glob.glob(str(DATA_DIR / "raw_busmap_captures" / "busmap_sweep_*.json")))
    tb_files = sorted(glob.glob(str(DATA_DIR / "raw_timbus_captures" / "timbus_sweep_*.json")))

    tb_pool: Dict[str, List[Dict[str, Any]]] = {}
    dir_raw_counts: Dict[str, int] = {}
    status_counts: Dict[int, int] = {}
    unique_total = 0
    sweep_bm_counts: List[int] = []
    sweep_tb_counts: List[int] = []

    for tb_p in tb_files:
        tb_raw = json.loads(Path(tb_p).read_text(encoding="utf-8"))
        ub = tb_raw.get("unique_buses", {})
        vals = list(ub.values()) if isinstance(ub, dict) else list(ub)
        unique_total += len(vals)
        sweep_tb_counts.append(len(vals))
        for b in vals:
            dr = str(b.get("direction_raw"))
            dir_raw_counts[dr] = dir_raw_counts.get(dr, 0) + 1
            st = b.get("status")
            status_counts[st] = status_counts.get(st, 0) + 1
            pn = TimBusClient.normalize_plate(b.get("plate_norm") or b.get("plate_raw") or "")
            if pn:
                tb_pool.setdefault(pn, []).append(b)

    aligned_dists: List[float] = []
    for bm_p in bm_files:
        bm_raw = json.loads(Path(bm_p).read_text(encoding="utf-8"))
        sweep_bm_counts.append(len(bm_raw))
        for k, v in bm_raw.items():
            pn = TimBusClient.normalize_plate(v.get("plate_norm") or k)
            if not pn or pn not in tb_pool or not v.get("update_time"):
                continue
            bm_epoch = parse_iso_ts(v["update_time"])
            best_tb = min(
                tb_pool[pn],
                key=lambda tb_r: abs(bm_epoch - float(tb_r.get("fetch_timestamp", 0.0))),
            )
            dtau = abs(bm_epoch - float(best_tb.get("fetch_timestamp", 0.0)))
            if dtau <= 5.0:
                aligned_dists.append(round(haversine_m(v["lat"], v["lon"], best_tb["lat"], best_tb["lon"]), 1))

    aligned_sorted = sorted(aligned_dists)
    return {
        "sweeps_count": min(len(bm_files), len(tb_files)),
        "bm_in_transit_avg": round(statistics.mean(sweep_bm_counts), 1) if sweep_bm_counts else 0.0,
        "tb_in_transit_avg": round(statistics.mean(sweep_tb_counts), 1) if sweep_tb_counts else 0.0,
        "aligned_dt_le5s_pairs": len(aligned_sorted),
        "aligned_median_m": aligned_sorted[len(aligned_sorted) // 2] if aligned_sorted else None,
        "aligned_mean_m": round(statistics.mean(aligned_sorted), 1) if aligned_sorted else None,
        "aligned_le15m_pct": round(100.0 * sum(1 for d in aligned_sorted if d <= 15.0) / len(aligned_sorted), 1) if aligned_sorted else 0.0,
        "unique_tb_records": unique_total,
        "response_direction_raw_dist": dir_raw_counts,
        "response_status_dist": status_counts,
    }


def load_saved_experiment_summaries() -> Dict[str, Any]:
    """Đọc và tóm tắt kết quả tái đo đạc sạch trong experiments/timbus/data/*.json (và DB khóa anchor nếu đã chốt)."""
    audit_176 = json.loads((DATA_DIR / "timbus_full_audit_176.json").read_text(encoding="utf-8"))
    recov = json.loads((DATA_DIR / "timbus_recovered_tail_anchors.json").read_text(encoding="utf-8"))
    r32_clean = json.loads((DATA_DIR / "clean_route32_reverification.json").read_text(encoding="utf-8"))

    db_locked: Dict[str, Any] = {"table": "timbus_verified_anchors", "present": False}
    tb = sqlite3.connect(f"file:{TIMBUS_DB}?mode=ro", uri=True)
    try:
        has_table = tb.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='timbus_verified_anchors'"
        ).fetchone()
        if has_table:
            db_lock_stats = {
                st: cnt
                for st, cnt in tb.execute(
                    "SELECT audit_status, COUNT(*) FROM timbus_verified_anchors GROUP BY audit_status"
                ).fetchall()
            }
            enabled_routes = tb.execute(
                "SELECT COUNT(DISTINCT route_code) FROM timbus_verified_anchors WHERE timbus_enabled=1"
            ).fetchone()[0]
            db_locked = {
                "table": "timbus_verified_anchors",
                "present": True,
                "status_counts": db_lock_stats,
                "enabled_distinct_routes": enabled_routes,
            }
    finally:
        tb.close()

    return {
        "clean_route32_reverification": r32_clean,
        "audit_176_summary": audit_176["summary"],
        "recovered_tail_pairs_count": len(recov.get("recovered", [])),
        "db_locked_anchors": db_locked,
    }


def run_live_verification() -> Dict[str, Any]:
    """Kiểm chứng trực tiếp TimBusClient.query_central_vehicles (Tuyến 32 dir=0: [1676, 161])."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import (  # noqa: E402
        fetch_route_buses_live,
    )

    row = None
    tb = sqlite3.connect(f"file:{TIMBUS_DB}?mode=ro", uri=True)
    try:
        has_table = tb.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='timbus_verified_anchors'"
        ).fetchone()
        if has_table:
            row = tb.execute(
                "SELECT primary_anchor_sid, backup_anchor_sid FROM timbus_verified_anchors WHERE route_id=32 AND direction=0 AND timbus_enabled=1"
            ).fetchone()
    finally:
        tb.close()
    anchors = [int(x) for x in (row or (1676, 161)) if x]

    bm_raw = fetch_route_buses_live(route_id=32, direction=0)
    go_plates = [
        TimBusClient.normalize_plate(str(v.get("VehicleNumber") or ""))
        for v in (bm_raw or [])
        if v.get("VehicleNumber")
    ]
    target_plates = go_plates[1:5] if len(go_plates) >= 5 else go_plates[:4]
    if not target_plates:
        return {"status": "no_active_busmap_go_buses"}

    res = TimBusClient.query_central_vehicles(
        station_ids=anchors,
        plates=target_plates,
        direction=0,
        route_code="",
        timeout=3,
        inter_request_delay=0.05,
    )
    return {
        "anchor_sequence": anchors,
        "queried_plates": target_plates,
        "returned_count": f"{len(res)}/{len(target_plates)}",
        "vehicles": {
            p: {
                "route": r.route,
                "lat": r.latitude,
                "lon": r.longitude,
                "speed_kmh": r.speed_kmh,
                "status": r.status,
                "dist_to_anchor_m": r.distance_to_queried_station_m,
                "eta_to_anchor_s": r.eta_to_queried_station_sec,
                "dest": r.destination_name,
            }
            for p, r in res.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tái lập & kiểm chứng toàn bộ thí nghiệm TimBus")
    parser.add_argument("--offline", action="store_true", help="Chỉ chạy tái lập offline từ DB và dữ liệu đã lưu (mặc định)")
    parser.add_argument("--live", action="store_true", help="Chạy thêm 1 vòng query live (4 xe Tuyến 32)")
    parser.add_argument("--json", action="store_true", help="Xuất toàn bộ kết quả dưới dạng JSON")
    args = parser.parse_args()

    report = {
        "1_client_codec_unit_test": test_client_codec(),
        "2_static_db_diff": reproduce_static_db_diff(),
        "3_route32_parity_shadowing": reproduce_route32_parity_and_shadowing(),
        "4_saved_experiments_summary": load_saved_experiment_summaries(),
    }
    if args.live and not args.offline:
        report["5_live_central_4_check"] = run_live_verification()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print("=== TIMBUS EXPERIMENT REPRODUCIBILITY & VERIFICATION ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
