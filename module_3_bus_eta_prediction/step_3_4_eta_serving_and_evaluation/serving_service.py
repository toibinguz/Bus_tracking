"""
Step 3.4 — Orchestrator serving (BusMapServingService) + facade cho app.py.
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py

Ghép: data_access + live_feed + frenet + projection_tracker + model_runtime + eta_policy.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import logging
import math
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

from config.system_config import (
    CONGESTION_SPEED_THRESHOLD_KMPH,
    DEFAULT_ETA_POLL_SEC,
    DEFAULT_DB_PATH,
    FREEFLOW_SPEED_THRESHOLD_KMPH,
    GPS_DRIFT_MAX_SPEED_KMPH,
    MACRO_SPEED_EMA_ALPHA,
    MACRO_SPEED_HISTORY_RETENTION_SEC,
    MACRO_SPEED_MAX_DT_SEC,
    MACRO_SPEED_MIN_DT_SEC,
    MACRO_SPEED_MIN_SAMPLE_DT_SEC,
    MAX_CORRIDOR_CROSS_TRACK_M,
    TERMINAL_STATIONARY_TOL_M,
    TIMBUS_ETA_POLL_SEC,
    TIMBUS_HOLD_FRESH_SEC,
    TIMBUS_LIVE_CACHE_TTL_SEC,
    TIMBUS_QUERY_TIMEOUT_SEC,
    TOMTOM_LIVE_TTL_SEC,
    TOMTOM_MIN_COS_THETA,
    TZ_HANOI,
)
from experiments.timbus.timbus_tracker import TimBusClient
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.tomtom_incident_projector import (
    compute_linestring_kinematics,
    split_matched_vertices_into_runs,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess, IncidentsProvider
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import (
    ApproachingBusDTO,
    BusVehicleDTO,
    RouteIncidentDTO,
    RouteItemDTO,
    RouteLiveResponse,
    RouteShapeResponse,
    RouteStationsResponse,
    StationEtaResponse,
    normalize_direction,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_policy import (
    compute_station_eta,
    project_filter_extrapolate,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.live_feed import (
    fetch_live_vehicles_for_route,
    now_hanoi_iso,
    parse_ping_epoch,
)
from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import (
    CausalFeatures,
    Observation,
    RouteIncidentInterval,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import ModelRuntime
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.projection_tracker import RouteProjectionTracker

logger = logging.getLogger(__name__)

PROXIMITY_CAP_FULL_M = 80.0
PROXIMITY_CAP_FADE_M = 120.0
PROXIMITY_CAP_SPEED_MPS = 2.5
PROXIMITY_CAP_MARGIN_SEC = 15.0


def compute_proximity_capped_etas(
    distances_and_etas: List[Tuple[float, float]],
    full_m: float = PROXIMITY_CAP_FULL_M,
    fade_m: float = PROXIMITY_CAP_FADE_M,
    speed_mps: float = PROXIMITY_CAP_SPEED_MPS,
    margin_sec: float = PROXIMITY_CAP_MARGIN_SEC,
) -> List[Optional[float]]:
    """
    Chặn trần ETA bất hợp lý khi hai xe kế tiếp cách nhau dưới fade_m (Giai đoạn 1).
    Trả về danh sách giá trị p50 mới (hoặc None nếu giữ nguyên) theo đúng thứ tự đầu vào.
    """
    n = len(distances_and_etas)
    if n < 2:
        return [None] * n
    order = sorted(range(n), key=lambda idx: distances_and_etas[idx][0])
    effective = [distances_and_etas[idx][1] for idx in range(n)]
    overrides: List[Optional[float]] = [None] * n
    fade_span = max(1e-6, fade_m - full_m)
    for pos in range(1, n):
        ahead_idx = order[pos - 1]
        behind_idx = order[pos]
        gap = distances_and_etas[behind_idx][0] - distances_and_etas[ahead_idx][0]
        if not (0.0 <= gap < fade_m):
            continue
        raw_cap = effective[ahead_idx] + gap / speed_mps + margin_sec
        if effective[behind_idx] <= raw_cap:
            continue
        alpha = 1.0 if gap <= full_m else (fade_m - gap) / fade_span
        capped = raw_cap + (1.0 - alpha) * (effective[behind_idx] - raw_cap)
        effective[behind_idx] = capped
        overrides[behind_idx] = capped
    return overrides

PASSED_STATION_TTL_SEC = 180.0
PASSED_NEW_TRIP_RESET_M = 150.0
_DWELL_TRIM_MIN_SEC = 30.0
_DWELL_MOVE_OUT_M = 25.0


class MacroSpeedTracker:
    """Bộ ước lượng vận tốc vĩ mô v ~ delta_s / delta_t với delta_t > 120s, chống nhảy vi sai cung ngắn."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (route_id, dir_int, plate_norm) -> [(t_sample, s_bus), ...]
        self._history: Dict[Tuple[int, int, str], List[Tuple[float, float]]] = {}
        self._ema: Dict[Tuple[int, int, str], float] = {}
        self._last_win_dt: Dict[Tuple[int, int, str], float] = {}
        self._seed: Dict[Tuple[int, int, str], float] = {}

    def reset_vehicle(self,route_id,plate_norm):
        with self._lock:
            for key in list(self._history):
                if key[0]==route_id and key[2]==plate_norm:
                    for state in (self._history,self._ema,self._last_win_dt,self._seed):state.pop(key,None)

    def sweep_stale(self, now_epoch: float, max_idle_sec: float = 3600.0) -> int:
        """Dọn các phương tiện không cập nhật quá max_idle_sec khỏi RAM."""
        cutoff = now_epoch - max_idle_sec
        removed = 0
        with self._lock:
            for key in list(self._history):
                hist = self._history.get(key)
                if not hist or hist[-1][0] < cutoff:
                    for state in (self._history, self._ema, self._last_win_dt, self._seed):
                        state.pop(key, None)
                    removed += 1
        return removed

    def revise_positions(self,route_id,dir_int,plate_norm,positions):
        key=(route_id,dir_int,plate_norm)
        with self._lock:
            history=self._history.get(key,[])
            revised=[(t,positions.get(t,s)) for t,s in history]
            if revised!=history:
                self._history[key]=revised;self._ema.pop(key,None);self._last_win_dt.pop(key,None)

    def _trim_leading_dwell(
        self,
        key: Tuple[int, int, str],
        hist: List[Tuple[float, float]],
        s_bus: float,
        reset_seed: float,
    ) -> None:
        """Cắt bỏ phần đỗ bến/đứng yên ở đầu cửa sổ sau khi xe đã thực sự xuất phát."""
        if len(hist) < 2:
            return
        s0 = hist[0][1]
        first_moved = None
        for idx, (_, s_val) in enumerate(hist):
            if abs(s_val - s0) > TERMINAL_STATIONARY_TOL_M:
                first_moved = idx
                break
        if first_moved is None or first_moved <= 1:
            return
        dwell_end = first_moved - 1
        dwell_dt = hist[dwell_end][0] - hist[0][0]
        if dwell_dt >= _DWELL_TRIM_MIN_SEC and (s_bus - hist[dwell_end][1]) >= _DWELL_MOVE_OUT_M:
            del hist[:dwell_end]
            self._ema.pop(key, None)
            self._last_win_dt.pop(key, None)
            self._seed[key] = reset_seed

    def observe_and_estimate(
        self,
        route_id: int,
        dir_int: int,
        plate_norm: str,
        t_sample: float,
        s_bus: float,
        raw_speed_kmh: float,
        bm_speed_kmh: float,
        route_base_spd_kmh: float,
    ) -> Tuple[float, float]:
        """Ghi nhận (t, s) và trả (smoothed_speed_kmh, window_dt_sec)."""
        key = (route_id, dir_int, plate_norm)
        fallback_seed = bm_speed_kmh if bm_speed_kmh > 0.0 else (
            raw_speed_kmh if raw_speed_kmh > 0.0 else max(5.0, float(route_base_spd_kmh))
        )

        with self._lock:
            hist = self._history.setdefault(key, [])
            if hist:
                last_t, last_s = hist[-1]
                if t_sample < last_t:
                    return round(self._ema.get(key, fallback_seed), 1), round(self._last_win_dt.get(key, 0.0), 1)
                if s_bus < last_s - 50.0 or (t_sample - last_t) > 1800.0:
                    # Xe quay đầu bến / bắt đầu lượt mới hoặc nhảy sang ngày/ca vận hành mới
                    hist.clear()
                    self._ema.pop(key, None)
                    self._last_win_dt.pop(key, None)
                    self._seed[key] = fallback_seed
                    hist.append((t_sample, s_bus))
                elif (t_sample - last_t) >= MACRO_SPEED_MIN_SAMPLE_DT_SEC:
                    hist.append((t_sample, s_bus))
                else:
                    # Cùng một nhịp dữ liệu -> chỉ cập nhật lý trình nếu tiến lên, giữ nguyên cached win_dt
                    hist[-1] = (last_t, max(last_s, s_bus))
                    if key in self._ema and len(hist) > 1:
                        cached_dt = self._last_win_dt.get(key, max(0.0, t_sample - hist[0][0]))
                        return round(self._ema[key], 1), round(cached_dt, 1)
            else:
                self._seed[key] = fallback_seed
                hist.append((t_sample, s_bus))

            reset_seed = raw_speed_kmh if raw_speed_kmh > 0.0 else fallback_seed
            self._trim_leading_dwell(key, hist, s_bus, reset_seed)

            if bm_speed_kmh > 0.0 and (t_sample - hist[0][0]) < 30.0:
                self._seed[key] = bm_speed_kmh

            cutoff = t_sample - MACRO_SPEED_HISTORY_RETENTION_SEC
            while len(hist) > 1 and hist[0][0] < cutoff:
                hist.pop(0)

            seed = self._seed.get(key, fallback_seed)

            # Tìm điểm tham chiếu có delta_t > 120s (ưu tiên gần 120s..240s nhất)
            p_ref: Optional[Tuple[float, float]] = None
            p_fallback_old: Optional[Tuple[float, float]] = None
            for pt in reversed(hist):
                dt = t_sample - pt[0]
                if dt > MACRO_SPEED_MIN_DT_SEC:
                    if dt <= MACRO_SPEED_MAX_DT_SEC:
                        p_ref = pt
                        break
                    p_fallback_old = pt
            if p_ref is None:
                p_ref = p_fallback_old

            if p_ref is not None:
                used_dt = t_sample - p_ref[0]
                v_macro = min(GPS_DRIFT_MAX_SPEED_KMPH, max(0.0, ((s_bus - p_ref[1]) / used_dt) * 3.6))
            else:
                used_dt = max(0.0, t_sample - hist[0][0])
                if used_dt < 15.0:
                    v_macro = seed
                else:
                    v_partial = min(GPS_DRIFT_MAX_SPEED_KMPH, max(0.0, ((s_bus - hist[0][1]) / used_dt) * 3.6))
                    weight = min(1.0, used_dt / MACRO_SPEED_MIN_DT_SEC)
                    v_macro = weight * v_partial + (1.0 - weight) * seed

            prev_ema = self._ema.get(key)
            if prev_ema is None:
                v_smooth = v_macro
            else:
                v_smooth = MACRO_SPEED_EMA_ALPHA * v_macro + (1.0 - MACRO_SPEED_EMA_ALPHA) * prev_ema
            self._ema[key] = v_smooth
            self._last_win_dt[key] = used_dt
            return round(v_smooth, 1), round(used_dt, 1)


class BusMapServingService:
    """Service phục vụ danh mục tuyến, vị trí xe trực tiếp và dự báo ETA trạm (ML + baseline)."""

    def __init__(self, db_path: Optional[str] = None, timbus_db_path: Optional[str] = None, release_pointer: Optional[str] = None):
        if release_pointer:
            from .release_source import load_release_source
            catalog = db_path or Path(__file__).resolve().parents[2] / DEFAULT_DB_PATH
            source = load_release_source(release_pointer, catalog)
            self._da = DataAccess(db_path, timbus_db_path=timbus_db_path, baseline_db_path=source['baseline_database'])
            self._incidents = IncidentsProvider(source['release'])
            # Do not pair a subset baseline with a separately trained category/calibrator mapping.
            self._runtime = ModelRuntime()
            self.source_info = dict(mode='release', artifact_id=source['artifact_id'],
                                    snapshot_id=source['snapshot_id'], baseline_routes=source['baseline_routes'],
                                    model_status='disabled_release_compatibility_unverified')
        else:
            self._da = DataAccess(db_path, timbus_db_path=timbus_db_path)
            self._runtime = ModelRuntime.load()
            if self._runtime.available and not self._runtime.validate_route_mapping(self._da.route_idx_by_code):
                logger.error("Tắt causal_eta_v1 do route_id_idx SQLite lệch với manifest.json")
            self._incidents = IncidentsProvider()
            self.source_info = dict(mode='local', artifact_id=None, snapshot_id=None,
                                    baseline_routes=sorted(self._da.route_idx_by_code),
                                    model_status='candidate_unverified' if self._runtime.available else 'unavailable')
        self._extractor = RouteProjectionTracker(self._da)
        self._causal = CausalFeatures(self._da)
        self._causal_lock = threading.Lock()
        self._causal_locks: Dict[int, threading.Lock] = {}
        self._causal_locks_guard = threading.Lock()
        self.source_info['model'] = self._runtime.identity
        self._shape_models: Dict[Tuple[int, str], Optional[ShapeProjectionModel]] = {}
        # Cache Monotonicity, danh sách xe vượt trạm theo từng trạm & vận tốc vĩ mô cho luồng hybrid TimBus 5s
        self._tb_lock = threading.Lock()
        self._tb_last_valid: Dict[Tuple[int, int, str], Tuple[float, float, BusVehicleDTO]] = {}
        self._last_timbus_status: Dict[Tuple[int, int], Tuple[str, Optional[str]]] = {}
        self._passed_station_plates: Dict[Tuple[int, int, int, str], float] = {}
        self._speed_tracker = MacroSpeedTracker()
        self._projection_generations={}
        self._incident_lock = threading.Lock()
        self._live_incidents_raw: List[dict] = []
        self._live_incidents_fetched_at: Optional[str] = None
        self._live_incidents_epoch: float = 0.0
        self._live_incidents_by_route: Dict[Tuple[int, int], List[RouteIncidentDTO]] = {}

    def _prepare_vehicle(self,route_id,dir_int,vehicle,now_epoch):
        vehicle=self._extractor.project_vehicle(route_id,dir_int,vehicle,now_epoch)
        plate=TimBusClient.normalize_plate(vehicle.plate) or f"id:{vehicle.id}"
        key=(route_id,dir_int,plate)
        reset_payload=None
        with self._tb_lock:
            previous=self._projection_generations.get(key,0)
            if vehicle.projection_generation!=previous:
                self._speed_tracker.reset_vehicle(route_id,plate)
                for cached_key in list(self._tb_last_valid):
                    if cached_key==(route_id,dir_int,plate):self._tb_last_valid.pop(cached_key,None)
                for passed_key in list(self._passed_station_plates):
                    if passed_key[0]==route_id and passed_key[1]==dir_int and passed_key[3]==plate:self._passed_station_plates.pop(passed_key,None)
                reset_payload=(vehicle.id,vehicle.projection_generation,vehicle.projection_status)
            self._projection_generations[key]=vehicle.projection_generation
        if reset_payload is not None:
            from .request_trace import record
            record('projection_reset',route_id=route_id,direction=dir_int,vehicle_id=reset_payload[0],
                   generation=reset_payload[1],reason=reset_payload[2])
        return vehicle

    def _get_causal_lock(self, route_id: int) -> threading.Lock:
        """Khóa theo từng tuyến để tránh nghẽn toàn cục giữa SpeedLayerPoller và live requests."""
        locks = getattr(self, "_causal_locks", None)
        guard = getattr(self, "_causal_locks_guard", None)
        if locks is not None and guard is not None:
            rid = int(route_id)
            with guard:
                lock = locks.get(rid)
                if lock is None:
                    lock = threading.Lock()
                    locks[rid] = lock
                return lock
        return self._causal_lock

    def _observe_causal_snapshot(
        self,
        route_id: int,
        dir_int: int,
        vehicles: List[BusVehicleDTO],
        now_epoch: float,
    ) -> None:
        """Cập nhật CausalFeatures (40 biến) đồng bộ với snapshot xe hiện hành."""
        with self._get_causal_lock(route_id):
            members: List[str] = []
            for v in vehicles:
                plate_key = TimBusClient.normalize_plate(v.plate) or f"id:{v.id}"
                members.append(plate_key)
                t_ping, _ = parse_ping_epoch(v.updated_at, now_epoch)
                t_obs = min(now_epoch, t_ping)
                raw_spd = float(v.raw_speed_kmh if v.raw_speed_kmh is not None else v.speed_kmh)
                sig = f"{v.lat:.5f},{v.lng:.5f},{round(raw_spd, 1)}"
                src = v.telemetry_source if v.telemetry_source in ("busmap", "timbus") else "busmap"
                self._causal.observe(
                    Observation(
                        route_id=route_id,
                        direction=dir_int,
                        vehicle=plate_key,
                        source=src,
                        epoch=t_obs,
                        received=now_epoch,
                        lat=float(v.lat),
                        lng=float(v.lng),
                        signature=sig,
                        context="live",
                    )
                )
            if vehicles:
                self._causal.observe_snapshot(route_id, dir_int, now_epoch, members, valid=True)

    # ---------------------------------------------------------------- catalog
    def get_routes(self) -> List[RouteItemDTO]:
        return self._da.get_routes()

    def resolve_route_id(self, route_ident: Union[str, int]) -> Optional[int]:
        return self._da.resolve_route_id(route_ident)

    def get_route_shape(self, route_ident: Union[str, int], direction: Union[int, str] = 0) -> Optional[RouteShapeResponse]:
        _, dir_str = normalize_direction(direction)
        return self._da.get_route_shape(route_ident, dir_str)

    def get_route_stations(self, route_ident: Union[str, int], direction: Union[int, str] = 0) -> Optional[RouteStationsResponse]:
        _, dir_str = normalize_direction(direction)
        return self._da.get_route_stations(route_ident, dir_str)

    # ------------------------------------------------------------------- live
    def get_live_vehicles(self, route_code: Union[str, int], direction: int = 0) -> RouteLiveResponse:
        route_id = self._da.resolve_route_id(route_code)
        if route_id is None:
            return RouteLiveResponse(
                route_id=0,
                direction=direction if direction in (0, 1) else 0,
                count=0,
                timestamp=now_hanoi_iso(),
                timbus_supported=False,
                poll_interval_sec=DEFAULT_ETA_POLL_SEC,
                vehicles=[],
            )
        dir_int, _ = normalize_direction(direction)
        timbus_ok, anchor_sids = self._da.get_timbus_anchors(route_id, dir_int)
        poll_sec = TIMBUS_ETA_POLL_SEC if timbus_ok else DEFAULT_ETA_POLL_SEC
        resp = fetch_live_vehicles_for_route(route_id=route_id, direction=dir_int)

        if not timbus_ok or not anchor_sids:
            now_ep = datetime.now(TZ_HANOI).timestamp()
            if resp.vehicles:
                self._observe_causal_snapshot(route_id, dir_int, resp.vehicles, now_ep)
            inc_list, inc_at = self.get_live_incidents_for_route(route_id, dir_int, now_ep)
            return resp.model_copy(
                update={
                    "timbus_supported": timbus_ok,
                    "poll_interval_sec": poll_sec,
                    "timbus_status": "unsupported",
                    "incidents": inc_list,
                    "incidents_fetched_at": inc_at,
                }
            )

        now_epoch = datetime.now(TZ_HANOI).timestamp()
        _, merged = self._sync_route_both_directions(
            route_id=route_id,
            primary_dir=dir_int,
            now_epoch=now_epoch,
            station_order=None,
            s_target=None,
            primary_live_resp=resp,
        )
        with self._tb_lock:
            tb_status, tb_error = getattr(self, "_last_timbus_status", {}).get((route_id, dir_int), ("ok", None))
        inc_list, inc_at = self.get_live_incidents_for_route(route_id, dir_int, now_epoch)
        return resp.model_copy(
            update={
                "count": len(merged),
                "timestamp": now_hanoi_iso(),
                "timbus_supported": True,
                "poll_interval_sec": poll_sec,
                "timbus_status": tb_status,
                "timbus_error": tb_error,
                "incidents": inc_list,
                "incidents_fetched_at": inc_at,
                "vehicles": merged,
            }
        )

    def _get_shape_model(self, route_id: int, dir_str: str) -> Optional[ShapeProjectionModel]:
        key = (route_id, dir_str)
        with self._tb_lock:
            if key in self._shape_models:
                return self._shape_models[key]
        points = self._da.get_shape_points(route_id, dir_str)
        model = ShapeProjectionModel.build(points) if len(points) >= 2 else None
        with self._tb_lock:
            return self._shape_models.setdefault(key, model)

    @staticmethod
    def _collect_bm_proj_and_plates(
        raw_vehicles: List[BusVehicleDTO],
        shape_model: ShapeProjectionModel,
    ) -> Tuple[Dict[str, Tuple[BusVehicleDTO, float, float]], List[str]]:
        """Chiếu toàn bộ xe BusMap hiện hành lên tim tuyến và gom đủ biển số chuẩn hóa."""
        bm_proj: Dict[str, Tuple[BusVehicleDTO, float, float]] = {}
        target_plates: List[str] = []
        for v in raw_vehicles:
            p_norm = TimBusClient.normalize_plate(v.plate)
            if not p_norm:
                continue
            s_bm, ct_bm, _ = shape_model.project_point(v.lat, v.lng)
            if p_norm not in bm_proj or s_bm > bm_proj[p_norm][1]:
                bm_proj[p_norm] = (v, s_bm, ct_bm)
            if p_norm not in target_plates:
                target_plates.append(p_norm)
        return bm_proj, target_plates

    def _sync_single_direction(
        self,
        route_id: int,
        dir_int: int,
        now_epoch: float,
        station_order: Optional[int] = None,
        s_target: Optional[float] = None,
        pre_live_resp: Optional[RouteLiveResponse] = None,
    ) -> Tuple[bool, List[BusVehicleDTO]]:
        """Đồng bộ toàn bộ xe đang chạy trên 1 chiều tuyến với TimBus 5s và cập nhật extractor."""
        timbus_ok, anchor_sids = self._da.get_timbus_anchors(route_id, dir_int)
        live_resp = pre_live_resp if pre_live_resp is not None else fetch_live_vehicles_for_route(
            route_id=route_id, direction=dir_int
        )
        # A malformed/stale response must not move one vehicle between both
        # direction trackers during the same sync cycle.
        live_resp=live_resp.model_copy(update={'vehicles':[v for v in live_resp.vehicles if v.direction==dir_int]})
        if not timbus_ok or not anchor_sids or not live_resp.vehicles:
            return timbus_ok, live_resp.vehicles

        dir_str = "go" if dir_int == 0 else "re"
        shape_model = self._get_shape_model(route_id, dir_str)
        if shape_model is None:
            return timbus_ok, live_resp.vehicles

        bm_proj, target_plates = self._collect_bm_proj_and_plates(live_resp.vehicles, shape_model)
        merged = self._sync_and_merge_timbus(
            route_id=route_id,
            dir_int=dir_int,
            dir_str=dir_str,
            anchor_sids=anchor_sids,
            target_plates=target_plates,
            bm_proj=bm_proj,
            raw_vehicles=live_resp.vehicles,
            shape_model=shape_model,
            now_epoch=now_epoch,
            station_order=None,
            s_target=None,
            use_live_cache=True,
        )
        # Fleet describes the whole route, independently of the requested station.
        self._extractor.update_observation(route_id, dir_int, merged, now_epoch)
        self._observe_causal_snapshot(route_id, dir_int, merged, now_epoch)
        from .request_trace import record
        record('route_observation',route_id=route_id,direction=dir_int,query_epoch=now_epoch,
               vehicles=[vehicle.model_dump() for vehicle in merged])
        return timbus_ok, self._filter_station_vehicles(
            route_id, dir_int, merged, shape_model, now_epoch, s_target, station_order
        )

    def _sync_route_both_directions(
        self,
        route_id: int,
        primary_dir: int,
        now_epoch: float,
        station_order: Optional[int] = None,
        s_target: Optional[float] = None,
        primary_live_resp: Optional[RouteLiveResponse] = None,
    ) -> Tuple[bool, List[BusVehicleDTO]]:
        """Mỗi chu kỳ 5s trên tuyến TimBus: query đồng thời toàn bộ xe trên cả 2 chiều (0 và 1)."""
        other_dir = 1 - primary_dir
        other_ok, other_anchors = self._da.get_timbus_anchors(route_id, other_dir)
        if not other_ok or not other_anchors:
            return self._sync_single_direction(
                route_id, primary_dir, now_epoch, station_order, s_target, primary_live_resp
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_primary = pool.submit(
                copy_context().run,
                self._sync_single_direction,
                route_id,
                primary_dir,
                now_epoch,
                station_order,
                s_target,
                primary_live_resp,
            )
            fut_other = pool.submit(
                copy_context().run,
                self._sync_single_direction,
                route_id,
                other_dir,
                now_epoch,
                None,
                None,
                None,
            )
            primary_res = fut_primary.result()
            try:
                fut_other.result()
            except Exception as e:
                logger.warning("Lỗi đồng bộ chiều đối %s dir=%s: %s", route_id, other_dir, e)
            return primary_res

    def _sync_and_merge_timbus(
        self,
        route_id: int,
        dir_int: int,
        dir_str: str,
        anchor_sids: List[int],
        target_plates: List[str],
        bm_proj: Dict[str, Tuple[BusVehicleDTO, float, float]],
        raw_vehicles: List[BusVehicleDTO],
        shape_model: ShapeProjectionModel,
        now_epoch: float,
        s_target: Optional[float],
        use_live_cache: bool,
        station_order: Optional[int] = None,
    ) -> List[BusVehicleDTO]:
        """Hợp nhất TimBus 5s với BusMap 15s + tổng quát hóa vận tốc vĩ mô (> 120s)."""
        if not target_plates:
            return self._apply_macro_speeds(route_id, dir_int, dir_str, bm_proj, raw_vehicles, shape_model, now_epoch)

        tb_valid_by_plate: Dict[str, BusVehicleDTO] = {}
        plates_to_query: List[str] = []

        if use_live_cache:
            with self._tb_lock:
                for p_norm in target_plates:
                    cached = self._tb_last_valid.get((route_id, dir_int, p_norm))
                    if cached is not None and (now_epoch - cached[0]) <= TIMBUS_LIVE_CACHE_TTL_SEC:
                        cached_ts, cached_s, last_dto = cached
                        bm_entry = bm_proj.get(p_norm)
                        if bm_entry is not None:
                            bm_v, s_bm, ct_bm = bm_entry
                            bm_ts_raw, _ = parse_ping_epoch(bm_v.updated_at, 0.0)
                            bm_ts = min(now_epoch, bm_ts_raw)
                            if bm_ts > cached_ts and s_bm > cached_s and ct_bm <= MAX_CORRIDOR_CROSS_TRACK_M:
                                continue
                        tb_valid_by_plate[p_norm] = last_dto
                    else:
                        plates_to_query.append(p_norm)
        else:
            plates_to_query = list(target_plates)

        if plates_to_query:
            timeout_s = max(1, int(math.ceil(TIMBUS_QUERY_TIMEOUT_SEC)))
            try:
                is_default_impl = getattr(TimBusClient.query_central_vehicles, "__func__", None) is getattr(
                    TimBusClient, "_default_query_central_impl", None
                )
                if is_default_impl:
                    tb_map, ok_cnt, err_cnt, last_err = TimBusClient.query_central_vehicles_with_status(
                        station_ids=anchor_sids,
                        plates=plates_to_query,
                        direction=dir_int,
                        timeout=timeout_s,
                    )
                else:
                    tb_map = TimBusClient.query_central_vehicles(
                        station_ids=anchor_sids,
                        plates=plates_to_query,
                        direction=dir_int,
                        timeout=timeout_s,
                    )
                    ok_cnt, err_cnt, last_err = len(tb_map), 0, None
                if err_cnt > 0 and ok_cnt == 0 and not tb_map:
                    tb_status, tb_err = "upstream_error", last_err
                elif err_cnt > 0:
                    tb_status, tb_err = "partial_error", last_err
                else:
                    tb_status, tb_err = "ok", None
            except Exception as e:
                logger.warning("Lỗi truy vấn TimBus route=%s dir=%s: %s", route_id, dir_int, e)
                tb_map = {}
                tb_status, tb_err = "upstream_error", f"{type(e).__name__}: {e}"
            with self._tb_lock:
                if not hasattr(self, "_last_timbus_status"):
                    self._last_timbus_status = {}
                self._last_timbus_status[(route_id, dir_int)] = (tb_status, tb_err)

            for p_norm in plates_to_query:
                bm_entry = bm_proj.get(p_norm)
                if bm_entry is None:
                    continue
                bm_v, s_bm, ct_bm = bm_entry
                bm_ping_raw, _ = parse_ping_epoch(bm_v.updated_at, 0.0)
                bm_ping_epoch = min(now_epoch, bm_ping_raw)
                cache_key = (route_id, dir_int, p_norm)

                tb_rec = tb_map.get(p_norm)
                if tb_rec is not None:
                    s_tb, ct_tb, seg_idx_tb = shape_model.project_point(tb_rec.latitude, tb_rec.longitude)
                    if ct_tb <= MAX_CORRIDOR_CROSS_TRACK_M:
                        tb_ts = float(getattr(tb_rec, "fetch_timestamp", None) or now_epoch)
                        ux, uy = shape_model.segment_unit_tangent(seg_idx_tb)
                        tb_deg = math.degrees(math.atan2(ux, uy)) % 360.0
                        tb_iso = datetime.fromtimestamp(tb_ts, tz=TZ_HANOI).isoformat()
                        tb_dto = bm_v.model_copy(
                            update={
                                "lat": float(tb_rec.latitude),
                                "lng": float(tb_rec.longitude),
                                "deg": tb_deg,
                                "speed_kmh": float(tb_rec.speed_kmh),
                                "raw_speed_kmh": float(tb_rec.speed_kmh),
                                "updated_at": tb_iso,
                                "busmap_updated_at": bm_v.updated_at,
                                "telemetry_source": "timbus",
                            }
                        )
                        tb_dto=self._prepare_vehicle(route_id,dir_int,tb_dto,now_epoch)
                        if tb_dto.matched_projection is None:
                            continue
                        s_tb,ct_tb,seg_idx_tb=tb_dto.matched_projection
                        ux,uy=shape_model.segment_unit_tangent(seg_idx_tb)
                        tb_dto=tb_dto.model_copy(update={'deg':math.degrees(math.atan2(ux,uy))%360.})
                        # Luôn giữ bản ghi TimBus mới nhất trong _tb_last_valid (kể cả khi đã qua trạm để bản đồ live chạy tiếp)
                        with self._tb_lock:
                            cached = self._tb_last_valid.get(cache_key)
                            if cached is not None and cached[0] > tb_ts:
                                tb_ts, s_tb, tb_dto = cached
                            bm_ahead_newer = bm_ping_epoch > tb_ts and s_bm > s_tb and ct_bm <= MAX_CORRIDOR_CROSS_TRACK_M
                            if not bm_ahead_newer:
                                self._tb_last_valid[cache_key] = (tb_ts, s_tb, tb_dto)

                        if not bm_ahead_newer:
                            tb_valid_by_plate[p_norm] = tb_dto
                        continue

                # Tầng 2 (missing_tb) + Monotonicity Guard khi gói BusMap 15s làm mới: không kéo lùi xe vừa có TimBus tươi
                with self._tb_lock:
                    last_cached = self._tb_last_valid.get(cache_key)
                if last_cached is not None:
                    last_ts, last_s_tb, last_dto = last_cached
                    within_limit = (now_epoch - last_ts) <= TIMBUS_HOLD_FRESH_SEC
                    if within_limit and s_bm < last_s_tb:
                        tb_valid_by_plate[p_norm] = last_dto
        else:
            with self._tb_lock:
                if not hasattr(self, "_last_timbus_status"):
                    self._last_timbus_status = {}
                self._last_timbus_status[(route_id, dir_int)] = ("ok", None)

        merged: List[BusVehicleDTO] = []
        for v in raw_vehicles:
            p_norm = TimBusClient.normalize_plate(v.plate)
            if p_norm in tb_valid_by_plate:
                merged.append(tb_valid_by_plate[p_norm])
            else:
                merged.append(v)

        merged = self._apply_macro_speeds(route_id, dir_int, dir_str, bm_proj, merged, shape_model, now_epoch)
        return self._filter_station_vehicles(
            route_id, dir_int, merged, shape_model, now_epoch, s_target, station_order
        )

    def _filter_station_vehicles(
        self, route_id: int, dir_int: int, vehicles: List[BusVehicleDTO],
        shape_model: ShapeProjectionModel, now_epoch: float,
        s_target: Optional[float], station_order: Optional[int],
    ) -> List[BusVehicleDTO]:
        if s_target is None:
            return vehicles
        approaching = []
        for vehicle in vehicles:
            vehicle=self._prepare_vehicle(route_id,dir_int,vehicle,now_epoch)
            if vehicle.matched_projection is None:continue
            s_cur, cross_track, _ = vehicle.matched_projection
            if cross_track > MAX_CORRIDOR_CROSS_TRACK_M:
                continue
            if project_filter_extrapolate(vehicle, shape_model, math.inf, now_epoch) is None:
                continue
            plate = TimBusClient.normalize_plate(vehicle.plate)
            key = (route_id, dir_int, station_order, plate) if station_order is not None else None
            if s_cur > s_target:
                from .request_trace import record
                record('station_filtered',route_id=route_id,direction=dir_int,station_order=station_order,
                       vehicle=vehicle.model_dump(),reason='passed_station',s_bus_m=s_cur,s_target_m=s_target)
                if key is not None:
                    with self._tb_lock:
                        self._passed_station_plates[key] = now_epoch
                continue
            if key is not None and self._is_recently_passed_locked(key, s_cur, s_target, now_epoch):
                from .request_trace import record
                record('station_filtered',route_id=route_id,direction=dir_int,station_order=station_order,
                       vehicle=vehicle.model_dump(),reason='recently_passed_guard',s_bus_m=s_cur,s_target_m=s_target)
                continue
            approaching.append(vehicle)
        return approaching

    def _is_recently_passed_locked(
        self,
        passed_key: Tuple[int, int, int, str],
        s_cur: float,
        s_target: float,
        now_epoch: float,
    ) -> bool:
        """Kiểm tra xe vừa qua trạm trong TTL; tự xóa nếu hết hạn hoặc đã quay đầu lượt mới."""
        with self._tb_lock:
            passed_ts = self._passed_station_plates.get(passed_key)
            if passed_ts is None:
                return False
            if (now_epoch - passed_ts) > PASSED_STATION_TTL_SEC or s_cur < (s_target - PASSED_NEW_TRIP_RESET_M):
                self._passed_station_plates.pop(passed_key, None)
                return False
            return True

    def _apply_macro_speeds(
        self,
        route_id: int,
        dir_int: int,
        dir_str: str,
        bm_proj: Dict[str, Tuple[BusVehicleDTO, float, float]],
        vehicles: List[BusVehicleDTO],
        shape_model: ShapeProjectionModel,
        now_epoch: float,
    ) -> List[BusVehicleDTO]:
        """Tổng quát hóa vận tốc theo delta_s / delta_t (> 120s) để triệt tiêu nhiễu tức thời hộp đen."""
        route_base_spd = self._da.get_route_profile(route_id, dir_str)[0]
        stabilized: List[BusVehicleDTO] = []
        for v in vehicles:
            v=self._prepare_vehicle(route_id,dir_int,v,now_epoch)
            if v.matched_projection is None:continue
            p_norm = TimBusClient.normalize_plate(v.plate)
            if not p_norm:
                stabilized.append(v)
                continue
            s_cur, _, _ = v.matched_projection
            if v.telemetry_source=='timbus':
                # TimBus has no measured heading. Keep its inferred map arrow
                # consistent with the selected branch, including cached DTOs.
                ux,uy=shape_model.segment_unit_tangent(v.matched_projection[2])
                v=v.model_copy(update={'deg':math.degrees(math.atan2(ux,uy))%360.})
            self._speed_tracker.revise_positions(route_id,dir_int,p_norm,self._extractor.projection_history(route_id,dir_int,v.id))
            t_sample, _ = parse_ping_epoch(v.updated_at, now_epoch)
            t_sample=min(now_epoch,t_sample)
            raw_spd = float(v.raw_speed_kmh if v.raw_speed_kmh is not None else v.speed_kmh)
            bm_entry = bm_proj.get(p_norm)
            bm_spd = float(bm_entry[0].speed_kmh) if bm_entry is not None else raw_spd
            smooth_spd, win_sec = self._speed_tracker.observe_and_estimate(
                route_id=route_id,
                dir_int=dir_int,
                plate_norm=p_norm,
                t_sample=t_sample,
                s_bus=s_cur,
                raw_speed_kmh=raw_spd,
                bm_speed_kmh=bm_spd,
                route_base_spd_kmh=route_base_spd,
            )
            stabilized.append(
                v.model_copy(
                    update={
                        "speed_kmh": smooth_spd,
                        "raw_speed_kmh": round(raw_spd, 1),
                        "speed_window_sec": win_sec,
                    }
                )
            )
        return stabilized

    # -------------------------------------------------------------------- ETA
    def get_station_eta(
        self,
        route_ident: Union[str, int],
        direction: Union[int, str] = 0,
        station_order: int = 0,
    ) -> Optional[StationEtaResponse]:
        """1. fetch live; 2. hợp nhất TimBus 5s nếu hỗ trợ; 3. cập nhật extractor; 4. ETA + policy; 5. đóng gói."""
        route_id = self._da.resolve_route_id(route_ident)
        if route_id is None:
            return None

        dir_int, dir_str = normalize_direction(direction)
        stations_resp = self._da.get_route_stations(route_id, dir_str)
        if stations_resp is None or not stations_resp.stations:
            return None

        target_st = next((st for st in stations_resp.stations if st.station_order == station_order), None)
        if target_st is None:
            return None
        s_target = target_st.cum_distance_m
        route_code = self._da.get_route_code(route_id)
        timbus_ok, _ = self._da.get_timbus_anchors(route_id, dir_int)
        poll_sec = TIMBUS_ETA_POLL_SEC if timbus_ok else DEFAULT_ETA_POLL_SEC

        now_hn = datetime.now(TZ_HANOI)
        now_iso = now_hn.isoformat()
        now_epoch = now_hn.timestamp()
        day_type = 0 if now_hn.weekday() < 5 else (1 if now_hn.weekday() == 5 else 2)
        hour_slot = min(21, max(5, now_hn.hour))

        # Ca Biên 1: Trạm Đầu Bến (order 0).
        if station_order == 0:
            return self._response(
                route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
                "THONG_THOANG", [], "Trạm đầu bến. Xe xuất bến theo nốt điều độ.",
                timbus_supported=timbus_ok, poll_interval_sec=poll_sec,
            )

        # Ca Biên 2: Tuyến nằm ngoài phạm vi baseline & mô hình khả dụng.
        if not self._is_route_eta_feasible(route_id, route_code):
            return self._response(
                route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
                "THONG_THOANG", [], "Tuyến nằm ngoài phạm vi dự báo ETA (chưa có dữ liệu baseline hoặc mô hình khả dụng).",
                timbus_supported=timbus_ok, poll_interval_sec=poll_sec,
            )

        live_resp = fetch_live_vehicles_for_route(route_id=route_id, direction=dir_int)
        if live_resp.upstream_status == "upstream_error":
            return self._response(
                route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
                "THONG_THOANG", [],
                f"Lỗi kết nối BusMap upstream: {live_resp.upstream_error or 'Không xác định'}",
                timbus_supported=timbus_ok, poll_interval_sec=poll_sec,
                upstream_status="upstream_error", upstream_error=live_resp.upstream_error,
                timbus_status="unsupported" if not timbus_ok else "ok",
            )
        if live_resp.count == 0:
            return self._response(
                route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
                "THONG_THOANG", [], "Hiện chưa có xe trực tiếp trên tuyến này.",
                timbus_supported=timbus_ok, poll_interval_sec=poll_sec,
                upstream_status=live_resp.upstream_status,
                timbus_status="unsupported" if not timbus_ok else "ok",
            )

        shape_model = self._get_shape_model(route_id, dir_str)
        if shape_model is None:
            return self._response(
                route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
                "THONG_THOANG", [], "Đang đồng bộ hình học tuyến...",
                timbus_supported=timbus_ok, poll_interval_sec=poll_sec,
            )

        if timbus_ok:
            _, vehicles = self._sync_route_both_directions(
                route_id=route_id,
                primary_dir=dir_int,
                now_epoch=now_epoch,
                station_order=station_order,
                s_target=s_target,
                primary_live_resp=live_resp,
            )
        else:
            vehicles = [self._prepare_vehicle(route_id,dir_int,v,now_epoch) for v in live_resp.vehicles]
            vehicles = [v for v in vehicles if v.matched_projection is not None]
            self._extractor.update_observation(route_id, dir_int, vehicles, now_epoch)
            self._observe_causal_snapshot(route_id, dir_int, vehicles, now_epoch)
            from .request_trace import record
            record('route_observation',route_id=route_id,direction=dir_int,query_epoch=now_epoch,
                   vehicles=[vehicle.model_dump() for vehicle in vehicles])
            vehicles = self._filter_station_vehicles(
                route_id, dir_int, vehicles, shape_model, now_epoch, s_target, target_st.station_order
            )

        station_s = [st.cum_distance_m for st in stations_resp.stations]
        station_orders = [st.station_order for st in stations_resp.stations]
        candidates = []
        speeds: List[float] = []

        inc_list, inc_at = self.get_live_incidents_for_route(route_id, dir_int, now_epoch)
        inc_epoch = self._get_live_incidents_epoch()
        if inc_list and inc_epoch > 0.0:
            inc_exp = inc_epoch + float(TOMTOM_LIVE_TTL_SEC)
            inc_intervals = []
            for inc in inc_list:
                if inc.delay_seconds <= 0.0:
                    continue
                span_route = max(0.0, inc.s_max_m - inc.s_min_m)
                if span_route <= 0.0:
                    continue
                eff_inc_span = max(inc.length_meters, span_route, 25.0)
                inc_intervals.append(
                    RouteIncidentInterval(
                        s_min_m=inc.s_min_m,
                        s_max_m=inc.s_max_m,
                        delay_seconds=inc.delay_seconds * (span_route / eff_inc_span),
                        crawled_epoch=inc_epoch,
                        expires_epoch=inc_exp,
                    )
                )
        else:
            inc_intervals = []
        with self._get_causal_lock(route_id):
            self._causal.observe_incidents(route_id, dir_int, inc_intervals)

        for v in vehicles:
            v=self._prepare_vehicle(route_id,dir_int,v,now_epoch)
            bus_state = project_filter_extrapolate(v, shape_model, s_target, now_epoch)
            if bus_state is None:
                from .request_trace import record
                record('eta_filtered', route_id=route_id, direction=dir_int, station_order=station_order,
                       vehicle=v.model_dump(), reason='projection_stale_heading_or_passed')
                continue

            plate_key = TimBusClient.normalize_plate(v.plate) or f"id:{v.id}"
            with self._get_causal_lock(route_id):
                causal_res = self._causal.features(route_id, dir_int, plate_key, target_st.station_order, now_epoch)
            features = causal_res[0] if causal_res is not None else None
            if not self._runtime.available:
                ml_p50, fb_reason = None, "model_unavailable"
            elif self._da.get_route_idx(route_id) is None:
                ml_p50, fb_reason = None, "unknown_route"
            elif features is None:
                ml_p50, fb_reason = None, "cold_start_causal"
            else:
                ml_p50, fb_reason = self._runtime.predict_p50_with_reason(features)
            prediction_source = "ml_calibrated" if ml_p50 is not None else "baseline_fallback"

            dto = compute_station_eta(
                bus_state=bus_state,
                route_id=route_id,
                dir_int=dir_int,
                target_st=target_st,
                station_s=station_s,
                now_epoch=now_epoch,
                data_access=self._da,
                day_type=day_type,
                hour_slot=hour_slot,
                ml_p50=ml_p50,
                prediction_source=prediction_source,
                station_orders=station_orders,
            ).model_copy(update={"fallback_reason": fb_reason})
            candidates.append((v, bus_state, features, prediction_source, fb_reason, dto))
            speeds.append(v.speed_kmh)

        overrides = compute_proximity_capped_etas(
            [(item[5].distance_to_station_m, item[5].eta_seconds) for item in candidates]
        )
        approaching: List[ApproachingBusDTO] = []
        for (v, bus_state, features, prediction_source, fb_reason, dto), capped_p50 in zip(candidates, overrides):
            if capped_p50 is not None:
                dto = compute_station_eta(
                    bus_state=bus_state,
                    route_id=route_id,
                    dir_int=dir_int,
                    target_st=target_st,
                    station_s=station_s,
                    now_epoch=now_epoch,
                    data_access=self._da,
                    day_type=day_type,
                    hour_slot=hour_slot,
                    ml_p50=capped_p50,
                    prediction_source=prediction_source,
                    station_orders=station_orders,
                ).model_copy(update={"fallback_reason": fb_reason})
            dto = dto.model_copy(
                update={
                    "telemetry_source": v.telemetry_source,
                    "busmap_updated_at": v.busmap_updated_at or (v.updated_at if v.telemetry_source == "busmap" else None),
                }
            )
            from .request_trace import record
            record('eta_result', route_id=route_id, direction=dir_int, station_order=station_order,
                   query_epoch=now_epoch, s_bus_m=bus_state.s_now, s_target_m=s_target,
                   vehicle=v.model_dump(), features=features or {}, result=dto.model_dump(), serving=self.source_info)
            approaching.append(dto)

        approaching.sort(key=lambda b: (b.eta_seconds, b.distance_to_station_m))

        if speeds:
            avg_spd = sum(speeds) / len(speeds)
            if avg_spd < CONGESTION_SPEED_THRESHOLD_KMPH:
                traffic_cond = "UN_TAC"
            elif avg_spd < FREEFLOW_SPEED_THRESHOLD_KMPH:
                traffic_cond = "BINH_THUONG"
            else:
                traffic_cond = "THONG_THOANG"
        else:
            traffic_cond = "THONG_THOANG"

        count = len(approaching)
        message = (
            f"Có {count} xe đang di chuyển về trạm."
            if count > 0
            else "Không có xe nào đang tiếp cận trạm này."
        )
        with self._tb_lock:
            tb_status, tb_error = (
                getattr(self, "_last_timbus_status", {}).get((route_id, dir_int), ("ok", None))
                if timbus_ok
                else ("unsupported", None)
            )
        top_fb_reason = approaching[0].fallback_reason if approaching else None
        inc_list, inc_at = self.get_live_incidents_for_route(route_id, dir_int, now_epoch)
        return self._response(
            route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
            traffic_cond, approaching, message,
            timbus_supported=timbus_ok, poll_interval_sec=poll_sec,
            upstream_status=live_resp.upstream_status,
            upstream_error=live_resp.upstream_error,
            timbus_status=tb_status,
            timbus_error=tb_error,
            fallback_reason=top_fb_reason,
            incidents=inc_list,
            incidents_fetched_at=inc_at,
        )

    def ingest_live_incidents(self, payload: Optional[dict], now_epoch: Optional[float] = None) -> int:
        """Nạp snapshot TomTom Incidents mới nhất từ Speed Layer (đồng bộ qua Hugging Face)."""
        if not isinstance(payload, dict) or not isinstance(payload.get("incidents"), list):
            return 0
        raw_list = payload["incidents"]
        fetched_at = payload.get("fetched_at")
        ep = float(now_epoch) if now_epoch is not None else datetime.now(TZ_HANOI).timestamp()
        if fetched_at:
            parsed_ep, _ = parse_ping_epoch(fetched_at, ep)
            ep = parsed_ep
        lock = getattr(self, "_incident_lock", None)
        if lock is None:
            lock = self._incident_lock = threading.Lock()
        with lock:
            self._live_incidents_raw = [item for item in raw_list if isinstance(item, dict)]
            self._live_incidents_fetched_at = str(fetched_at) if fetched_at else None
            self._live_incidents_epoch = ep
            self._live_incidents_gen = getattr(self, "_live_incidents_gen", 0) + 1
            self._live_incidents_by_route = {}
            return len(self._live_incidents_raw)

    @staticmethod
    def _extract_incident_polylines(geometry_type: str, coords: Any) -> List[List[Tuple[float, float]]]:
        """Chuẩn hóa Point / LineString / MultiLineString GeoJSON ([lon, lat]) thành danh sách [(lat, lon)]."""
        if not isinstance(coords, (list, tuple)) or not coords:
            return []

        def _is_num(val: Any) -> bool:
            return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)

        def _to_lat_lon_pts(seq: Any) -> List[Tuple[float, float]]:
            if not isinstance(seq, (list, tuple)):
                return []
            return [
                (float(p[1]), float(p[0]))
                for p in seq
                if isinstance(p, (list, tuple)) and len(p) >= 2 and _is_num(p[0]) and _is_num(p[1])
            ]

        gtype = str(geometry_type or "").lower()
        if _is_num(coords[0]):
            return [[(float(coords[1]), float(coords[0]))]] if len(coords) >= 2 and _is_num(coords[1]) else []
        if gtype == "multilinestring" or (
            isinstance(coords[0], (list, tuple)) and coords[0] and isinstance(coords[0][0], (list, tuple))
        ):
            return [pts for part in coords if (pts := _to_lat_lon_pts(part))]
        pts = _to_lat_lon_pts(coords)
        return [pts] if pts else []

    def get_live_incidents_for_route(
        self, route_id: int, dir_int: int, now_epoch: Optional[float] = None
    ) -> Tuple[List[RouteIncidentDTO], Optional[str]]:
        """Chiếu sự cố TomTom live lên hành lang tuyến/chiều (lọc hướng cos_theta >= 0.5, TTL 45 phút)."""
        lock = getattr(self, "_incident_lock", None)
        if lock is None:
            return [], None
        now_ep = float(now_epoch) if now_epoch is not None else datetime.now(TZ_HANOI).timestamp()
        with lock:
            fetched_at = getattr(self, "_live_incidents_fetched_at", None)
            inc_epoch = getattr(self, "_live_incidents_epoch", 0.0)
            gen = getattr(self, "_live_incidents_gen", 0)
            raw_list = list(getattr(self, "_live_incidents_raw", []))
            if not raw_list or (now_ep - inc_epoch) > float(TOMTOM_LIVE_TTL_SEC):
                return [], None
            cached = self._live_incidents_by_route.get((route_id, dir_int))
            if cached is not None:
                return list(cached), fetched_at

        dir_str = "go" if dir_int == 0 else "re"
        shape_model = self._get_shape_model(route_id, dir_str)
        if shape_model is None:
            return [], fetched_at

        has_batch_proj = hasattr(shape_model, "project_directed_points_batch")
        matched: List[RouteIncidentDTO] = []
        for inc in raw_list:
            polylines = self._extract_incident_polylines(inc.get("geometry_type", ""), inc.get("coordinates"))
            inc_len_m = float(inc.get("length_meters") or 0.0)
            inc_runs: List[Tuple[float, float]] = []
            matched_polylines: List[List[List[float]]] = []
            for pts in polylines:
                if len(pts) == 1:
                    s_val, ct_val, _ = shape_model.project_point(pts[0][0], pts[0][1])
                    if ct_val <= MAX_CORRIDOR_CROSS_TRACK_M:
                        inc_runs.append((s_val, s_val))
                        matched_polylines.append([[round(pts[0][0], 6), round(pts[0][1], 6)]])
                    continue
                if len(pts) < 2:
                    continue
                coords = [(lon, lat) for lat, lon in pts]
                pt_unit_vecs, pt_step_dists = compute_linestring_kinematics(coords)
                if has_batch_proj:
                    matched_vertices = shape_model.project_directed_points_batch(
                        [p[0] for p in pts],
                        [p[1] for p in pts],
                        [v[0] for v in pt_unit_vecs],
                        [v[1] for v in pt_unit_vecs],
                        min_cos_theta=TOMTOM_MIN_COS_THETA,
                        max_d_perp_m=MAX_CORRIDOR_CROSS_TRACK_M,
                    )
                else:
                    matched_vertices = []
                    for idx, (lat, lon) in enumerate(pts):
                        ux, uy = pt_unit_vecs[idx]
                        if ux == 0.0 and uy == 0.0:
                            continue
                        proj = shape_model.project_directed_point(
                            lat, lon, ux, uy, min_cos_theta=TOMTOM_MIN_COS_THETA, max_d_perp_m=MAX_CORRIDOR_CROSS_TRACK_M
                        )
                        if proj is not None:
                            s_val, ct_val, _ = proj
                            matched_vertices.append((idx, s_val, ct_val))
                runs = split_matched_vertices_into_runs(matched_vertices, pt_step_dists, inc_len_m)
                if runs:
                    matched_polylines.append([[round(lat, 6), round(lon, 6)] for lat, lon in pts])
                    for s_min, s_max, _ in runs:
                        inc_runs.append((s_min, s_max))

            if inc_runs:
                for s_min_r, s_max_r in inc_runs:
                    matched.append(
                        RouteIncidentDTO(
                            incident_id=str(inc.get("incident_id") or ""),
                            description=str(inc.get("description") or "Sự cố giao thông"),
                            icon_category=int(inc.get("icon_category") or 0),
                            magnitude_of_delay=int(inc.get("magnitude_of_delay") or 0),
                            delay_seconds=float(inc.get("delay_seconds") or 0.0),
                            length_meters=inc_len_m,
                            s_min_m=round(s_min_r, 1),
                            s_max_m=round(s_max_r, 1),
                            polylines=matched_polylines,
                        )
                    )

        matched.sort(key=lambda item: (-item.delay_seconds, -item.magnitude_of_delay))
        with lock:
            if getattr(self, "_live_incidents_gen", 0) == gen:
                self._live_incidents_by_route[(route_id, dir_int)] = matched
        return list(matched), fetched_at

    # ------------------------------------------------- Speed-Layer Integration
    def get_poller_route_ids(self) -> List[int]:
        """Trả danh sách route_id phục vụ Speed Layer (ưu tiên tuyến baseline)."""
        baseline_codes = set(getattr(self, "source_info", {}).get("baseline_routes") or ())
        routes = self._da.get_routes()
        if baseline_codes:
            matched = [r.route_id for r in routes if r.route_no in baseline_codes]
            if matched:
                return matched
        return [r.route_id for r in routes]

    def get_timbus_anchors(self, route_id: int, dir_int: int) -> Tuple[bool, List[int]]:
        return self._da.get_timbus_anchors(route_id, dir_int)

    def get_shape_model(self, route_id: int, dir_str: str) -> Optional[ShapeProjectionModel]:
        return self._get_shape_model(route_id, dir_str)

    def get_route_endpoint_s(self, route_id: int, dir_str: str) -> Optional[Tuple[float, float]]:
        """Trả (s_start, s_end) của tuyến/chiều để phân loại xe đậu gần bến."""
        stations_resp = self._da.get_route_stations(route_id, dir_str)
        if stations_resp is None or not stations_resp.stations:
            return None
        return (stations_resp.stations[0].cum_distance_m, stations_resp.stations[-1].cum_distance_m)

    def get_recent_timbus_plates(
        self, route_id: int, dir_int: int, now_epoch: float, max_age_sec: float = 45.0
    ) -> set:
        """Biển số đã được Serving Layer hoặc Speed Layer cập nhật TimBus gần đây (< max_age_sec)."""
        recent = set()
        with self._tb_lock:
            for (r_id, d_id, plate), (ts, _, _) in self._tb_last_valid.items():
                if r_id == route_id and d_id == dir_int and (now_epoch - ts) < max_age_sec:
                    recent.add(plate)
        return recent

    def ingest_speed_layer_vehicles(
        self, route_id: int, dir_int: int, vehicles: List[BusVehicleDTO], now_epoch: float
    ) -> List[BusVehicleDTO]:
        """Nạp snapshot BusMap từ Speed Layer vào RouteProjectionTracker + MacroSpeedTracker."""
        if not vehicles:
            return []
        prepared = [self._prepare_vehicle(route_id, dir_int, v, now_epoch) for v in vehicles]
        prepared = [v for v in prepared if v.matched_projection is not None]
        if prepared:
            self._extractor.update_observation(route_id, dir_int, prepared, now_epoch)
            self._observe_causal_snapshot(route_id, dir_int, prepared, now_epoch)
        return prepared

    def ingest_speed_layer_timbus_hit(
        self,
        route_id: int,
        dir_int: int,
        bm_v: BusVehicleDTO,
        tb_rec: Any,
        now_epoch: float,
    ) -> Optional[BusVehicleDTO]:
        """Nạp bản ghi TimBus hit từ Speed Layer vào _tb_last_valid + extractor + CausalFeatures."""
        dir_str = "go" if dir_int == 0 else "re"
        shape_model = self._get_shape_model(route_id, dir_str)
        if shape_model is None:
            return None
        s_tb, ct_tb, seg_idx_tb = shape_model.project_point(tb_rec.latitude, tb_rec.longitude)
        if ct_tb > MAX_CORRIDOR_CROSS_TRACK_M:
            return None
        raw_ts = getattr(tb_rec, "fetch_timestamp", None)
        tb_ts, tb_iso = parse_ping_epoch(raw_ts, now_epoch) if raw_ts is not None else (now_epoch, now_hanoi_iso())
        ux, uy = shape_model.segment_unit_tangent(seg_idx_tb)
        tb_deg = math.degrees(math.atan2(ux, uy)) % 360.0
        tb_dto = bm_v.model_copy(
            update={
                "lat": float(tb_rec.latitude),
                "lng": float(tb_rec.longitude),
                "deg": tb_deg,
                "speed_kmh": float(tb_rec.speed_kmh),
                "raw_speed_kmh": float(tb_rec.speed_kmh),
                "updated_at": tb_iso,
                "busmap_updated_at": bm_v.updated_at,
                "telemetry_source": "timbus",
            }
        )
        tb_dto = self._prepare_vehicle(route_id, dir_int, tb_dto, now_epoch)
        if tb_dto.matched_projection is None:
            return None
        s_tb, _, seg_idx_tb = tb_dto.matched_projection
        p_norm = TimBusClient.normalize_plate(tb_dto.plate)
        if p_norm:
            with self._tb_lock:
                self._tb_last_valid[(route_id, dir_int, p_norm)] = (tb_ts, s_tb, tb_dto)
        self._extractor.update_observation(route_id, dir_int, [tb_dto], now_epoch)
        with self._get_causal_lock(route_id):
            self._causal.observe(
                Observation(
                    route_id=route_id,
                    direction=dir_int,
                    vehicle=p_norm or f"id:{tb_dto.id}",
                    source="timbus",
                    epoch=min(now_epoch, tb_ts),
                    received=now_epoch,
                    lat=float(tb_dto.lat),
                    lng=float(tb_dto.lng),
                    signature=f"{float(tb_dto.lat):.5f},{float(tb_dto.lng):.5f},{round(float(tb_dto.raw_speed_kmh or 0.0), 1)}",
                    context="speed_layer",
                )
            )
        return tb_dto

    def _get_live_incidents_epoch(self) -> float:
        lock = getattr(self, "_incident_lock", None)
        if lock is None:
            return float(getattr(self, "_live_incidents_epoch", 0.0) or 0.0)
        with lock:
            return float(getattr(self, "_live_incidents_epoch", 0.0) or 0.0)

    def sweep_stale_state(self, now_epoch: float, max_idle_sec: float = 3600.0) -> int:
        """Dọn định kỳ các trạng thái xe quá hạn trong RAM để tránh phình bộ nhớ khi chạy 24h+."""
        removed = 0
        passed_cutoff = now_epoch - PASSED_STATION_TTL_SEC
        idle_cutoff = now_epoch - max_idle_sec
        with self._tb_lock:
            for k in [k for k, ts in self._passed_station_plates.items() if ts < passed_cutoff]:
                self._passed_station_plates.pop(k, None)
                removed += 1
            for k in [k for k, (ts, _, _) in self._tb_last_valid.items() if ts < idle_cutoff]:
                self._tb_last_valid.pop(k, None)
                removed += 1
        removed += self._speed_tracker.sweep_stale(now_epoch, max_idle_sec=max_idle_sec)
        return removed

    def _is_route_eta_feasible(self, route_id: int, route_code: str) -> bool:
        """True nếu tuyến có baseline quan sát hoặc thuộc miền huấn luyện của ModelRuntime."""
        baseline_routes = set(getattr(self, "source_info", {}).get("baseline_routes") or ())
        if route_code in baseline_routes:
            return True
        route_idx = self._da.get_route_idx(route_id)
        if route_idx is not None and self._runtime.available and route_idx in self._runtime._known_routes:
            return True
        return False

    @staticmethod
    def _response(
        route_id: int, route_code: str, dir_int: int, dir_str: str, target_st, now_iso: str,
        day_type: int, hour_slot: int, traffic_cond: str, buses: List[ApproachingBusDTO], message: str,
        timbus_supported: bool = False, poll_interval_sec: int = DEFAULT_ETA_POLL_SEC,
        upstream_status: str = "ok", upstream_error: Optional[str] = None,
        timbus_status: str = "unsupported", timbus_error: Optional[str] = None,
        fallback_reason: Optional[str] = None,
        incidents: Optional[List[RouteIncidentDTO]] = None,
        incidents_fetched_at: Optional[str] = None,
    ) -> StationEtaResponse:
        return StationEtaResponse(
            route_id=route_id,
            route_code=route_code,
            direction=dir_int,
            direction_str=dir_str,
            target_station=target_st,
            query_time=now_iso,
            day_type=day_type,
            hour_slot=hour_slot,
            traffic_condition=traffic_cond,
            approaching_count=len(buses),
            buses=buses,
            message=message,
            timbus_supported=timbus_supported,
            poll_interval_sec=poll_interval_sec,
            upstream_status=upstream_status,
            upstream_error=upstream_error,
            timbus_status=timbus_status,
            timbus_error=timbus_error,
            fallback_reason=fallback_reason,
            incidents=list(incidents or []),
            incidents_fetched_at=incidents_fetched_at,
        )


__all__ = [
    "BusMapServingService",
    "RouteItemDTO",
    "RouteLiveResponse",
    "RouteShapeResponse",
    "RouteStationsResponse",
    "StationEtaResponse",
    "BusVehicleDTO",
    "normalize_direction",
    "fetch_live_vehicles_for_route",
]
