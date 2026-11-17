"""
Step 3.4 — Orchestrator serving (BusMapServingService) + facade cho app.py.
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py

Ghép: data_access + live_feed + frenet + online_features + model_runtime + eta_policy.
Đây là implementation thay thế `busmap_service.py` cũ (sẽ retire ở task 10).
"""

from concurrent.futures import ThreadPoolExecutor
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
    TZ_HANOI,
)
from experiments.timbus.timbus_tracker import TimBusClient
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess, IncidentsProvider
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import (
    ApproachingBusDTO,
    BusVehicleDTO,
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
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import ModelRuntime
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import OnlineFeatureExtractor

logger = logging.getLogger(__name__)

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
                if s_bus < last_s - 50.0:
                    # Xe quay đầu bến / bắt đầu lượt mới
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
            self._incidents = IncidentsProvider()
            self.source_info = dict(mode='local', artifact_id=None, snapshot_id=None,
                                    baseline_routes=sorted(self._da.route_idx_by_code),
                                    model_status='candidate_unverified' if self._runtime.available else 'unavailable')
        self._extractor = OnlineFeatureExtractor(self._da, self._incidents)
        self._shape_models: Dict[Tuple[int, str], Optional[ShapeProjectionModel]] = {}
        # Cache Monotonicity, danh sách xe vượt trạm theo từng trạm & vận tốc vĩ mô cho luồng hybrid TimBus 5s
        self._tb_lock = threading.Lock()
        self._tb_last_valid: Dict[Tuple[int, int, str], Tuple[float, float, BusVehicleDTO]] = {}
        self._passed_station_plates: Dict[Tuple[int, int, int, str], float] = {}
        self._speed_tracker = MacroSpeedTracker()

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
            return resp.model_copy(update={"timbus_supported": timbus_ok, "poll_interval_sec": poll_sec})

        now_epoch = datetime.now(TZ_HANOI).timestamp()
        _, merged = self._sync_route_both_directions(
            route_id=route_id,
            primary_dir=dir_int,
            now_epoch=now_epoch,
            station_order=None,
            s_target=None,
            primary_live_resp=resp,
        )
        return resp.model_copy(
            update={
                "count": len(merged),
                "timestamp": now_hanoi_iso(),
                "timbus_supported": True,
                "poll_interval_sec": poll_sec,
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
                self._sync_single_direction,
                route_id,
                primary_dir,
                now_epoch,
                station_order,
                s_target,
                primary_live_resp,
            )
            fut_other = pool.submit(
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
                            bm_ts, _ = parse_ping_epoch(bm_v.updated_at, 0.0)
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
                tb_map = TimBusClient.query_central_vehicles(
                    station_ids=anchor_sids,
                    plates=plates_to_query,
                    direction=dir_int,
                    timeout=timeout_s,
                )
            except Exception as e:
                logger.warning("Lỗi truy vấn TimBus route=%s dir=%s: %s", route_id, dir_int, e)
                tb_map = {}

            for p_norm in plates_to_query:
                bm_entry = bm_proj.get(p_norm)
                if bm_entry is None:
                    continue
                bm_v, s_bm, ct_bm = bm_entry
                bm_ping_epoch, _ = parse_ping_epoch(bm_v.updated_at, 0.0)
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
                                "telemetry_source": "timbus",
                            }
                        )
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
            s_cur, cross_track, _ = shape_model.project_point(vehicle.lat, vehicle.lng)
            if cross_track > MAX_CORRIDOR_CROSS_TRACK_M:
                continue
            plate = TimBusClient.normalize_plate(vehicle.plate)
            key = (route_id, dir_int, station_order, plate) if station_order is not None else None
            if s_cur > s_target:
                if key is not None:
                    with self._tb_lock:
                        self._passed_station_plates[key] = now_epoch
                continue
            if key is not None and self._is_recently_passed_locked(key, s_cur, s_target, now_epoch):
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
            p_norm = TimBusClient.normalize_plate(v.plate)
            if not p_norm:
                stabilized.append(v)
                continue
            s_cur, _, _ = shape_model.project_point(v.lat, v.lng)
            t_sample, _ = parse_ping_epoch(v.updated_at, now_epoch)
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

        n_stations = len(stations_resp.stations)
        if station_order < 0 or station_order >= n_stations:
            return None

        target_st = stations_resp.stations[station_order]
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

        live_resp = fetch_live_vehicles_for_route(route_id=route_id, direction=dir_int)
        if live_resp.count == 0:
            return self._response(
                route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
                "THONG_THOANG", [], "Hiện chưa có xe trực tiếp trên tuyến này.",
                timbus_supported=timbus_ok, poll_interval_sec=poll_sec,
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
            vehicles = live_resp.vehicles
            self._extractor.update_observation(route_id, dir_int, vehicles, now_epoch)

        station_s = [st.cum_distance_m for st in stations_resp.stations]
        approaching: List[ApproachingBusDTO] = []
        speeds: List[float] = []

        for v in vehicles:
            bus_state = project_filter_extrapolate(v, shape_model, s_target, now_epoch)
            if bus_state is None:
                continue

            features = self._extractor.build_features(
                route_id=route_id,
                dir_int=dir_int,
                vehicle=v,
                target_order=station_order,
                s_target_m=s_target,
                s_bus_m=bus_state.s_now,
                now_epoch=now_epoch,
            )
            ml_p50 = self._runtime.predict_p50(features) if self._runtime.available else None
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
            )
            dto = dto.model_copy(update={"telemetry_source": v.telemetry_source})
            approaching.append(dto)
            speeds.append(v.speed_kmh)

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
        return self._response(
            route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
            traffic_cond, approaching, message,
            timbus_supported=timbus_ok, poll_interval_sec=poll_sec,
        )

    @staticmethod
    def _response(
        route_id: int, route_code: str, dir_int: int, dir_str: str, target_st, now_iso: str,
        day_type: int, hour_slot: int, traffic_cond: str, buses: List[ApproachingBusDTO], message: str,
        timbus_supported: bool = False, poll_interval_sec: int = DEFAULT_ETA_POLL_SEC,
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
