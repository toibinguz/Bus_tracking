"""Evaluate a strict physics-grounded Dual-HMM direction classifier on real BusMap & TimBus telemetry."""

from __future__ import annotations

import glob
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.system_config import DEFAULT_DB_PATH, HANOI_BBOX, STALE_DELTA_T_MAX_SEC, TZ_HANOI
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.route_matcher import (
    RouteHMM,
    ShapeProjectionModel,
)


class DualHMMDirectionTracker:
    """Chạy song song RouteHMM(go) & RouteHMM(re) với ràng buộc vật lý để tự suy luận chiều xe."""

    def __init__(
        self,
        shape_go: ShapeProjectionModel,
        shape_re: ShapeProjectionModel,
        init_advance_m: float = 120.0,
        init_lead_m: float = 80.0,
        switch_min_matches: int = 2,
        switch_advance_m: float = 100.0,
        terminal_zone_m: float = 800.0,
    ):
        self.shapes = {"go": shape_go, "re": shape_re}
        self.init_advance_m = init_advance_m
        self.init_lead_m = init_lead_m
        self.switch_min_matches = switch_min_matches
        self.switch_advance_m = switch_advance_m
        self.terminal_zone_m = terminal_zone_m

        self.hmms: Dict[str, RouteHMM] = {}
        self.run_start_s: Dict[str, Optional[float]] = {}
        self.run_last_s: Dict[str, Optional[float]] = {}
        self.consec_matches: Dict[str, int] = {}
        self.recent_misses: Dict[str, int] = {}
        self.locked_dir: Optional[str] = None
        self.last_epoch: Optional[float] = None
        self._obs_idx = 0
        self._init_both()

    def _init_dir(self, d: str) -> None:
        self.hmms[d] = RouteHMM(
            self.shapes[d],
            allow_terminal_wrap=False,
            backward_window_sec=60.0,
            backward_switch_margin=2.0,
        )
        self.run_start_s[d] = None
        self.run_last_s[d] = None
        self.consec_matches[d] = 0
        self.recent_misses[d] = 0

    def _init_both(self) -> None:
        self._init_dir("go")
        self._init_dir("re")
        self.locked_dir = None

    def update(self, epoch: float, lat: float, lng: float) -> Tuple[Optional[str], Optional[float], str]:
        if self.last_epoch is not None and epoch <= self.last_epoch:
            s_out = self.run_last_s[self.locked_dir] if self.locked_dir else None
            return self.locked_dir, s_out, "duplicate_or_late"
        if self.last_epoch is not None and (epoch - self.last_epoch) > STALE_DELTA_T_MAX_SEC:
            self._init_both()
        self.last_epoch = epoch

        idx = self._obs_idx
        self._obs_idx += 1

        matches = {}
        advances = {"go": 0.0, "re": 0.0}
        soft_dead = {"go": False, "re": False}

        for d in ("go", "re"):
            m = self.hmms[d].update(epoch, lat, lng, idx)
            matches[d] = m
            reason = self.hmms[d].reason
            if m is not None:
                if reason == "initialized" or self.run_start_s[d] is None:
                    self.run_start_s[d] = m.s
                    self.consec_matches[d] = 1
                else:
                    self.consec_matches[d] += 1
                self.run_last_s[d] = m.s
                advances[d] = m.s - float(self.run_start_s[d])
                self.recent_misses[d] = 0
            else:
                self.recent_misses[d] += 1
                if reason in ("outside_corridor", "direction_change_pending") or (
                    reason == "no_feasible_transition" and self.recent_misses[d] >= 2
                ):
                    soft_dead[d] = True
                # Nếu nhánh không được lock bị kẹt bởi trạng thái cũ, reset để sẵn sàng bắt chiều mới
                if self.locked_dir != d and reason in ("no_feasible_transition", "direction_change_pending"):
                    self._init_dir(d)

        if self.locked_dir is None:
            cand_dir = None
            for d in ("go", "re"):
                other = "re" if d == "go" else "go"
                if matches[d] is None or advances[d] < self.init_advance_m:
                    continue
                if matches[other] is None or soft_dead[other] or advances[d] >= advances[other] + self.init_lead_m:
                    cand_dir = d
                    break
            if cand_dir is not None:
                self.locked_dir = cand_dir
                return self.locked_dir, matches[self.locked_dir].s, "locked_init"
            return None, None, "unresolved_init"

        cur = self.locked_dir
        other = "re" if cur == "go" else "go"

        # Kiểm tra đảo chiều với ràng buộc vật lý chặt
        last_cur_s = self.run_last_s[cur]
        cur_near_terminal = (
            last_cur_s is not None
            and min(last_cur_s, self.shapes[cur]._total_len - last_cur_s) <= self.terminal_zone_m
        )
        can_abandon_cur = soft_dead[cur] or cur_near_terminal
        if (
            can_abandon_cur
            and matches[other] is not None
            and self.consec_matches[other] >= self.switch_min_matches
            and advances[other] >= self.switch_advance_m
        ):
            self.locked_dir = other
            self._init_dir(cur)
            return self.locked_dir, matches[self.locked_dir].s, "switched"

        s_cur = matches[cur].s if matches[cur] is not None else None
        return self.locked_dir, s_cur, "steady"


def load_canonical_shapes(conn: sqlite3.Connection, route_codes: List[str]):
    shapes: Dict[str, Dict[str, ShapeProjectionModel]] = {}
    st_dir: Dict[Tuple[int, int], str] = {}

    for r_id, st_id, d in conn.execute(
        """
        SELECT route_id, station_id, MIN(direction)
        FROM canonical_station_master
        GROUP BY route_id, station_id
        HAVING COUNT(DISTINCT direction) = 1
        """
    ).fetchall():
        st_dir[(int(r_id), int(st_id))] = str(d).lower()

    placeholders = ",".join("?" for _ in route_codes)
    rows = conn.execute(
        f"""
        SELECT r.route_code, r.route_id, s.direction, s.point_order, s.lat, s.lon, s.cum_distance_m
        FROM canonical_shape_master s
        JOIN canonical_route_master r ON r.route_id = s.route_id
        WHERE r.route_code IN ({placeholders})
        ORDER BY r.route_code, s.direction, s.point_order
        """,
        route_codes,
    ).fetchall()

    raw_pts: Dict[Tuple[str, str], List[Tuple[int, float, float, float]]] = defaultdict(list)
    route_id_map: Dict[str, int] = {}
    for rc, rid, d, po, lat, lon, cum in rows:
        route_id_map[str(rc)] = int(rid)
        raw_pts[(str(rc), str(d).lower())].append((int(po), float(lat), float(lon), float(cum)))

    for rc in route_codes:
        go_pts = raw_pts.get((rc, "go"), [])
        re_pts = raw_pts.get((rc, "re"), [])
        if len(go_pts) >= 2 and len(re_pts) >= 2:
            shapes[rc] = {
                "go": ShapeProjectionModel.build(go_pts),
                "re": ShapeProjectionModel.build(re_pts),
            }
    return shapes, route_id_map, st_dir


def eval_busmap_historical(conn: sqlite3.Connection, route_codes: List[str], shapes, route_id_map, st_dir):
    print("\n=== 1. BENCHMARK DUAL-HMM TRÊN DỮ LIỆU THẬT BUSMAP (3 NGÀY 2026-11-16..18) ===")
    total_pings = 0
    unresolved_pings = 0
    resolved_pings = 0
    correct_pings = 0
    gt_switches = 0
    matched_switches = 0
    false_switches = 0
    switch_latencies_sec: List[float] = []
    switch_latencies_pings: List[int] = []
    per_route = {}

    for rc in route_codes:
        rid = route_id_map[rc]
        rows = conn.execute(
            """
            SELECT vehicle_id, device_epoch, direction, lat, lon, current_station_id
            FROM vehicle_unique_pings
            WHERE route_id = ?
              AND date_tag BETWEEN '2026-11-16' AND '2026-11-18'
              AND direction IN (0, 1)
              AND lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
            ORDER BY vehicle_id, device_epoch
            """,
            (rid, HANOI_BBOX["min_lat"], HANOI_BBOX["max_lat"], HANOI_BBOX["min_lon"], HANOI_BBOX["max_lon"]),
        ).fetchall()

        by_vid = defaultdict(list)
        for vid, ep, raw_d, lat, lon, st_id in rows:
            gt = st_dir.get((rid, int(st_id))) if st_id else None
            if gt is None:
                gt = "go" if int(raw_d) == 0 else "re"
            by_vid[int(vid)].append((float(ep), float(lat), float(lon), gt))

        r_tot = r_unres = r_res = r_ok = 0
        for vid, pts in by_vid.items():
            tracker = DualHMMDirectionTracker(shapes[rc]["go"], shapes[rc]["re"])
            prev_gt = None
            prev_ep = None
            pending_gt_switch: Optional[Tuple[str, float, int]] = None
            pred_history: List[Tuple[float, Optional[str], str]] = []

            for idx_p, (ep, lat, lon, gt) in enumerate(pts):
                if prev_ep is not None and ep - prev_ep > STALE_DELTA_T_MAX_SEC:
                    pending_gt_switch = None
                elif prev_gt is not None and gt != prev_gt:
                    gt_switches += 1
                    pending_gt_switch = (gt, ep, idx_p)
                prev_gt = gt
                prev_ep = ep

                pred_dir, _, status = tracker.update(ep, lat, lon)
                pred_history.append((ep, pred_dir, gt))

                r_tot += 1
                if pred_dir is None:
                    r_unres += 1
                else:
                    r_res += 1
                    if pred_dir == gt:
                        r_ok += 1

                if status == "switched":
                    if pending_gt_switch is not None and pred_dir == pending_gt_switch[0]:
                        lat_sec = ep - pending_gt_switch[1]
                        if 0.0 <= lat_sec <= 600.0:
                            matched_switches += 1
                            switch_latencies_sec.append(lat_sec)
                            switch_latencies_pings.append(idx_p - pending_gt_switch[2])
                            pending_gt_switch = None
                        else:
                            false_switches += 1
                    else:
                        # Đôi khi Dual-HMM phát hiện đảo chiều sớm hơn API 1-2 ping
                        false_switches += 1

        total_pings += r_tot
        unresolved_pings += r_unres
        resolved_pings += r_res
        correct_pings += r_ok
        acc = (r_ok / r_res * 100.0) if r_res else 0.0
        cov = (r_res / r_tot * 100.0) if r_tot else 0.0
        per_route[rc] = (r_tot, cov, acc)
        print(f"  Tuyến {rc:<4}: pings={r_tot:>6,} | resolved={cov:5.1f}% | accuracy_on_resolved={acc:5.2f}%")

    overall_cov = (resolved_pings / total_pings * 100.0) if total_pings else 0.0
    overall_acc = (correct_pings / resolved_pings * 100.0) if resolved_pings else 0.0
    avg_lat_s = sum(switch_latencies_sec) / len(switch_latencies_sec) if switch_latencies_sec else 0.0
    avg_lat_p = sum(switch_latencies_pings) / len(switch_latencies_pings) if switch_latencies_pings else 0.0
    print(
        f"  TỔNG 5 TUYẾN BUSMAP: total={total_pings:,} | resolved={resolved_pings:,} ({overall_cov:.2f}%) | "
        f"unresolved={unresolved_pings:,} | accuracy={overall_acc:.2f}%"
    )
    print(
        f"  ĐẢO CHIỀU (GT switches={gt_switches}): khớp GT sau switch={matched_switches} "
        f"(trễ TB {avg_lat_s:.1f}s / {avg_lat_p:.1f} pings) | switch không khớp tức thời GT={false_switches}"
    )


def eval_live_captures(shapes):
    print("\n=== 2. BENCHMARK DUAL-HMM TRÊN DỮ LIỆU LIVE SWEEP TUYẾN 32 (TIMBUS & BUSMAP 20s) ===")
    sh_go = shapes["32"]["go"]
    sh_re = shapes["32"]["re"]

    # A. TimBus captures
    tb_files = sorted(glob.glob(str(ROOT / "experiments/timbus/data/raw_timbus_captures/*.json")))
    tb_by_plate: Dict[str, List[Tuple[float, float, float, str]]] = defaultdict(list)
    for f in tb_files:
        d = json.load(open(f, encoding="utf-8"))
        for plate, rec in d.get("unique_buses", {}).items():
            raw_d = str(rec.get("direction_raw", ""))
            gt = "go" if raw_d == "Đi" else ("re" if raw_d == "Về" else "")
            if not gt:
                continue
            tb_by_plate[plate].append((float(rec["fetch_timestamp"]), float(rec["lat"]), float(rec["lon"]), gt))

    tb_tot = tb_res = tb_ok = tb_switches = 0
    for plate, pts in tb_by_plate.items():
        pts.sort(key=lambda x: x[0])
        tr = DualHMMDirectionTracker(sh_go, sh_re)
        for ep, lat, lon, gt in pts:
            pred, _, st = tr.update(ep, lat, lon)
            if st == "switched":
                tb_switches += 1
            tb_tot += 1
            if pred is not None:
                tb_res += 1
                if pred == gt:
                    tb_ok += 1

    print(
        f"  TimBus Tuyến 32 ({len(tb_files)} sweeps, {len(tb_by_plate)} xe): "
        f"obs={tb_tot}, resolved={tb_res} ({tb_res/tb_tot*100:.1f}%), "
        f"agree_TimBus={tb_ok}/{tb_res} ({(tb_ok/tb_res*100 if tb_res else 0):.2f}%), switches={tb_switches}"
    )

    # B. BusMap captures
    bm_files = sorted(glob.glob(str(ROOT / "experiments/timbus/data/raw_busmap_captures/*.json")))
    bm_by_plate: Dict[str, Dict[float, Tuple[float, float, str]]] = defaultdict(dict)
    for f in bm_files:
        d = json.load(open(f, encoding="utf-8"))
        for plate, rec in d.items():
            ut = rec.get("update_time")
            api_d = str(rec.get("direction_api", ""))
            if not ut or api_d not in ("go", "re"):
                continue
            dt_obj = datetime.fromisoformat(ut)
            if dt_obj.tzinfo is None:
                dt_obj = dt_obj.replace(tzinfo=TZ_HANOI)
            ep = dt_obj.timestamp()
            bm_by_plate[plate][ep] = (float(rec["lat"]), float(rec["lon"]), api_d)

    bm_tot = bm_res = bm_ok = bm_switches = 0
    disagreements = []
    for plate, ep_map in bm_by_plate.items():
        tr = DualHMMDirectionTracker(sh_go, sh_re)
        for ep in sorted(ep_map):
            lat, lon, gt = ep_map[ep]
            pred, _, st = tr.update(ep, lat, lon)
            if st == "switched":
                bm_switches += 1
            bm_tot += 1
            if pred is not None:
                bm_res += 1
                if pred == gt:
                    bm_ok += 1
                else:
                    disagreements.append((plate, ep, pred, gt))

    print(
        f"  BusMap Tuyến 32 ({len(bm_files)} sweeps, {len(bm_by_plate)} xe): "
        f"unique_obs={bm_tot}, resolved={bm_res} ({bm_res/bm_tot*100:.1f}%), "
        f"agree_BusMap={bm_ok}/{bm_res} ({(bm_ok/bm_res*100 if bm_res else 0):.2f}%), switches={bm_switches}"
    )
    if disagreements:
        by_p = Counter(x[0] for x in disagreements)
        print(f"  Bất đồng BusMap theo biển số: {dict(by_p)}")


def main():
    routes = ["01", "02", "27", "32", "E03"]
    db_path = ROOT / DEFAULT_DB_PATH
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        shapes, route_id_map, st_dir = load_canonical_shapes(conn, routes)
        eval_busmap_historical(conn, routes, shapes, route_id_map, st_dir)
    eval_live_captures(shapes)


if __name__ == "__main__":
    main()
