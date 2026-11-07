"""
Module 3 - Step 3.5: End-to-End Real-Time ETA Serving Service.
Integrates OnlineFeatureExtractor and EtaInferenceEngine to serve low-latency ETA predictions
for single vehicles or whole route snapshots directly from BusMap live telemetry.

Features:
- High-level API for live route and vehicle queries
- Automatic coordinate convention handling (route_bus_gps vs vehicle_hn/get)
- Integrated Frenet orthogonal projector and cross-track corridor filter (d_perp <= 35.0m)
- Integrated Terminal Gate (TD-19)
- Sub-10ms single-query inference SLA
"""

import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, BASE_DIR)

from config.system_config import DEFAULT_DB_PATH
from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import (
    fetch_route_buses_live,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_inference_engine import (
    EtaInferenceEngine,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.online_feature_extractor import (
    OnlineFeatureExtractor,
)


class EtaServingService:
    """
    Unified production serving service for real-time bus ETA prediction.
    Combines online feature extraction and calibrated XGBoost residual inference.
    """

    _instance: Optional["EtaServingService"] = None

    @classmethod
    def get_instance(
        cls,
        tag: str = "_r3_big",
        db_path: str = DEFAULT_DB_PATH,
    ) -> "EtaServingService":
        """Singleton accessor ensuring in-memory models and tables are reused."""
        if cls._instance is None:
            cls._instance = cls(tag=tag, db_path=db_path)
        return cls._instance

    def __init__(
        self,
        tag: str = "_r3_big",
        db_path: str = DEFAULT_DB_PATH,
    ) -> None:
        self.extractor = OnlineFeatureExtractor(db_path=db_path)
        self.engine = EtaInferenceEngine(tag=tag)

    def predict_for_vehicle(
        self,
        route_code: str,
        direction: Union[str, int],
        vehicle_id: Union[str, int],
        lat: float,
        lon: float,
        speed_kmh: float = 0.0,
        device_epoch: Optional[float] = None,
        target_station_order: Optional[int] = None,
        is_vehicle_query: bool = False,
    ) -> Dict[str, Any]:
        """
        Calculates real-time ETA predictions for a single bus ping.
        - is_vehicle_query: Set True if lat/lon came from vehicle_hn/get (which has Lat=Lon, Lng=Lat).
        """
        t0 = time.time()
        r_code = str(route_code)
        d_str = "go" if str(direction) in ("0", "go", "Chiều đi") else "re"
        vid = str(vehicle_id)

        if device_epoch is None:
            device_epoch = time.time()

        # Handle coordinate convention if vehicle_hn/get
        if is_vehicle_query:
            actual_lat = float(lon)
            actual_lon = float(lat)
        else:
            actual_lat = float(lat)
            actual_lon = float(lon)

        # 1. Project onto route polyline
        s_bus, d_perp, is_on_corridor = self.extractor.project_coordinate(
            r_code, d_str, actual_lat, actual_lon
        )

        key = (r_code, d_str)
        st_list = self.extractor.stations_by_dir.get(key, [])
        if not st_list:
            return {
                "route_code": r_code,
                "direction": d_str,
                "vehicle_id": vid,
                "lat": actual_lat,
                "lon": actual_lon,
                "speed_kmh": round(speed_kmh, 1),
                "status": "ERROR_ROUTE_NOT_FOUND",
                "message": f"Route '{r_code}' direction '{d_str}' has no stations",
                "latency_ms": round((time.time() - t0) * 1000.0, 2),
            }

        # 2. Check corridor adherence
        if not is_on_corridor:
            return {
                "route_code": r_code,
                "direction": d_str,
                "vehicle_id": vid,
                "lat": actual_lat,
                "lon": actual_lon,
                "speed_kmh": round(speed_kmh, 1),
                "status": "DETOUR_OFF_CORRIDOR",
                "s_bus_m": round(s_bus, 1),
                "cross_track_m": round(d_perp, 1),
                "message": f"Bus is off-corridor by {d_perp:.1f}m (> 35.0m threshold)",
                "latency_ms": round((time.time() - t0) * 1000.0, 2),
            }

        # 3. Check Terminal Gate (TD-19)
        gate_status = self.extractor.get_terminal_gate_status(r_code, d_str, s_bus)
        if gate_status == "AT_ORIGIN_TERMINAL":
            return {
                "route_code": r_code,
                "direction": d_str,
                "vehicle_id": vid,
                "lat": actual_lat,
                "lon": actual_lon,
                "speed_kmh": round(speed_kmh, 1),
                "status": "AT_ORIGIN_TERMINAL",
                "s_bus_m": round(s_bus, 1),
                "message": "Bus is staging at origin terminal; waiting for scheduled dispatch",
                "latency_ms": round((time.time() - t0) * 1000.0, 2),
            }
        elif gate_status == "AT_DESTINATION_TERMINAL":
            return {
                "route_code": r_code,
                "direction": d_str,
                "vehicle_id": vid,
                "lat": actual_lat,
                "lon": actual_lon,
                "speed_kmh": round(speed_kmh, 1),
                "status": "AT_DESTINATION_TERMINAL",
                "s_bus_m": round(s_bus, 1),
                "message": "Bus has completed trip and entered destination terminal depot",
                "latency_ms": round((time.time() - t0) * 1000.0, 2),
            }

        # 4. Extract 54 features for in-transit bus
        df_feat = self.extractor.extract_features_for_ego(
            r_code, d_str, vid, device_epoch, s_bus, speed_kmh, target_station_order
        )

        if df_feat.empty:
            return {
                "route_code": r_code,
                "direction": d_str,
                "vehicle_id": vid,
                "status": "NO_UPCOMING_STATIONS",
                "s_bus_m": round(s_bus, 1),
                "message": "No valid upcoming stations ahead of current bus position",
                "latency_ms": round((time.time() - t0) * 1000.0, 2),
            }

        # 5. Predict via calibrated inference engine
        predicted_etas = self.engine.predict(df_feat, calibrate=True)

        ord_map = {st[0]: (st[1], st[2], st[3]) for st in st_list}
        st_orders = df_feat["target_station_order"].to_numpy(dtype=int)
        p50_baselines = df_feat["baseline_eta_p50_sec"].to_numpy(dtype=float)

        predictions: List[Dict[str, Any]] = []
        for i in range(len(st_orders)):
            t_ord = int(st_orders[i])
            eta_s = float(predicted_etas[i])
            base_s = float(p50_baselines[i])
            delta_s = eta_s - base_s
            s_id, s_name, s_dist = ord_map.get(t_ord, (-1, "Unknown", 0.0))

            predictions.append(
                {
                    "target_station_order": t_ord,
                    "target_station_id": s_id,
                    "target_station_name": s_name,
                    "target_distance_m": round(s_dist, 1),
                    "eta_seconds": round(eta_s, 1),
                    "eta_minutes": round(eta_s / 60.0, 1),
                    "baseline_p50_sec": round(base_s, 1),
                    "residual_delta_sec": round(delta_s, 1),
                }
            )

        k_curr = int(df_feat["current_station_order"].iloc[0])
        cur_id, cur_name, _ = ord_map.get(k_curr, (-1, "Unknown", 0.0))

        return {
            "route_code": r_code,
            "direction": d_str,
            "vehicle_id": vid,
            "status": "ACTIVE_IN_TRANSIT",
            "lat": actual_lat,
            "lon": actual_lon,
            "current_s_bus_m": round(s_bus, 1),
            "cross_track_m": round(d_perp, 1),
            "current_station_order": k_curr,
            "current_station_name": cur_name,
            "speed_kmh": round(speed_kmh, 1),
            "predictions_count": len(predictions),
            "predictions": predictions,
            "latency_ms": round((time.time() - t0) * 1000.0, 2),
        }

    def predict_route_snapshot_live(
        self,
        route_code: str,
        direction: Union[str, int] = 0,
        target_station_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Queries live route buses via BusMap route_bus_gps API and predicts ETAs for all active buses.
        """
        t0 = time.time()
        r_code = str(route_code)
        if r_code not in self.extractor.route_meta:
            raise KeyError(f"Tuyến route_code '{r_code}' không tồn tại trong canonical_route_master")

        route_id = self.extractor.route_meta[r_code]["route_id"]
        dir_int = 1 if str(direction) in ("1", "re", "Chiều về") else 0
        d_str = "re" if dir_int == 1 else "go"

        # Query live route buses from BusMap API
        live_buses = fetch_route_buses_live(route_id=route_id, direction=dir_int)
        if not live_buses:
            return {
                "route_code": r_code,
                "direction": d_str,
                "route_id": route_id,
                "total_buses": 0,
                "active_buses": 0,
                "buses": [],
                "latency_ms": round((time.time() - t0) * 1000.0, 2),
            }

        # Resolve target_station_order if target_station_id is provided
        target_station_order = None
        if target_station_id is not None:
            st_list = self.extractor.stations_by_dir.get((r_code, d_str), [])
            for st in st_list:
                if st[1] == int(target_station_id):
                    target_station_order = st[0]
                    break

        buses_out: List[Dict[str, Any]] = []
        active_count = 0

        for b in live_buses:
            vid = str(b.get("Id", ""))
            v_num = str(b.get("VehicleNumber", ""))
            lat = float(b.get("Lat", 0.0))
            lng = float(b.get("Lng", 0.0))
            spd = float(b.get("Speed", 0.0))

            res = self.predict_for_vehicle(
                route_code=r_code,
                direction=d_str,
                vehicle_id=vid,
                lat=lat,
                lon=lng,
                speed_kmh=spd,
                device_epoch=time.time(),
                target_station_order=target_station_order,
                is_vehicle_query=False,  # route_bus_gps has Lat=lat, Lng=lon
            )
            res["plate"] = v_num
            res["heading_deg"] = round(float(b.get("Deg", 0.0)), 1)
            buses_out.append(res)
            if res.get("status") == "ACTIVE_IN_TRANSIT":
                active_count += 1

        return {
            "route_code": r_code,
            "direction": d_str,
            "route_id": route_id,
            "total_buses": len(buses_out),
            "active_in_transit_count": active_count,
            "buses": buses_out,
            "latency_ms": round((time.time() - t0) * 1000.0, 2),
        }
