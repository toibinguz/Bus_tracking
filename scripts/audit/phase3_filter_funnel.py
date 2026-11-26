"""
Giai đoạn 3 — Đo Filter Funnel & Ablation Probe trên Dữ liệu Replay Thật (Read-Only).

Replay 1 ngày đầy đủ (`dt=2026-11-18`) trên 5 tuyến đại diện (`01`, `02`, `27`, `32`, `E03`)
từ Silver Parquet qua toàn bộ các cổng lọc & chính sách Serving:
  - CausalFeatures (observe + features)
  - RouteProjectionTracker (RouteHMM horizon=120s)
  - eta_policy.project_filter_extrapolate
  - ModelRuntime / ResidualETA (raw_eta vs clamp max(5.0, raw_eta))
  - eta_policy.compute_station_eta (LINEX raw_buffer vs cap 180.0s, delay, traffic_status)
  - compute_proximity_capped_etas

Xuất evidence ra:
  - docs/evidence/codebase_audit_20261126/03_filter_funnel.json
  - docs/evidence/codebase_audit_20261126/03_filter_funnel.md
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.system_config import (  # noqa: E402
    BUFFER_ALPHA_SIGMA,
    BUFFER_BETA_TELEMETRY,
    BUFFER_GAMMA_HORIZON,
    HEADING_COS_SIMILARITY_MIN,
    HEADING_MIN_SPEED_KMPH,
    MAX_CORRIDOR_CROSS_TRACK_M,
    MAX_SAFE_BUFFER_CEILING_SEC,
    MAX_TELEMETRY_STALE_SEC,
    TELEMETRY_HEARTBEAT_SEC,
    TZ_HANOI,
    BASELINE_MAX_HOUR_SLOT,
    BASELINE_MIN_HOUR_SLOT,
)
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import (  # noqa: E402
    CausalFeatures,
    MAX_POSITION_AGE,
    Observation,
)
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.causal_eta_training import (  # noqa: E402
    BASE as BASE_COL,
    feature_frame,
)
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.silver_replay_trainer import (  # noqa: E402
    load_incident_timeline,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess  # noqa: E402
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO  # noqa: E402
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_policy import (  # noqa: E402
    _kappa,
    compute_station_eta,
    project_filter_extrapolate,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.live_feed import parse_ping_epoch  # noqa: E402
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import ModelRuntime  # noqa: E402
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.projection_tracker import (  # noqa: E402
    RouteProjectionTracker,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.serving_service import (  # noqa: E402
    compute_proximity_capped_etas,
)

ROUTES = ("01", "02", "27", "32", "E03")
TARGET_DAY = "2026-11-18"
FORECAST_CADENCE_SEC = 180.0
OUT_DIR = ROOT / "docs" / "evidence" / "codebase_audit_20261126"


def summarize_array(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"count": 0}
    arr = np.asarray(vals, dtype=np.float64)
    return {
        "count": int(arr.size),
        "min": round(float(np.min(arr)), 2),
        "p01": round(float(np.quantile(arr, 0.01)), 2),
        "p05": round(float(np.quantile(arr, 0.05)), 2),
        "p50": round(float(np.quantile(arr, 0.50)), 2),
        "p95": round(float(np.quantile(arr, 0.95)), 2),
        "p99": round(float(np.quantile(arr, 0.99)), 2),
        "max": round(float(np.max(arr)), 2),
    }


def classify_project_rejection(
    v: BusVehicleDTO,
    shape_model: Any,
    s_target: float,
    now_epoch: float,
) -> str:
    t_ping, _ = parse_ping_epoch(v.updated_at, now_epoch)
    age = max(0.0, now_epoch - t_ping)
    if age > MAX_TELEMETRY_STALE_SEC:
        return "stale_gt_300s"
    if v.projection_checked and v.matched_projection is None:
        return "hmm_unmatched"
    s_ping, d_perp, seg_idx = (
        v.matched_projection if v.projection_checked else shape_model.project_point(v.lat, v.lng)
    )
    if d_perp > MAX_CORRIDOR_CROSS_TRACK_M:
        return "cross_track_gt_35m"
    if v.speed_kmh >= HEADING_MIN_SPEED_KMPH and v.deg is not None:
        ux, uy = shape_model.segment_unit_tangent(seg_idx)
        rad = math.radians(v.deg)
        if math.sin(rad) * ux + math.cos(rad) * uy < HEADING_COS_SIMILARITY_MIN:
            return "heading_rejected"
    if s_ping > s_target:
        return "passed_s_target"
    return "other"


def run_funnel() -> dict[str, Any]:
    data = DataAccess()
    runtime = ModelRuntime.load()
    if not runtime.available or runtime._residual_eta is None:
        raise RuntimeError("ModelRuntime causal_eta_v1 not available")
    residual_eta = runtime._residual_eta

    silver_root = ROOT / "data" / "lakehouse" / "silver" / "route_projected_telemetry"
    inc_root = ROOT / "data" / "lakehouse" / "silver" / "fact_route_tomtom_incidents"
    inc_timeline = load_incident_timeline(inc_root, data, route_codes=ROUTES)

    tracker = RouteProjectionTracker(data)
    causal = CausalFeatures(data)

    # Counters
    ping_counts: Counter[str] = Counter()
    hmm_reject_by_route: Counter[str] = Counter()
    gate_counts: Counter[str] = Counter()
    fallback_reasons: Counter[str] = Counter()
    traffic_status_counts: Counter[str] = Counter()

    # Load & merge day rows across 5 routes
    events: list[tuple[float, int, int, int, str, float, float, float, str]] = []
    for rc in ROUTES:
        part_dir = silver_root / f"route_code={rc}" / f"dt={TARGET_DAY}"
        for pq_file in sorted(part_dir.glob("*.parquet")):
            tbl = pq.ParquetFile(pq_file).read(
                columns=["route_id", "direction", "vehicle_id", "plate", "device_epoch", "lat", "lon", "derived_speed_kmh"]
            )
            for row in tbl.to_pylist():
                d_str = row.get("direction")
                if d_str not in ("go", "re"):
                    continue
                d_int = 0 if d_str == "go" else 1
                plate = "".join(c for c in (row.get("plate") or "").upper() if c.isalnum())
                vid = int(row["vehicle_id"])
                veh_key = plate or f"id:{vid}"
                spd = float(row["derived_speed_kmh"]) if row.get("derived_speed_kmh") is not None else 0.0
                events.append(
                    (
                        float(row["device_epoch"]),
                        int(row["route_id"]),
                        d_int,
                        vid,
                        veh_key,
                        float(row["lat"]),
                        float(row["lon"]),
                        max(0.0, spd),
                        rc,
                    )
                )

    events.sort(key=lambda x: (x[0], x[1], x[2], x[4]))
    ping_counts["silver_pings_loaded"] = len(events)

    members: dict[tuple[int, int], dict[str, tuple[float, BusVehicleDTO]]] = defaultdict(dict)
    prev_coords: dict[tuple[int, str], tuple[float, float, float]] = {}
    next_forecast: dict[tuple[int, int], float] = {}
    inc_ptrs: dict[tuple[int, int], int] = defaultdict(int)
    active_incidents: dict[tuple[int, int], list[Any]] = defaultdict(list)

    # Store candidates passing project_filter_extrapolate for batch ML + eta_policy
    pending_candidates: list[dict[str, Any]] = []
    # Also track per-station queue groups for proximity cap audit
    station_queues: list[tuple[int, int, int, list[int]]] = []

    for (now, rid, d_int), grp in groupby(events, key=lambda x: (x[0], x[1], x[2])):
        grp_list = list(grp)
        key = (rid, d_int)
        d_str = "go" if d_int == 0 else "re"
        rc = grp_list[0][8]
        active = {p: val for p, val in members[key].items() if now - val[0] <= MAX_POSITION_AGE}

        for epoch, _r, _d, vid, veh, lat, lng, spd, _rc in grp_list:
            ping_counts["pings_replayed"] += 1
            iso_ts = datetime.fromtimestamp(epoch, tz=TZ_HANOI).isoformat()
            prev = prev_coords.get((rid, veh))
            deg_val = prev[2] if prev else 0.0
            if prev is not None:
                dx = (lng - prev[1]) * 111320.0 * math.cos(math.radians(lat))
                dy = (lat - prev[0]) * 110540.0
                if dx * dx + dy * dy >= 25.0:
                    deg_val = math.degrees(math.atan2(dx, dy)) % 360.0
            prev_coords[(rid, veh)] = (lat, lng, deg_val)

            dto = BusVehicleDTO(
                id=vid,
                plate=veh,
                route_id=rid,
                lat=lat,
                lng=lng,
                deg=deg_val,
                speed_kmh=spd,
                direction=d_int,
                updated_at=iso_ts,
                busmap_updated_at=iso_ts,
                telemetry_source="busmap",
                raw_speed_kmh=spd,
            )
            dto = tracker.project_vehicle(rid, d_int, dto, epoch)
            if dto.matched_projection is None:
                ping_counts["hmm_120s_rejected"] += 1
                hmm_reject_by_route[rc] += 1
            else:
                ping_counts["hmm_120s_accepted"] += 1

            obs = Observation(rid, d_int, veh, "busmap", epoch, epoch, lat, lng, f"{lat:.5f},{lng:.5f},{spd:.1f}", "live")
            c_res = causal.observe(obs)
            if c_res is None:
                ping_counts["causal_observe_rejected"] += 1
            else:
                ping_counts["causal_observe_accepted"] += 1

            active[veh] = (epoch, dto)

        members[key] = active
        causal.observe_snapshot(rid, d_int, now, set(active.keys()), valid=True)

        if now < next_forecast.get(key, 0.0):
            continue
        next_forecast[key] = now + FORECAST_CADENCE_SEC

        # Update active incidents
        route_inc = inc_timeline.get(key, ())
        ptr = inc_ptrs[key]
        cur_active = active_incidents[key]
        while ptr < len(route_inc) and route_inc[ptr].crawled_epoch <= now:
            if route_inc[ptr].expires_epoch >= now:
                cur_active.append(route_inc[ptr])
            ptr += 1
        inc_ptrs[key] = ptr
        if cur_active:
            cur_active = [iv for iv in cur_active if iv.expires_epoch >= now]
            active_incidents[key] = cur_active
        causal.observe_incidents(rid, d_int, cur_active)

        st_res = data.get_route_stations(rid, d_str)
        if not st_res.stations or len(st_res.stations) < 4:
            continue
        shape_model = tracker._get_shape_model(rid, d_str)
        if shape_model is None:
            continue

        station_s = [st.cum_distance_m for st in st_res.stations]
        # Sample ~6 evenly spaced corridor stations [1 .. N-2]
        n_st = len(st_res.stations)
        sample_indices = sorted(
            set(
                max(1, min(n_st - 2, round(1 + k * (n_st - 3) / 5.0)))
                for k in range(6)
            )
        )
        stamp = datetime.fromtimestamp(now, TZ_HANOI)
        day_type = 0 if stamp.weekday() < 5 else (1 if stamp.weekday() == 5 else 2)
        hour_slot = min(BASELINE_MAX_HOUR_SLOT, max(BASELINE_MIN_HOUR_SLOT, stamp.hour))

        for st_idx in sample_indices:
            target_st = st_res.stations[st_idx]
            s_target = float(target_st.cum_distance_m)
            q_indices: list[int] = []

            for veh in sorted(active):
                _ep, v_dto = active[veh]
                gate_counts["station_vehicle_evals"] += 1
                bus_state = project_filter_extrapolate(v_dto, shape_model, s_target, now)
                if bus_state is None:
                    reason = classify_project_rejection(v_dto, shape_model, s_target, now)
                    gate_counts[f"rejected_{reason}"] += 1
                    continue

                gate_counts["accepted_project_filter"] += 1
                if bus_state.d_station == 0.0:
                    gate_counts["at_station_d_zero"] += 1

                feat_res = causal.features(rid, d_int, veh, target_st.station_order, now)
                feat_row = feat_res[0] if feat_res is not None else None
                c_idx = len(pending_candidates)
                q_indices.append(c_idx)
                pending_candidates.append(
                    {
                        "bus_state": bus_state,
                        "rid": rid,
                        "d_int": d_int,
                        "target_st": target_st,
                        "station_s": station_s,
                        "now": now,
                        "day_type": day_type,
                        "hour_slot": hour_slot,
                        "feat_row": feat_row,
                    }
                )

            if len(q_indices) >= 2:
                station_queues.append((rid, d_int, target_st.station_order, q_indices))

    # Batch ML inference (both raw delta + clamped max(5.0, base + delta))
    ml_rows_idx: list[int] = []
    ml_rows: list[dict[str, Any]] = []
    for idx, c in enumerate(pending_candidates):
        fr = c["feat_row"]
        if fr is None:
            fallback_reasons["cold_start_causal"] += 1
            c["ml_p50"] = None
            c["pred_src"] = "baseline_fallback"
        elif fr.get("route_id_idx") is None or int(fr["route_id_idx"]) not in runtime._known_routes:
            fallback_reasons["unknown_route"] += 1
            c["ml_p50"] = None
            c["pred_src"] = "baseline_fallback"
        else:
            fallback_reasons["ok"] += 1
            ml_rows_idx.append(idx)
            ml_rows.append(fr)

    raw_etas: list[float] = []
    raw_deltas: list[float] = []
    clamped_lt_5_count = 0
    clamped_lt_0_count = 0

    if ml_rows:
        frame = feature_frame(ml_rows, residual_eta.domains, columns=residual_eta.features)
        base_vals = frame[BASE_COL].to_numpy()
        deltas = residual_eta._predict_raw(frame)
        raw_arr = base_vals + deltas
        clamped_arr = np.maximum(5.0, raw_arr)

        clamped_lt_5_count = int(np.sum(raw_arr < 5.0))
        clamped_lt_0_count = int(np.sum(raw_arr < 0.0))
        raw_etas = [float(x) for x in raw_arr]
        raw_deltas = [float(x) for x in deltas]

        for pos, c_idx in enumerate(ml_rows_idx):
            pending_candidates[c_idx]["ml_p50"] = float(clamped_arr[pos])
            pending_candidates[c_idx]["pred_src"] = "ml_calibrated"

    # Compute eta_policy outputs + raw_buffer ablation
    raw_buffers: list[float] = []
    capped_buffers: list[float] = []
    buffer_capped_180_count = 0
    delayed_count = 0
    dto_list = []

    for c in pending_candidates:
        bs = c["bus_state"]
        rid = c["rid"]
        d_int = c["d_int"]
        target_st = c["target_st"]
        station_s = c["station_s"]
        now = c["now"]
        day_type = c["day_type"]
        hour_slot = c["hour_slot"]
        ml_p50 = c["ml_p50"]

        dto = compute_station_eta(
            bs,
            rid,
            d_int,
            target_st,
            station_s,
            now,
            data,
            day_type,
            hour_slot,
            ml_p50,
            c["pred_src"],
        )
        dto_list.append(dto)
        traffic_status_counts[dto.traffic_status] += 1
        if dto.safe_window.is_delayed:
            delayed_count += 1

        # Reproduce raw_buffer before MAX_SAFE_BUFFER_CEILING_SEC cap for ablation
        n_st = len(station_s)
        s_now = bs.s_now
        k = 0
        for si in range(n_st - 1):
            if station_s[si] <= s_now < station_s[si + 1]:
                k = si
                break
        if s_now >= station_s[-1]:
            k = n_st - 2
        l_k = max(1.0, station_s[k + 1] - station_s[k])
        rho = min(1.0, max(0.0, max(0.0, station_s[k + 1] - s_now) / l_k))
        _, _, _, _, std_k = data.lookup_baseline_tt(rid, d_int, k, k + 1, day_type, hour_slot, l_k)
        sigma_sq = (rho * std_k) ** 2
        for m in range(k + 1, target_st.station_order):
            seg_len_m = max(1.0, station_s[m + 1] - station_s[m])
            _, _, _, _, std_m = data.lookup_baseline_tt(rid, d_int, m, m + 1, day_type, hour_slot, seg_len_m)
            sigma_sq += std_m ** 2
        raw_buf = _kappa(bs.d_station) * (
            BUFFER_ALPHA_SIGMA * math.sqrt(sigma_sq)
            + BUFFER_BETA_TELEMETRY * TELEMETRY_HEARTBEAT_SEC
            + BUFFER_GAMMA_HORIZON * dto.eta_seconds
        )
        raw_buffers.append(float(raw_buf))
        capped_buffers.append(float(dto.safe_window.buffer_seconds))
        if raw_buf > MAX_SAFE_BUFFER_CEILING_SEC:
            buffer_capped_180_count += 1

    # Proximity cap check across multi-bus station queues
    prox_evaluated = 0
    prox_triggered = 0
    prox_deltas: list[float] = []
    for _rid, _d_int, _st_ord, q_indices in station_queues:
        pairs = [(dto_list[i].distance_to_station_m, dto_list[i].eta_seconds) for i in q_indices]
        overrides = compute_proximity_capped_etas(pairs)
        prox_evaluated += len(q_indices)
        for pos, ov in enumerate(overrides):
            if ov is not None:
                prox_triggered += 1
                prox_deltas.append(dto_list[q_indices[pos]].eta_seconds - ov)

    total_cands = len(pending_candidates)
    return {
        "generated_at": datetime.now(TZ_HANOI).strftime("%Y-%m-%d %H:%M:%S%z"),
        "config": {
            "routes": list(ROUTES),
            "target_day": TARGET_DAY,
            "forecast_cadence_sec": FORECAST_CADENCE_SEC,
        },
        "ping_funnel": dict(ping_counts),
        "hmm_120s_reject_by_route": dict(hmm_reject_by_route),
        "station_gate_funnel": dict(gate_counts),
        "ml_fallback_reasons": dict(fallback_reasons),
        "eta_clamp_ablation": {
            "ml_predictions": len(raw_etas),
            "raw_lt_5s_clamped": clamped_lt_5_count,
            "raw_lt_5s_pct": round(100.0 * clamped_lt_5_count / len(raw_etas), 3) if raw_etas else 0.0,
            "raw_lt_0s": clamped_lt_0_count,
            "raw_eta_stats": summarize_array(raw_etas),
            "raw_delta_stats": summarize_array(raw_deltas),
        },
        "buffer_ceiling_ablation": {
            "total_eta_outputs": total_cands,
            "raw_gt_180s_capped": buffer_capped_180_count,
            "raw_gt_180s_pct": round(100.0 * buffer_capped_180_count / total_cands, 2) if total_cands else 0.0,
            "raw_buffer_stats": summarize_array(raw_buffers),
            "capped_buffer_stats": summarize_array(capped_buffers),
        },
        "policy_outputs": {
            "is_delayed_count": delayed_count,
            "is_delayed_pct": round(100.0 * delayed_count / total_cands, 2) if total_cands else 0.0,
            "traffic_status_counts": dict(traffic_status_counts),
            "proximity_queue_vehicles": prox_evaluated,
            "proximity_cap_triggered": prox_triggered,
            "proximity_cap_pct": round(100.0 * prox_triggered / prox_evaluated, 3) if prox_evaluated else 0.0,
            "proximity_reduction_stats": summarize_array(prox_deltas),
        },
    }


def render_markdown(res: dict[str, Any]) -> str:
    pf = res["ping_funnel"]
    gf = res["station_gate_funnel"]
    fb = res["ml_fallback_reasons"]
    ec = res["eta_clamp_ablation"]
    bc = res["buffer_ceiling_ablation"]
    po = res["policy_outputs"]

    tot_eval = max(1, gf.get("station_vehicle_evals", 0))
    tot_pings = max(1, pf.get("pings_replayed", 0))
    tot_cands = max(1, bc.get("total_eta_outputs", 0))

    lines = [
        "# Giai đoạn 3 — Evidence Filter Funnel & Ablation Probe",
        "",
        f"- **Thời điểm chạy:** `{res['generated_at']}`",
        f"- **Phạm vi dữ liệu:** `dt={res['config']['target_day']}`, 5 tuyến `{res['config']['routes']}`, cadence `{res['config']['forecast_cadence_sec']}s`.",
        "- **Lưu ý phạm vi:** Dữ liệu Silver Parquet đã qua lọc hành lang `<= 35m` ở Batch và không lưu trường `deg` thô, nên cổng `heading` & `cross_track` trên Silver chủ yếu đo hành vi tái chiếu qua `RouteProjectionTracker` (`RouteHMM horizon=120s`) và các cổng Serving phía sau.",
        "",
        "---",
        "",
        "## 1. Funnel Mức Ping (Ingestion & HMM Online)",
        "",
        "| Cổng lọc | Số lượng | Tỷ lệ (%) | Ghi chú |",
        "| :--- | ---: | ---: | :--- |",
        f"| Silver pings đầu vào | `{pf.get('pings_replayed', 0):,}` | `100.00%` | Dữ liệu ngày `{res['config']['target_day']}` |",
        f"| `RouteProjectionTracker` (`HMM 120s`) chấp nhận | `{pf.get('hmm_120s_accepted', 0):,}` | `{100.0 * pf.get('hmm_120s_accepted', 0) / tot_pings:.2f}%` | `matched_projection != None` |",
        f"| `RouteProjectionTracker` (`HMM 120s`) loại | `{pf.get('hmm_120s_rejected', 0):,}` | `{100.0 * pf.get('hmm_120s_rejected', 0) / tot_pings:.2f}%` | Theo tuyến: `{res['hmm_120s_reject_by_route']}` |",
        f"| `CausalFeatures.observe` chấp nhận | `{pf.get('causal_observe_accepted', 0):,}` | `{100.0 * pf.get('causal_observe_accepted', 0) / tot_pings:.2f}%` | `HMM 360s, window=128` |",
        f"| `CausalFeatures.observe` từ chối | `{pf.get('causal_observe_rejected', 0):,}` | `{100.0 * pf.get('causal_observe_rejected', 0) / tot_pings:.2f}%` | `out-of-order` / không khớp hình học |",
        "",
        "---",
        "",
        "## 2. Funnel Mức Cặp (Xe × Trạm) & Trạng thái Dự báo",
        "",
        "| Cổng lọc trạm (`project_filter_extrapolate` + ML) | Số lượng | Tỷ lệ (%) |",
        "| :--- | ---: | ---: |",
        f"| Tổng lượt đánh giá `(xe x trạm)` | `{gf.get('station_vehicle_evals', 0):,}` | `100.00%` |",
        f"| Loại do `passed_s_target` (`s_now > s_target`) | `{gf.get('rejected_passed_s_target', 0):,}` | `{100.0 * gf.get('rejected_passed_s_target', 0) / tot_eval:.2f}%` |",
        f"| Loại do `hmm_unmatched` | `{gf.get('rejected_hmm_unmatched', 0):,}` | `{100.0 * gf.get('rejected_hmm_unmatched', 0) / tot_eval:.2f}%` |",
        f"| Loại do `cross_track > 35m` | `{gf.get('rejected_cross_track_gt_35m', 0):,}` | `{100.0 * gf.get('rejected_cross_track_gt_35m', 0) / tot_eval:.2f}%` |",
        f"| Loại do `heading_rejected` (`deg` nội suy) | `{gf.get('rejected_heading_rejected', 0):,}` | `{100.0 * gf.get('rejected_heading_rejected', 0) / tot_eval:.2f}%` |",
        f"| Loại do `stale > 300s` | `{gf.get('rejected_stale_gt_300s', 0):,}` | `{100.0 * gf.get('rejected_stale_gt_300s', 0) / tot_eval:.2f}%` |",
        f"| Chấp nhận vào `compute_station_eta` | `{gf.get('accepted_project_filter', 0):,}` | `{100.0 * gf.get('accepted_project_filter', 0) / tot_eval:.2f}%` |",
        f"| Trong đó trường hợp biên `d_station == 0.0` | `{gf.get('at_station_d_zero', 0):,}` | `{100.0 * gf.get('at_station_d_zero', 0) / tot_cands:.2f}%` |",
        "",
        "**Phân bố `fallback_reason` trên các lượt được chấp nhận:**",
        "",
        "| Lý do | Số lượt | Tỷ lệ (%) |",
        "| :--- | ---: | ---: |",
    ]
    for k, v in sorted(fb.items(), key=lambda x: -x[1]):
        lines.append(f"| `{k}` | `{v:,}` | `{100.0 * v / tot_cands:.2f}%` |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Ablation Probe — Kiểm tra Lớp Kẹp / Trần Phòng thủ",
            "",
            f"- **ETA clamp `max(5.0, baseline_p50 + delta)`:** Trên `{ec['ml_predictions']:,}` lượt dự báo ML, có **`{ec['raw_lt_5s_clamped']:,}` (`{ec['raw_lt_5s_pct']}%`)** lượt có `raw_eta < 5.0s` (trong đó `< 0.0s`: `{ec['raw_lt_0s']:,}`). Phân bố `raw_eta`: `{ec['raw_eta_stats']}`.",
            f"- **LINEX buffer ceiling `180.0s`:** Trên `{tot_cands:,}` lượt xuất ETA, có **`{bc['raw_gt_180s_capped']:,}` (`{bc['raw_gt_180s_pct']}%`)** lượt có `raw_buffer > 180.0s` bị chạm trần. Phân bố `raw_buffer`: `{bc['raw_buffer_stats']}`.",
            f"- **Proximity Cap (`80m / 120m / 2.5 m/s / 15s`):** Kích hoạt trên **`{po['proximity_cap_triggered']:,} / {po['proximity_queue_vehicles']:,}` (`{po['proximity_cap_pct']}%`)** lượt xe trong hàng chờ nhiều xe; mức giảm ETA: `{po['proximity_reduction_stats']}`.",
            f"- **Phân bố `traffic_status`:** `{po['traffic_status_counts']}` | Tỷ lệ `is_delayed == True`: **`{po['is_delayed_pct']}%`** (`{po['is_delayed_count']:,}` lượt).",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res = run_funnel()
    json_path = OUT_DIR / "03_filter_funnel.json"
    md_path = OUT_DIR / "03_filter_funnel.md"
    json_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(res), encoding="utf-8")
    print(f"Wrote {json_path} and {md_path}")
    print("Summary:", json.dumps({
        "ping_funnel": res["ping_funnel"],
        "ml_fallback_reasons": res["ml_fallback_reasons"],
        "eta_clamp_pct": res["eta_clamp_ablation"]["raw_lt_5s_pct"],
        "buffer_cap_pct": res["buffer_ceiling_ablation"]["raw_gt_180s_pct"],
        "proximity_cap_pct": res["policy_outputs"]["proximity_cap_pct"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
