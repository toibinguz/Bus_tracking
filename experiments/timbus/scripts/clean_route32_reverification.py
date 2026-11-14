#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tái đo đạc sạch (không dựa JSON suy diễn cũ) từ 30 cặp raw_busmap_captures & raw_timbus_captures
trên Tuyến 32 và kiểm chứng thuật toán chọn xe trung tâm với:
- Ngưỡng cross-track cứng <= 35.0 m (xe vượt 35m bị loại vì vị trí s trên polyline không xác định được -> nhảy sang xe kế B2, B3)
- Dung sai chạm trạm: TimBus s <= s_S + 15.0m; BusMap s <= s_S
- Định nghĩa đúng nhãn fallback (phân biệt rõ chỉ có 1 xe, 2 xe, hay đủ 3 xe).
"""

from __future__ import annotations

import glob
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from config.system_config import MAX_CORRIDOR_CROSS_TRACK_M  # noqa: E402
from experiments.timbus.timbus_tracker import TimBusClient  # noqa: E402
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel  # noqa: E402

DATA_DIR = ROOT / "experiments/timbus/data"
BM_DB = ROOT / "data/hanoi_bus_system.db"
OUT_PATH = DATA_DIR / "clean_route32_reverification.json"

TIMBUS_STATION_TOL_M = 15.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6378137.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * r * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def main() -> None:
    con = sqlite3.connect(f"file:{BM_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    shapes: Dict[str, ShapeProjectionModel] = {}
    stations: Dict[str, List[Dict[str, Any]]] = {}
    for d_str in ("go", "re"):
        pts = [
            (int(r["point_order"]), float(r["lat"]), float(r["lon"]), float(r["cum_distance_m"]))
            for r in con.execute(
                "SELECT point_order, lat, lon, cum_distance_m FROM canonical_shape_master "
                "WHERE route_code='32' AND direction=? ORDER BY point_order",
                (d_str,),
            )
        ]
        shapes[d_str] = ShapeProjectionModel.build(pts)
        stations[d_str] = [
            dict(r)
            for r in con.execute(
                "SELECT station_order, station_id, station_name, lat, lon, cum_distance_m "
                "FROM canonical_station_master WHERE route_code='32' AND direction=? ORDER BY station_order",
                (d_str,),
            )
        ]
    con.close()

    bm_files = sorted(glob.glob(str(DATA_DIR / "raw_busmap_captures" / "busmap_sweep_*.json")))
    tb_files = sorted(glob.glob(str(DATA_DIR / "raw_timbus_captures" / "timbus_sweep_*.json")))
    assert len(bm_files) == len(tb_files) == 30, f"Unexpected capture counts: {len(bm_files)}, {len(tb_files)}"

    total_station_evals = 0
    has_bm_candidate = 0
    bm_over_ct_skipped = 0
    tb_selected_count = 0
    tb_over_ct_skipped = 0
    tb_passed_station_skipped = 0
    tb_saved_by_tolerance_15m = 0
    tb_fallback_to_bm = 0
    fallback_reasons: Dict[str, int] = {}

    for bm_p, tb_p in zip(bm_files, tb_files):
        bm_raw = json.loads(Path(bm_p).read_text(encoding="utf-8"))
        tb_raw = json.loads(Path(tb_p).read_text(encoding="utf-8")).get("unique_buses", {})

        # Gom xe BusMap theo hướng + chiếu Frenet
        bm_by_dir: Dict[str, List[Dict[str, Any]]] = {"go": [], "re": []}
        for k, v in bm_raw.items():
            d_str = v.get("direction_api")
            if d_str not in ("go", "re"):
                continue
            plate = TimBusClient.normalize_plate(v.get("plate_norm") or k)
            s_bm, ct_bm, _ = shapes[d_str].project_point(float(v["lat"]), float(v["lon"]))
            bm_by_dir[d_str].append({
                "plate": plate,
                "lat": float(v["lat"]),
                "lng": float(v["lon"]),
                "s": s_bm,
                "ct": ct_bm,
            })

        # Duyệt qua tất cả trạm trung tuyến (bỏ trạm đầu order=0)
        for d_str in ("go", "re"):
            sm = shapes[d_str]
            for st in stations[d_str]:
                if int(st["station_order"]) == 0:
                    continue
                total_station_evals += 1
                s_S = float(st["cum_distance_m"])

                # Bước 1: Tìm các xe BusMap hợp lệ đang tiến tới trạm S (s <= s_S, ct <= 35m)
                raw_approaching = [b for b in bm_by_dir[d_str] if b["s"] <= s_S]
                valid_approaching = []
                for b in raw_approaching:
                    if b["ct"] > MAX_CORRIDOR_CROSS_TRACK_M:
                        bm_over_ct_skipped += 1
                        continue
                    valid_approaching.append(b)
                if not valid_approaching:
                    continue
                has_bm_candidate += 1
                valid_approaching.sort(key=lambda b: b["s"], reverse=True)
                top3 = valid_approaching[:3]  # B1, B2, B3

                # Bước 2: Đánh giá TimBus trên cụm B1, B2, B3 với lọc ct <= 35m & s_tb <= s_S + 15m
                chosen_tb = None
                cand_issues = []
                for idx, b in enumerate(top3, 1):
                    tb_rec = tb_raw.get(b["plate"])
                    if not tb_rec:
                        cand_issues.append(f"B{idx}:missing_tb")
                        continue
                    s_tb, ct_tb, _ = sm.project_point(float(tb_rec["lat"]), float(tb_rec["lon"]))
                    if ct_tb > MAX_CORRIDOR_CROSS_TRACK_M:
                        tb_over_ct_skipped += 1
                        cand_issues.append(f"B{idx}:over_ct")
                        continue
                    if s_tb > s_S + TIMBUS_STATION_TOL_M:
                        tb_passed_station_skipped += 1
                        cand_issues.append(f"B{idx}:passed_15m")
                        continue
                    # Kiểm tra có nhờ dung sai +15m mà giữ được không
                    if chosen_tb is None or s_tb > chosen_tb["s_tb"]:
                        chosen_tb = {
                            "plate": b["plate"],
                            "from_rank": idx,
                            "s_tb": s_tb,
                            "ct_tb": ct_tb,
                            "in_0_to_15m": s_S < s_tb <= s_S + TIMBUS_STATION_TOL_M,
                        }
                if chosen_tb is not None:
                    tb_selected_count += 1
                    if chosen_tb["in_0_to_15m"]:
                        tb_saved_by_tolerance_15m += 1
                else:
                    tb_fallback_to_bm += 1
                    key = f"n={len(top3)}|" + ",".join(cand_issues)
                    fallback_reasons[key] = fallback_reasons.get(key, 0) + 1

    out = {
        "total_station_evals": total_station_evals,
        "has_valid_bm_candidate_evals": has_bm_candidate,
        "tb_selected_count": tb_selected_count,
        "tb_selected_pct": round(100.0 * tb_selected_count / max(1, has_bm_candidate), 2),
        "tb_saved_by_15m_tolerance": tb_saved_by_tolerance_15m,
        "tb_fallback_to_bm_count": tb_fallback_to_bm,
        "bm_over_ct_skipped_total": bm_over_ct_skipped,
        "tb_over_ct_skipped_total": tb_over_ct_skipped,
        "tb_passed_station_skipped_total": tb_passed_station_skipped,
        "fallback_breakdown_exact": dict(sorted(fallback_reasons.items(), key=lambda kv: -kv[1])),
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
