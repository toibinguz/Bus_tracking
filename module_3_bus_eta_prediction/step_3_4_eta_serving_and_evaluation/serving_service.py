"""
Step 3.4 — Orchestrator serving (BusMapServingService) + facade cho app.py.
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py

Ghép: data_access + live_feed + frenet + online_features + model_runtime + eta_policy.
Đây là implementation thay thế `busmap_service.py` cũ (sẽ retire ở task 10).
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

from config.system_config import CONGESTION_SPEED_THRESHOLD_KMPH, FREEFLOW_SPEED_THRESHOLD_KMPH, TZ_HANOI
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
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import ModelRuntime
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_features import OnlineFeatureExtractor

logger = logging.getLogger(__name__)


class BusMapServingService:
    """Service phục vụ danh mục tuyến, vị trí xe trực tiếp và dự báo ETA trạm (ML + baseline)."""

    def __init__(self, db_path: Optional[str] = None):
        self._da = DataAccess(db_path)
        self._runtime = ModelRuntime.load()
        self._incidents = IncidentsProvider()
        self._extractor = OnlineFeatureExtractor(self._da, self._incidents)
        self._shape_models: Dict[Tuple[int, str], Optional[ShapeProjectionModel]] = {}

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
                vehicles=[],
            )
        return fetch_live_vehicles_for_route(route_id=route_id, direction=direction)

    def _get_shape_model(self, route_id: int, dir_str: str) -> Optional[ShapeProjectionModel]:
        key = (route_id, dir_str)
        if key not in self._shape_models:
            points = self._da.get_shape_points(route_id, dir_str)
            self._shape_models[key] = ShapeProjectionModel.build(points) if len(points) >= 2 else None
        return self._shape_models[key]

    # -------------------------------------------------------------------- ETA
    def get_station_eta(
        self,
        route_ident: Union[str, int],
        direction: Union[int, str] = 0,
        station_order: int = 0,
    ) -> Optional[StationEtaResponse]:
        """1. fetch live; 2. cập nhật state extractor; 3. mỗi xe: project->features->ML->policy; 4. đóng gói."""
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
            )

        live_resp = fetch_live_vehicles_for_route(route_id=route_id, direction=dir_int)
        if live_resp.count == 0:
            return self._response(
                route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
                "THONG_THOANG", [], "Hiện chưa có xe trực tiếp trên tuyến này.",
            )

        shape_model = self._get_shape_model(route_id, dir_str)
        if shape_model is None:
            return self._response(
                route_id, route_code, dir_int, dir_str, target_st, now_iso, day_type, hour_slot,
                "THONG_THOANG", [], "Đang đồng bộ hình học tuyến...",
            )

        self._extractor.update_observation(route_id, dir_int, live_resp.vehicles, now_epoch)

        station_s = [st.cum_distance_m for st in stations_resp.stations]
        approaching: List[ApproachingBusDTO] = []
        speeds: List[float] = []

        for v in live_resp.vehicles:
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
        )

    @staticmethod
    def _response(
        route_id: int, route_code: str, dir_int: int, dir_str: str, target_st, now_iso: str,
        day_type: int, hour_slot: int, traffic_cond: str, buses: List[ApproachingBusDTO], message: str,
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
