"""Independent experiment: BusMap/TimBus API Flag vs Dual-HMM vs Joint Bidirectional HMM.

Evaluates against an independently cross-checked Offline Retrospective Viterbi Ground Truth
(so API terminal lag does not bias accuracy at route endpoints). Strictly read-only.
"""

from __future__ import annotations

import glob
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.system_config import (
    DEFAULT_DB_PATH,
    FRENET_MAX_SPEED_MPS,
    HANOI_BBOX,
    MAX_CORRIDOR_CROSS_TRACK_M,
    MAX_GPS_BACKWARD_JITTER_M,
    STALE_DELTA_T_MAX_SEC,
    TERMINAL_RESET_ZONE_M,
    TZ_HANOI,
)
from experiments.hmm_direction_eval.eval_dual_hmm_direction import (
    DualHMMDirectionTracker,
    load_canonical_shapes,
)
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.route_matcher import (
    Match,
    RouteHMM,
    ShapeProjectionModel,
)

TERMINAL_LAYOVER_GAP_SEC = 1800.0


def _collect_dir_candidates(
    shape: ShapeProjectionModel,
    epoch: float,
    lat: float,
    lng: float,
    obs_idx: int,
    max_candidates: int = 6,
) -> List[Match]:
    """Lọc ứng viên trên 1 chiều dùng chính BBox của RouteHMM."""
    hmm = RouteHMM(shape, max_candidates=max_candidates)
    return hmm.candidates(epoch, lat, lng, obs_idx)


def build_offline_retrospective_gt(
    pts: List[Tuple[float, float, float, int, Optional[int]]],
    shape_go: ShapeProjectionModel,
    shape_re: ShapeProjectionModel,
) -> List[Optional[Tuple[str, float, float]]]:
    """Viterbi toàn cục (nhìn cả quá khứ & tương lai) để xác định (gt_dir, gt_s, gt_p) độc lập với cờ API."""
    n = len(pts)
    gt: List[Optional[Tuple[str, float, float]]] = [None] * n
    if n == 0:
        return gt

    hmms = {"go": RouteHMM(shape_go, max_candidates=6), "re": RouteHMM(shape_re, max_candidates=6)}
    lengths = {"go": max(1.0, shape_go._total_len), "re": max(1.0, shape_re._total_len)}

    # Tiền tính ứng viên cho từng ping
    all_cands: List[List[Tuple[str, Match, float]]] = []
    for i, (ep, lat, lng, _, _) in enumerate(pts):
        row = []
        for d in ("go", "re"):
            for m in hmms[d].candidates(ep, lat, lng, i):
                row.append((d, m, m.s / lengths[d]))
        all_cands.append(row)

    # Tách đoạn theo các khoảng mất tín hiệu > 1800s (hoặc chuỗi rỗng)
    valid_indices = [i for i, c in enumerate(all_cands) if c]
    if not valid_indices:
        return gt

    segments: List[List[int]] = [[valid_indices[0]]]
    for idx in valid_indices[1:]:
        prev_idx = segments[-1][-1]
        if pts[idx][0] - pts[prev_idx][0] > TERMINAL_LAYOVER_GAP_SEC:
            segments.append([idx])
        else:
            segments[-1].append(idx)

    sigma = 15.0
    for seg in segments:
        m_len = len(seg)
        dp_scores: List[np.ndarray] = []
        back_ptrs: List[np.ndarray] = []

        # Bước khởi tạo với ưu tiên nhẹ theo đầu xuất phát nếu ở vùng bến
        i0 = seg[0]
        c0 = all_cands[i0]
        sc0 = np.array(
            [
                -0.5 * (m.cross_track / sigma) ** 2 + (0.6 if p <= 0.1 else (-0.6 if p >= 0.9 else 0.0))
                for _, m, p in c0
            ],
            dtype=np.float64,
        )
        dp_scores.append(sc0)
        back_ptrs.append(np.full(len(c0), -1, dtype=np.int32))

        for k in range(1, m_len):
            i_prev = seg[k - 1]
            i_cur = seg[k]
            ep_p, lat_p, lng_p, _, _ = pts[i_prev]
            ep_c, lat_c, lng_c, _, _ = pts[i_cur]
            dt = max(1e-3, ep_c - ep_p)
            move = math.hypot((lng_c - lng_p) * shape_go.kx, (lat_c - lat_p) * shape_go.ky)

            c_prev = all_cands[i_prev]
            c_cur = all_cands[i_cur]
            prev_sc = dp_scores[-1]
            cur_sc = np.full(len(c_cur), -np.inf, dtype=np.float64)
            cur_bp = np.full(len(c_cur), -1, dtype=np.int32)

            for j, (db, mb, pb) in enumerate(c_cur):
                em = 0.0 if (lat_c == lat_p and lng_c == lng_p) else -0.5 * (mb.cross_track / sigma) ** 2
                if dt <= 30.0 and move >= sigma:
                    mx = (lng_c - lng_p) * shape_go.kx
                    my = (lat_c - lat_p) * shape_go.ky
                    ux, uy = hmms[db].shape.segment_unit_tangent(mb.segment)
                    em -= 2.0 * (1.0 - (mx * ux + my * uy) / move)

                best_val = -np.inf
                best_i = -1
                for i_a, (da, ma, pa) in enumerate(c_prev):
                    if not math.isfinite(prev_sc[i_a]):
                        continue
                    if da == db:
                        ds = mb.s - ma.s
                        if ds < -MAX_GPS_BACKWARD_JITTER_M:
                            continue
                        dist = max(0.0, ds)
                        if dist > dt * FRENET_MAX_SPEED_MPS + 3.0 * sigma:
                            continue
                        pen = max(0.0, -ds) / sigma
                        tr = -abs(dist - move) / sigma - pen
                    else:
                        # Đảo chiều ở vùng bến
                        a_end = pa >= 0.85 or ma.s >= lengths[da] - 1000.0
                        b_start = pb <= 0.15 or mb.s <= 1000.0
                        if not (a_end and b_start):
                            continue
                        dist = max(0.0, lengths[da] - ma.s) + mb.s
                        if dist > dt * FRENET_MAX_SPEED_MPS + 250.0:
                            continue
                        tr = -5.0 - abs(dist - move) / 30.0
                    cand_val = prev_sc[i_a] + tr
                    if cand_val > best_val:
                        best_val = cand_val
                        best_i = i_a

                if best_i == -1:
                    # Fallback khẩn cấp nếu xe nhảy cóc/quay đầu bất thường để không đứt chuỗi DP
                    best_i = int(np.argmax(prev_sc))
                    cur_sc[j] = prev_sc[best_i] - 35.0 + em
                else:
                    cur_sc[j] = best_val + em
                cur_bp[j] = best_i

            cur_sc -= np.max(cur_sc)
            dp_scores.append(cur_sc)
            back_ptrs.append(cur_bp)

        # Backtrack đường tối ưu toàn cục
        cur_state = int(np.argmax(dp_scores[-1]))
        for k in range(m_len - 1, -1, -1):
            d_k, m_k, p_k = all_cands[seg[k]][cur_state]
            gt[seg[k]] = (d_k, m_k.s, p_k)
            cur_state = int(back_ptrs[k][cur_state])

    return gt


class JointBidirectionalHMM:
    """Online Causal Joint HMM ghép nối topo 2 chiều go <-> re qua vùng 2 đầu bến & tỷ lệ lý trình p."""

    def __init__(
        self,
        shape_go: ShapeProjectionModel,
        shape_re: ShapeProjectionModel,
        sigma: float = 15.0,
        max_per_dir: int = 6,
        window: int = 32,
        horizon: float = 300.0,
        backward_window_sec: float = 60.0,
        backward_switch_margin: float = 2.0,
    ):
        self.shapes = {"go": shape_go, "re": shape_re}
        self.lengths = {"go": max(1.0, shape_go._total_len), "re": max(1.0, shape_re._total_len)}
        self.probes = {"go": RouteHMM(shape_go, max_candidates=max_per_dir), "re": RouteHMM(shape_re, max_candidates=max_per_dir)}
        self.sigma = sigma
        self.max_per_dir = max_per_dir
        self.window = window
        self.horizon = horizon
        self.backward_window_sec = backward_window_sec
        self.backward_switch_margin = backward_switch_margin

        # Mỗi state trong beam: (dir_str, Match, progress_p)
        self.states: List[Tuple[str, Match, float]] = []
        self.scores = np.array([], dtype=np.float64)
        self.paths: List[List[Tuple[str, Match, float]]] = []
        self.best_path: List[Tuple[str, Match, float]] = []
        self.last: Optional[Tuple[float, float, float]] = None
        self.consec_dead = 0
        self._obs_idx = 0
        self.post_gap_dir: Optional[str] = None
        self.post_gap_start_s: Dict[str, Optional[float]] = {"go": None, "re": None}
        self.post_gap_consec: Dict[str, int] = {"go": 0, "re": 0}

    def _collect_candidates(self, epoch: float, lat: float, lng: float, idx: int) -> List[Tuple[str, Match, float]]:
        out: List[Tuple[str, Match, float]] = []
        for d in ("go", "re"):
            for m in self.probes[d].candidates(epoch, lat, lng, idx):
                out.append((d, m, m.s / self.lengths[d]))
        return out

    def update(self, epoch: float, lat: float, lng: float) -> Tuple[Optional[str], Optional[float], str]:
        if self.last is not None and epoch <= self.last[0]:
            if not self.best_path:
                return None, None, "late_or_duplicate"
            d, m, _ = self.best_path[-1]
            return d, m.s, "late_or_duplicate"

        idx = self._obs_idx
        self._obs_idx += 1
        new_cands = self._collect_candidates(epoch, lat, lng, idx)
        if not new_cands:
            return None, None, "outside_corridor"

        old = self.last
        dt = (epoch - old[0]) if old is not None else 0.0
        move = (
            math.hypot((lng - old[2]) * self.shapes["go"].kx, (lat - old[1]) * self.shapes["go"].ky)
            if old is not None
            else 0.0
        )

        # Emission score
        n_new = len(new_cands)
        emission = np.zeros(n_new, dtype=np.float64)
        if not (old is not None and lat == old[1] and lng == old[2]):
            for i, (d, m, _) in enumerate(new_cands):
                emission[i] = -0.5 * (m.cross_track / self.sigma) ** 2
        if old is not None and dt <= 30.0 and move >= self.sigma:
            mx = (lng - old[2]) * self.shapes["go"].kx
            my = (lat - old[1]) * self.shapes["go"].ky
            for i, (d, m, _) in enumerate(new_cands):
                ux, uy = self.shapes[d].segment_unit_tangent(m.segment)
                emission[i] -= 2.0 * (1.0 - (mx * ux + my * uy) / move)

        in_terminal_layover = (
            old is not None
            and STALE_DELTA_T_MAX_SEC < dt <= TERMINAL_LAYOVER_GAP_SEC
            and self.best_path
            and (
                self.best_path[-1][2] >= 0.90
                or self.best_path[-1][1].s >= self.lengths[self.best_path[-1][0]] - TERMINAL_RESET_ZONE_M
            )
        )

        reason = "matched"
        if not self.states or (dt > STALE_DELTA_T_MAX_SEC and not in_terminal_layover):
            # Khóa chiều sau gap giữa tuyến 300s < dt <= 1800s (0.15 <= p <= 0.85)
            prev_mid_dir = None
            if (
                self.best_path
                and old is not None
                and STALE_DELTA_T_MAX_SEC < dt <= TERMINAL_LAYOVER_GAP_SEC
                and 0.15 <= self.best_path[-1][2] <= 0.85
            ):
                prev_mid_dir = self.best_path[-1][0]
            self.post_gap_dir = prev_mid_dir
            self.post_gap_start_s = {"go": None, "re": None}
            self.post_gap_consec = {"go": 0, "re": 0}
            if prev_mid_dir is not None:
                for cd, cm, _ in new_cands:
                    if self.post_gap_start_s[cd] is None:
                        self.post_gap_start_s[cd] = cm.s
                        self.post_gap_consec[cd] = 1

            # Terminal prior lúc khởi tạo: ưu tiên nhánh đang xuất phát (p <= 0.08) hơn nhánh sắp kết thúc (p >= 0.92)
            priors = np.array(
                [1.5 if p <= 0.08 else (-1.5 if p >= 0.92 else 0.0) for _, _, p in new_cands],
                dtype=np.float64,
            )
            scores = emission + priors
            paths = [[c] for c in new_cands]
            reason = "initialized"
            self.consec_dead = 0
        else:
            scores = np.full(n_new, -np.inf, dtype=np.float64)
            paths: List[Optional[List[Tuple[str, Match, float]]]] = [None] * n_new
            for j, (db, mb, pb) in enumerate(new_cands):
                best_opt = -np.inf
                best_parent = -1
                best_crossed = False

                for i_a, (da, ma, pa) in enumerate(self.states):
                    if da == db:
                        ds = mb.s - ma.s
                        recent_floor = ma.s
                        if self.backward_window_sec > 0 and self.paths[i_a]:
                            rec = [
                                pm.s
                                for pd, pm, _ in self.paths[i_a]
                                if pd == da and (epoch - pm.epoch) <= self.backward_window_sec
                            ]
                            if rec:
                                recent_floor = max(rec)
                        if ds < -MAX_GPS_BACKWARD_JITTER_M or mb.s < recent_floor - MAX_GPS_BACKWARD_JITTER_M:
                            continue
                        dist = max(0.0, ds)
                        if dist > dt * FRENET_MAX_SPEED_MPS + 3.0 * self.sigma:
                            continue
                        pen = max(0.0, -ds) / self.sigma
                        opt = self.scores[i_a] - abs(dist - move) / self.sigma - pen
                        crossed = False
                    else:
                        # Siết vùng nối đầu bến switched_terminal (<= 10%-12% hoặc <= 800m) + chứng cứ rời bến
                        a_finish = (pa >= 0.90) or (ma.s >= self.lengths[da] - TERMINAL_RESET_ZONE_M)
                        b_start = ((pb <= 0.10) or (mb.s <= TERMINAL_RESET_ZONE_M)) and (pb <= 0.12)
                        departed = (mb.s >= 40.0) or (move >= 10.0)
                        if not (a_finish and b_start and departed and dt <= TERMINAL_LAYOVER_GAP_SEC):
                            continue
                        dist = max(0.0, self.lengths[da] - ma.s) + mb.s
                        if dist > dt * FRENET_MAX_SPEED_MPS + 200.0:
                            continue
                        opt = self.scores[i_a] - 4.5 - abs(dist - move) / (2.0 * self.sigma)
                        crossed = True

                    if opt > best_opt:
                        best_opt = opt
                        best_parent = i_a
                        best_crossed = crossed

                if best_parent != -1 and math.isfinite(best_opt):
                    scores[j] = best_opt + emission[j]
                    if best_crossed:
                        paths[j] = [new_cands[j]]
                    else:
                        p_new = (self.paths[best_parent] + [new_cands[j]])[-self.window :]
                        while len(p_new) > 2 and (epoch - p_new[0][1].epoch) > self.horizon:
                            p_new.pop(0)
                        paths[j] = p_new

            if not np.isfinite(scores).any():
                self.consec_dead += 1
                if self.consec_dead >= 3:
                    # Short-turn escape: khóa ưu tiên chiều cũ tới khi chiều mới chứng minh chạy tiến >= 90m
                    prev_mid = self.best_path[-1][0] if self.best_path else None
                    self.post_gap_dir = prev_mid
                    self.post_gap_start_s = {"go": None, "re": None}
                    self.post_gap_consec = {"go": 0, "re": 0}
                    for cd, cm, _ in new_cands:
                        if self.post_gap_start_s[cd] is None:
                            self.post_gap_start_s[cd] = cm.s
                            self.post_gap_consec[cd] = 1
                    self.states = list(new_cands)
                    self.scores = emission - np.max(emission)
                    self.paths = [[c] for c in new_cands]
                    best = int(np.argmax(self.scores))
                    if self.post_gap_dir is not None:
                        keep = [k for k, (sd, _, _) in enumerate(self.states) if sd == self.post_gap_dir]
                        if keep:
                            best = max(keep, key=lambda k: self.scores[k])
                    self.best_path = self.paths[best]
                    self.last = (epoch, lat, lng)
                    self.consec_dead = 0
                    d_out, m_out, _ = self.best_path[-1]
                    return d_out, m_out.s, "short_turn_reset"
                return None, None, "no_feasible_transition"
            self.consec_dead = 0

        valid = [k for k, sc in enumerate(scores) if math.isfinite(sc)]
        self.states = [new_cands[k] for k in valid]
        self.paths = [paths[k] for k in valid]  # type: ignore[misc]
        self.scores = scores[valid]
        self.scores -= np.max(self.scores)
        best = int(np.argmax(self.scores))

        # Kiểm soát khóa chiều sau gap giữa tuyến: đòi hỏi chiều đối chứng minh tiến >= 90m mới cho đổi
        if self.post_gap_dir is not None:
            for d_cand in ("go", "re"):
                idxs = [k for k, (sd, _, _) in enumerate(self.states) if sd == d_cand]
                if idxs:
                    best_dc = max(idxs, key=lambda k: self.scores[k])
                    s_dc = self.states[best_dc][1].s
                    if self.post_gap_start_s[d_cand] is None:
                        self.post_gap_start_s[d_cand] = s_dc
                        self.post_gap_consec[d_cand] = 1
                    elif reason != "initialized":
                        self.post_gap_consec[d_cand] += 1
                else:
                    self.post_gap_consec[d_cand] = 0
                    self.post_gap_start_s[d_cand] = None

            opp = "re" if self.post_gap_dir == "go" else "go"
            opp_s0 = self.post_gap_start_s[opp]
            opp_idxs = [k for k, (sd, _, _) in enumerate(self.states) if sd == opp]
            opp_adv = (
                (self.states[max(opp_idxs, key=lambda k: self.scores[k])][1].s - opp_s0)
                if (opp_idxs and opp_s0 is not None)
                else 0.0
            )
            cur_s0 = self.post_gap_start_s[self.post_gap_dir]
            cur_idxs = [k for k, (sd, _, _) in enumerate(self.states) if sd == self.post_gap_dir]
            cur_adv = (
                (self.states[max(cur_idxs, key=lambda k: self.scores[k])][1].s - cur_s0)
                if (cur_idxs and cur_s0 is not None)
                else 0.0
            )
            if self.post_gap_consec[opp] >= 2 and opp_adv >= 90.0:
                self.post_gap_dir = None
            elif cur_adv >= 90.0:
                self.post_gap_dir = None
            elif cur_idxs:
                best = max(cur_idxs, key=lambda k: self.scores[k])

        # Hysteresis chống nhảy lùi trên cùng chiều khi chênh score nhỏ
        if self.best_path and old is not None and reason != "initialized":
            prev_d, prev_m, _ = self.best_path[-1]
            cur_d, cur_m, _ = self.states[best]
            if cur_d == prev_d and len(self.paths[best]) > 1 and cur_m.s < prev_m.s - MAX_GPS_BACKWARD_JITTER_M:
                fwd = [
                    k
                    for k, (sd, sm, _) in enumerate(self.states)
                    if sd == prev_d and sm.s >= prev_m.s - MAX_GPS_BACKWARD_JITTER_M
                ]
                if fwd:
                    fwd_best = max(fwd, key=lambda k: self.scores[k])
                    if (self.scores[best] - self.scores[fwd_best]) < self.backward_switch_margin:
                        best = fwd_best

        prev_dir = self.best_path[-1][0] if self.best_path else None
        self.best_path = self.paths[best]
        self.last = (epoch, lat, lng)
        d_out, m_out, _ = self.best_path[-1]
        if prev_dir is not None and d_out != prev_dir and reason != "initialized":
            reason = "switched_terminal"
        return d_out, m_out.s, reason


def run_busmap_benchmark(conn: sqlite3.Connection, routes: List[str], shapes, route_id_map, st_dir):
    print("\n=== 1. BENCHMARK ĐỘC LẬP TRÊN BUSMAP 3 NGÀY (2026-11-16..18) VỚI OFFLINE RETROSPECTIVE GT ===")
    gt_station_total = 0
    gt_station_match = 0

    stats = {
        name: {
            "total": 0,
            "resolved": 0,
            "correct": 0,
            "mid_res": 0,
            "mid_ok": 0,
            "term_res": 0,
            "term_ok": 0,
            "false_mid_switches": 0,
            "gt_switches": 0,
            "matched_switches": 0,
            "lat_sec": [],
            "lat_pings": [],
        }
        for name in ("API_Flag", "Dual_HMM", "Joint_HMM")
    }

    for rc in routes:
        rid = route_id_map[rc]
        rows = conn.execute(
            """
            SELECT vehicle_id, device_epoch, lat, lon, direction, current_station_id
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
        for vid, ep, lat, lon, raw_d, st_id in rows:
            by_vid[int(vid)].append((float(ep), float(lat), float(lon), int(raw_d), int(st_id) if st_id else None))

        for vid, pts in by_vid.items():
            gt_seq = build_offline_retrospective_gt(pts, shapes[rc]["go"], shapes[rc]["re"])

            # Kiểm chứng chéo Offline GT với st_dir giữa tuyến (15%..85%)
            for (_, _, _, _, st_id), g in zip(pts, gt_seq):
                if g is None or not st_id:
                    continue
                sd = st_dir.get((rid, st_id))
                if sd and 0.15 <= g[2] <= 0.85:
                    gt_station_total += 1
                    if g[0] == sd:
                        gt_station_match += 1

            dual = DualHMMDirectionTracker(shapes[rc]["go"], shapes[rc]["re"])
            joint = JointBidirectionalHMM(shapes[rc]["go"], shapes[rc]["re"])

            prev_gt_dir = None
            prev_ep = None
            pending_gt = {k: None for k in stats}
            prev_pred = {k: None for k in stats}

            for idx_p, ((ep, lat, lng, raw_d, _), g) in enumerate(zip(pts, gt_seq)):
                api_dir = "go" if raw_d == 0 else "re"
                dual_dir, _, _ = dual.update(ep, lat, lng)
                joint_dir, _, _ = joint.update(ep, lat, lng)

                if g is None:
                    prev_ep = ep
                    continue
                gt_dir, _, gt_p = g
                in_mid = 0.15 <= gt_p <= 0.85

                if prev_ep is not None and (ep - prev_ep) > TERMINAL_LAYOVER_GAP_SEC:
                    prev_gt_dir = None
                    for k in stats:
                        pending_gt[k] = None
                        prev_pred[k] = None

                if prev_gt_dir is not None and gt_dir != prev_gt_dir:
                    for k in stats:
                        stats[k]["gt_switches"] += 1
                        pending_gt[k] = (gt_dir, ep, idx_p)

                preds = {"API_Flag": api_dir, "Dual_HMM": dual_dir, "Joint_HMM": joint_dir}
                for name, p_dir in preds.items():
                    s = stats[name]
                    s["total"] += 1
                    if p_dir is not None:
                        s["resolved"] += 1
                        ok = p_dir == gt_dir
                        if ok:
                            s["correct"] += 1
                        if in_mid:
                            s["mid_res"] += 1
                            if ok:
                                s["mid_ok"] += 1
                        else:
                            s["term_res"] += 1
                            if ok:
                                s["term_ok"] += 1

                        if prev_pred[name] is not None and p_dir != prev_pred[name]:
                            pg = pending_gt[name]
                            if pg is not None and p_dir == pg[0] and 0.0 <= (ep - pg[1]) <= 900.0:
                                s["matched_switches"] += 1
                                s["lat_sec"].append(ep - pg[1])
                                s["lat_pings"].append(idx_p - pg[2])
                                pending_gt[name] = None
                            elif in_mid:
                                s["false_mid_switches"] += 1
                        prev_pred[name] = p_dir

                prev_gt_dir = gt_dir
                prev_ep = ep

    gt_agree = (gt_station_match / gt_station_total * 100.0) if gt_station_total else 0.0
    print(f"[Kiểm chứng chéo Offline GT vs st_dir giữa tuyến 15%-85%]: {gt_station_match:,}/{gt_station_total:,} ({gt_agree:.3f}%)")
    print("-" * 106)
    print(
        f"{'Phương pháp':<12} | {'Resolved':>9} | {'Acc Toàn':>9} | {'Acc Giữa':>9} | "
        f"{'Acc 2 Đầu':>10} | {'Đảo giả giữa':>12} | {'Khớp đổi chiều / Trễ TB':>24}"
    )
    print("-" * 106)
    for name in ("API_Flag", "Dual_HMM", "Joint_HMM"):
        s = stats[name]
        cov = s["resolved"] / s["total"] * 100.0 if s["total"] else 0.0
        acc_all = s["correct"] / s["resolved"] * 100.0 if s["resolved"] else 0.0
        acc_mid = s["mid_ok"] / s["mid_res"] * 100.0 if s["mid_res"] else 0.0
        acc_term = s["term_ok"] / s["term_res"] * 100.0 if s["term_res"] else 0.0
        avg_s = sum(s["lat_sec"]) / len(s["lat_sec"]) if s["lat_sec"] else 0.0
        avg_p = sum(s["lat_pings"]) / len(s["lat_pings"]) if s["lat_pings"] else 0.0
        print(
            f"{name:<12} | {cov:8.2f}% | {acc_all:8.2f}% | {acc_mid:8.2f}% | "
            f"{acc_term:9.2f}% | {s['false_mid_switches']:>12,} | "
            f"{s['matched_switches']}/{s['gt_switches']} ({avg_s:5.1f}s / {avg_p:4.1f}p)"
        )


def run_live_route32_benchmark(shapes):
    print("\n=== 2. BENCHMARK ĐỘC LẬP LIVE SWEEP 20s TUYẾN 32 (TIMBUS & BUSMAP) ===")
    sh_go = shapes["32"]["go"]
    sh_re = shapes["32"]["re"]

    # BusMap 30 sweeps -> ghép chuỗi thật để chạy Retrospective GT
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
            bm_by_plate[plate][dt_obj.timestamp()] = (float(rec["lat"]), float(rec["lon"]), api_d)

    # TimBus 30 sweeps
    tb_files = sorted(glob.glob(str(ROOT / "experiments/timbus/data/raw_timbus_captures/*.json")))
    tb_by_plate: Dict[str, List[Tuple[float, float, float, str]]] = defaultdict(list)
    for f in tb_files:
        d = json.load(open(f, encoding="utf-8"))
        for plate, rec in d.get("unique_buses", {}).items():
            raw_d = str(rec.get("direction_raw", ""))
            tb_d = "go" if raw_d == "Đi" else ("re" if raw_d == "Về" else "")
            if tb_d:
                tb_by_plate[plate].append((float(rec["fetch_timestamp"]), float(rec["lat"]), float(rec["lon"]), tb_d))

    for src_name, seq_map in [
        (
            "BusMap Live 20s",
            {p: [(ep, lat, lng, 0 if d == "go" else 1, None) for ep, (lat, lng, d) in sorted(m.items())] for p, m in bm_by_plate.items()},
        ),
        (
            "TimBus Live 20s",
            {p: [(ep, lat, lng, 0 if d == "go" else 1, None) for ep, lat, lng, d in sorted(lst, key=lambda x: x[0])] for p, lst in tb_by_plate.items()},
        ),
    ]:
        counts = {m: [0, 0, 0] for m in ("Source_Flag", "Dual_HMM", "Joint_HMM")}  # [total, resolved, ok]
        for plate, pts in seq_map.items():
            gt_seq = build_offline_retrospective_gt(pts, sh_go, sh_re)
            dual = DualHMMDirectionTracker(sh_go, sh_re)
            joint = JointBidirectionalHMM(sh_go, sh_re)
            for (ep, lat, lng, raw_d, _), g in zip(pts, gt_seq):
                src_d = "go" if raw_d == 0 else "re"
                dual_d, _, _ = dual.update(ep, lat, lng)
                joint_d, _, _ = joint.update(ep, lat, lng)
                if g is None:
                    continue
                gt_d = g[0]
                for mname, pd_val in (("Source_Flag", src_d), ("Dual_HMM", dual_d), ("Joint_HMM", joint_d)):
                    counts[mname][0] += 1
                    if pd_val is not None:
                        counts[mname][1] += 1
                        if pd_val == gt_d:
                            counts[mname][2] += 1

        print(f"  [{src_name} — đối chiếu với Offline Retrospective GT]")
        for mname in ("Source_Flag", "Dual_HMM", "Joint_HMM"):
            tot, res, ok = counts[mname]
            cov = res / tot * 100.0 if tot else 0.0
            acc = ok / res * 100.0 if res else 0.0
            print(f"    {mname:<12}: resolved={res:>3}/{tot} ({cov:5.1f}%) | accuracy={ok:>3}/{res} ({acc:5.2f}%)")


def main():
    routes = ["01", "02", "27", "32", "E03"]
    db_path = ROOT / DEFAULT_DB_PATH
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        shapes, route_id_map, st_dir = load_canonical_shapes(conn, routes)
        run_busmap_benchmark(conn, routes, shapes, route_id_map, st_dir)
    run_live_route32_benchmark(shapes)


if __name__ == "__main__":
    main()
