"""
Step 3.4 — RouteProjectionTracker: theo dõi quỹ đạo nhân quả RouteHMM trên 1D Frenet.
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/projection_tracker.py
"""

import threading
from typing import Dict, List, Optional, Tuple

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.route_matcher import (
    RouteHMM,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.dto import BusVehicleDTO
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.live_feed import parse_ping_epoch


class RouteProjectionTracker:
    """Theo dõi khớp tuyến nhân quả RouteHMM theo từng xe trên RAM."""

    def __init__(self, data_access: DataAccess):
        self._da = data_access
        self._shape_models: Dict[Tuple[int, str], Optional[ShapeProjectionModel]] = {}
        self._match_lock = threading.RLock()
        self._matchers: Dict[Tuple[int, int, int], RouteHMM] = {}
        self._matched: Dict[Tuple[int, int, int], Tuple[float, dict, BusVehicleDTO]] = {}
        self._directions: Dict[Tuple[int, int], Tuple[int, float]] = {}
        self._generations: Dict[Tuple[int, int], int] = {}

    def project_vehicle(
        self, route_id: int, dir_int: int, vehicle: BusVehicleDTO, now_epoch: float
    ) -> BusVehicleDTO:
        """One causal route match per source timestamp, reused by every consumer."""
        shape = self._get_shape_model(route_id, "go" if dir_int == 0 else "re")
        if shape is None:
            return vehicle.model_copy(
                update={"projection_checked": True, "matched_projection": None, "projection_status": "missing_shape"}
            )
        epoch, _ = parse_ping_epoch(vehicle.updated_at, now_epoch)
        epoch = min(epoch, now_epoch)
        key = (route_id, dir_int, vehicle.id)
        identity = (route_id, vehicle.id)
        with self._match_lock:
            previous_direction = self._directions.get(identity)
            if previous_direction and previous_direction[0] != dir_int:
                if epoch <= previous_direction[1]:
                    return vehicle.model_copy(
                        update={
                            "projection_checked": True,
                            "matched_projection": None,
                            "projection_status": "old_direction",
                            "projection_generation": self._generations.get(identity, 0),
                        }
                    )
                self._reset_vehicle(route_id, vehicle.id)
            self._directions[identity] = (
                dir_int,
                max(epoch, previous_direction[1] if previous_direction and previous_direction[0] == dir_int else epoch),
            )
            cached = self._matched.get(key)
            if cached and epoch < cached[0]:
                return cached[2]
            if cached and epoch == cached[0]:
                return vehicle.model_copy(update=cached[1])
            matcher = self._matchers.setdefault(key, RouteHMM(shape))
            old_resets = matcher.resets
            match = matcher.update(epoch, vehicle.lat, vehicle.lng, int(epoch * 1000))
            if matcher.resets != old_resets:
                self._generations[identity] = self._generations.get(identity, 0) + 1
            update = dict(
                projection_checked=True,
                matched_projection=(match.s, match.cross_track, match.segment) if match else None,
                projection_status=matcher.reason,
                projection_generation=self._generations.get(identity, 0),
            )
            prepared = vehicle.model_copy(update=update)
            self._matched[key] = (epoch, update, prepared)
            return prepared

    def _reset_vehicle(self, route_id: int, vehicle_id: int) -> None:
        for key in list(self._matchers):
            if key[0] == route_id and key[2] == vehicle_id:
                self._matchers.pop(key, None)
                self._matched.pop(key, None)
        identity = (route_id, vehicle_id)
        self._generations[identity] = self._generations.get(identity, 0) + 1

    def projection_history(self, route_id: int, dir_int: int, vehicle_id: int) -> Dict[float, float]:
        with self._match_lock:
            matcher = self._matchers.get((route_id, dir_int, vehicle_id))
            return {p.epoch: p.s for p in matcher.best_path} if matcher else {}

    def _get_shape_model(self, route_id: int, dir_str: str) -> Optional[ShapeProjectionModel]:
        with self._match_lock:
            key = (route_id, dir_str)
            if key not in self._shape_models:
                points = self._da.get_shape_points(route_id, dir_str)
                self._shape_models[key] = ShapeProjectionModel.build(points) if len(points) >= 2 else None
            return self._shape_models[key]

    def update_observation(
        self, route_id: int, dir_int: int, vehicles: List[BusVehicleDTO], now_epoch: float
    ) -> None:
        """Cập nhật phép chiếu RouteHMM cho toàn bộ xe trên tuyến/chiều."""
        for v in vehicles:
            self.project_vehicle(route_id, dir_int, v, now_epoch)
