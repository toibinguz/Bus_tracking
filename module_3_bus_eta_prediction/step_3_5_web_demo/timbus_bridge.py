"""
Module 3 - Step 3.5: TimBus Realtime Telemetry Bridge & Macro-Micro ETA Fusion.
Bridges 5.0s sub-second GPS telemetry from TimBus with BusMap Canonical Ground Truth.
Complies strictly with:
  - TD-33 & TD-39: Never uses TimBus StationID or next_station_* raw fields; projects onto Canonical Frenet.
  - TD-35: Eliminates cross-source telemetry conflicts (Single Source of Truth per vehicle).
  - TD-37: Strict Direction Preservation (go -> dir=0, re -> dir=1; never min(d_perp_go, d_perp_re)).
  - TD-38: Fallback State Machine for missing / depot / off-line buses.
  - TD-52: Macro-Micro Fusion (XGBoost/Baseline macro + TimBus 5s micro progression).
"""

import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.system_config import (
    MAX_CORRIDOR_CROSS_TRACK_M,
    normalize_direction,
    normalize_direction_int,
)
from experiments.timbus.timbus_tracker import BusRecord, TimBusClient
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_serving_service import (
    EtaServingService,
)

TELEMETRY_STATE_TIMBUS_5S = "timbus_5s"
TELEMETRY_STATE_BUSMAP_RELAY = "busmap_relay"


def normalize_license_plate(plate: str) -> str:
    """Normalizes vehicle plate into alphanumeric uppercase without punctuation (e.g. '29B-205.54' -> '29B20554')."""
    if not plate:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(plate)).upper()


class TimBusRealtimeBridge:
    """
    Real-time coordinator bridging TimBus 5.0s telemetry with Canonical Serving Pipeline.
    Manages multi-threaded probe requests, WGS84 Frenet projection, and Fallback State Machine.
    """

    _instance: Optional["TimBusRealtimeBridge"] = None

    def __init__(self, service: EtaServingService) -> None:
        self.service = service
        self.extractor = service.extractor
        # Bộ đệm giữ trạng thái viễn trắc TimBus gần nhất theo xe để chống hiện tượng nhảy lùi (Jitter Drift)
        self.last_timbus_positions: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_instance(cls, service: Optional[EtaServingService] = None) -> "TimBusRealtimeBridge":
        """Singleton accessor for TimBusRealtimeBridge."""
        if cls._instance is None:
            if service is None:
                service = EtaServingService.get_instance()
            cls._instance = cls(service)
        return cls._instance

    def get_route_terminal_station_ids(self, route_code: str, direction: str) -> Tuple[int, int]:
        """
        Retrieves canonical terminal station IDs (origin, destination) for a given route and direction.
        Returns: (term_sid, alt_sid).
        """
        r_code = str(route_code)
        d_str = normalize_direction(direction)
        k_rd = (r_code, d_str)
        st_list = self.extractor.stations_by_dir.get(k_rd, [])
        if not st_list:
            return (1750, 1667)
        # Primary terminal: destination station (where buses head towards)
        term_sid = int(st_list[-1][1])
        # Alternate terminal: origin station (staging / departure)
        alt_sid = int(st_list[0][1])
        return (term_sid, alt_sid)

    def project_timbus_telemetry(
        self, route_code: str, direction: str, lat: float, lon: float
    ) -> Tuple[float, float, bool]:
        """
        Projects TimBus (lat, lon) onto Canonical Shape polyline with strict direction preservation (TD-37).
        Returns: (s_bus_m, cross_track_m, is_on_corridor).
        """
        d_str = normalize_direction(direction)
        return self.extractor.project_coordinate(route_code, d_str, float(lat), float(lon))

    def interpolate_micro_eta(
        self,
        predictions: List[Dict[str, Any]],
        old_s_bus: float,
        new_s_bus: float,
        current_speed_kmh: float,
    ) -> List[Dict[str, Any]]:
        """
        TD-52 Micro-ETA Interpolation:
        Smoothly adjusts upcoming station ETAs based on actual physical distance covered (delta_s).
        Preserves macro Baseline + ML residual boundaries while enabling second-by-second countdown.
        """
        if not predictions:
            return predictions

        delta_s = new_s_bus - old_s_bus
        if delta_s <= 0.0:
            return predictions

        # Effective kinematic speed for micro segment traversal
        eff_mps = max(2.5, min(18.0, current_speed_kmh / 3.6))
        # Physical time saved across the micro progression (capped at 300s to prevent jump distortion)
        dt_saved = min(300.0, max(0.0, delta_s / eff_mps))

        updated_preds: List[Dict[str, Any]] = []
        for p in predictions:
            p_copy = dict(p)
            orig_eta_s = float(p_copy.get("eta_seconds", 0.0))
            # Monotonic decrement with safety floor of 5.0 seconds
            new_eta_s = max(5.0, round(orig_eta_s - dt_saved, 1))
            p_copy["eta_seconds"] = new_eta_s
            p_copy["eta_minutes"] = round(new_eta_s / 60.0, 1)
            updated_preds.append(p_copy)

        return updated_preds

    def resolve_bus_telemetry_state(
        self,
        route_code: str,
        direction: str,
        bus_item: Dict[str, Any],
        tb_record: Optional[Any],
    ) -> Dict[str, Any]:
        """
        Evaluates Telemetry Fallback State Machine for a single vehicle:
          - If tb_record is valid AND d_perp <= 35m -> State: TIMBUS_5S (và cập nhật bộ nhớ đệm)
          - If tb_record is None nhưng có tọa độ TimBus tươi trong <= 12s -> Giữ nguyên vị trí TimBus
            (Chống giật lùi 600m về tọa độ BusMap cũ do trễ mạng GPRS theo Báo cáo Heartbeat #2)
          - Else -> State: BUSMAP_RELAY
        """
        res_bus = dict(bus_item)
        vid = str(res_bus.get("vehicle_id", ""))
        now_epoch = time.time()

        if tb_record is None:
            # Kiểm tra xem xe này có tọa độ TimBus tươi trong 12 giây gần nhất không
            if vid in self.last_timbus_positions and (now_epoch - self.last_timbus_positions[vid]["epoch"] <= 12.0):
                cached = self.last_timbus_positions[vid]
                res_bus["telemetry_source"] = TELEMETRY_STATE_TIMBUS_5S
                res_bus["lat"] = cached["lat"]
                res_bus["lon"] = cached["lon"]
                res_bus["speed_kmh"] = cached["speed_kmh"]
                res_bus["current_s_bus_m"] = cached["s_bus_m"]
                res_bus["cross_track_m"] = cached["cross_track_m"]
                if cached.get("station_order") is not None:
                    res_bus["current_station_order"] = cached["station_order"]
                if cached.get("station_name"):
                    res_bus["current_station_name"] = cached["station_name"]
                return res_bus

            res_bus["telemetry_source"] = TELEMETRY_STATE_BUSMAP_RELAY
            return res_bus

        r_code = str(route_code)
        d_str = normalize_direction(direction)
        k_rd = (r_code, d_str)

        # 1. Project TimBus coordinate onto canonical centerline
        s_bus, d_perp, is_on = self.project_timbus_telemetry(
            r_code, d_str, tb_record.latitude, tb_record.longitude
        )

        # 2. Strict corridor tolerance check (MAX_CORRIDOR_CROSS_TRACK_M = 35.0m)
        if is_on and d_perp <= MAX_CORRIDOR_CROSS_TRACK_M:
            old_s = float(res_bus.get("current_s_bus_m", s_bus))
            res_bus["telemetry_source"] = TELEMETRY_STATE_TIMBUS_5S
            res_bus["lat"] = float(tb_record.latitude)
            res_bus["lon"] = float(tb_record.longitude)
            res_bus["speed_kmh"] = float(tb_record.speed_kmh)
            res_bus["current_s_bus_m"] = round(s_bus, 1)
            res_bus["cross_track_m"] = round(d_perp, 1)

            # 3. Update current passed station if station distances are available
            if k_rd in self.extractor.st_s_vals:
                st_s_vals = self.extractor.st_s_vals[k_rd]
                st_orders = self.extractor.st_orders[k_rd]
                st_list = self.extractor.stations_by_dir.get(k_rd, [])
                k_curr = int(np.searchsorted(st_s_vals, s_bus, side="right")) - 1
                k_curr = min(len(st_s_vals) - 2, max(0, k_curr))
                res_bus["current_station_order"] = int(st_orders[k_curr])
                if k_curr < len(st_list):
                    res_bus["current_station_name"] = str(st_list[k_curr][2])

            # 4. TD-52 Micro-ETA Interpolation
            res_bus["predictions"] = self.interpolate_micro_eta(
                predictions=res_bus.get("predictions", []),
                old_s_bus=old_s,
                new_s_bus=s_bus,
                current_speed_kmh=float(tb_record.speed_kmh),
            )

            # Lưu vào bộ nhớ đệm chống trôi pha viễn thông
            self.last_timbus_positions[vid] = {
                "epoch": now_epoch,
                "lat": res_bus["lat"],
                "lon": res_bus["lon"],
                "speed_kmh": res_bus["speed_kmh"],
                "s_bus_m": s_bus,
                "cross_track_m": d_perp,
                "station_order": res_bus.get("current_station_order"),
                "station_name": res_bus.get("current_station_name"),
            }
        else:
            # TD-41: Detour or lateral deviation > 35m -> Fallback to BusMap relay
            res_bus["telemetry_source"] = TELEMETRY_STATE_BUSMAP_RELAY

        return res_bus

    def enrich_snapshot_with_timbus(
        self,
        route_code: str,
        direction: Union[str, int],
        raw_snapshot: Dict[str, Any],
        timeout: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Enriches a BusMap route snapshot with 5.0s TimBus GPS telemetry.
        Runs multi-threaded probe queries across all active buses.
        Guarantees zero regression: any unmapped bus seamlessly retains its BusMap data.
        """
        buses = raw_snapshot.get("buses", [])
        if not buses:
            return raw_snapshot

        r_code = str(route_code)
        d_str = normalize_direction(direction)
        dir_int = normalize_direction_int(direction)
        term_sid, alt_sid = self.get_route_terminal_station_ids(r_code, d_str)

        # Prepare parallel query worker
        def _probe_single_bus(b_item: Dict[str, Any]) -> Tuple[str, Optional[Any]]:
            vid = str(b_item.get("vehicle_id", ""))
            raw_plate = b_item.get("plate", "")
            clean_plate = normalize_license_plate(raw_plate)
            if not clean_plate:
                return (vid, None)
            try:
                # Query TimBus targeted vehicle using destination terminal FleId
                tb = TimBusClient.query_targeted_vehicle(
                    station_id=term_sid,
                    route_code=r_code,
                    plate=clean_plate,
                    direction=dir_int,
                    timeout=timeout,
                )
                if not tb and alt_sid:
                    # Alternate probe on origin terminal if staging at depot
                    tb = TimBusClient.query_targeted_vehicle(
                        station_id=alt_sid,
                        route_code=r_code,
                        plate=clean_plate,
                        direction=dir_int,
                        timeout=timeout,
                    )
                return (vid, tb)
            except Exception:
                return (vid, None)

        # Execute parallel probe across active fleet
        with ThreadPoolExecutor(max_workers=8) as executor:
            probe_results = dict(executor.map(_probe_single_bus, buses))

        # Apply Fallback State Machine & Micro-ETA interpolation
        enriched_buses: List[Dict[str, Any]] = []
        for b in buses:
            vid = str(b.get("vehicle_id", ""))
            tb_rec = probe_results.get(vid)
            resolved_b = self.resolve_bus_telemetry_state(
                route_code=r_code,
                direction=d_str,
                bus_item=b,
                tb_record=tb_rec,
            )
            enriched_buses.append(resolved_b)

        enriched_snapshot = dict(raw_snapshot)
        enriched_snapshot["buses"] = enriched_buses
        return enriched_snapshot
