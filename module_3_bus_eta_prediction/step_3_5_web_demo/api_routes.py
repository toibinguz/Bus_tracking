"""
Module 3 - Step 3.5: FastAPI RESTful Router.
Implements the 4 endpoints defined by contract.py:
1. GET /api/v1/routes
2. GET /api/v1/routes/{route_code}/geometry
3. GET /api/v1/routes/{route_code}/live-eta
4. GET /api/v1/health
"""

import os
import re
import sys
import time
from datetime import datetime, timedelta
from typing import List, Optional

import psutil
from fastapi import APIRouter, HTTPException, Query

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, BASE_DIR)

from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.eta_serving_service import (
    EtaServingService,
)
from module_3_bus_eta_prediction.step_3_5_web_demo.cache_manager import route_eta_cache
from module_3_bus_eta_prediction.step_3_5_web_demo.contract import (
    GeoJsonLineString,
    HealthResponse,
    LiveBusItem,
    LiveEtaResponse,
    PredictionItem,
    RouteGeometryResponse,
    RouteItem,
    StationGeometryItem,
)

router = APIRouter(prefix="/api/v1", tags=["ETA Prediction"])
SERVER_START_TIME = time.time()


def _natural_route_sort_key(route_code: str):
    """Sort helper to naturally arrange route codes (e.g., 01, 02, 10, 100, E01)."""
    match = re.match(r"^(\D*)(\d+)(.*)$", route_code)
    if match:
        prefix, num, suffix = match.groups()
        return (0 if not prefix else 1, prefix, int(num), suffix)
    return (2, route_code, 0, "")


@router.get("/routes", response_model=List[RouteItem], summary="Lấy danh mục các tuyến xe buýt")
def get_routes() -> List[RouteItem]:
    """Trả về danh mục toàn bộ các tuyến xe buýt hiện có trong Master Ground Truth."""
    service = EtaServingService.get_instance()
    meta = service.extractor.route_meta

    items: List[RouteItem] = []
    for rc, info in meta.items():
        # Check if both directions exist in stations
        has_go = (rc, "go") in service.extractor.stations_by_dir
        has_re = (rc, "re") in service.extractor.stations_by_dir
        items.append(
            RouteItem(
                route_code=rc,
                route_id=info["route_id"],
                route_name=info["route_name"],
                has_go_direction=has_go,
                has_re_direction=has_re,
            )
        )

    items.sort(key=lambda x: _natural_route_sort_key(x.route_code))
    return items


@router.get(
    "/routes/{route_code}/geometry",
    response_model=RouteGeometryResponse,
    summary="Lấy tọa độ tim đường và trạm dừng theo tuyến",
)
def get_route_geometry(
    route_code: str,
    direction: str = Query("go", description="Chiều di chuyển: 'go' hoặc 're'"),
) -> RouteGeometryResponse:
    """Trả về GeoJSON LineString tim đường và danh sách trạm dừng có tọa độ dọc hành lang."""
    service = EtaServingService.get_instance()
    r_code = str(route_code)
    d_str = "re" if str(direction).lower() in ("1", "re", "chiều về") else "go"

    if r_code not in service.extractor.route_meta:
        raise HTTPException(
            status_code=404, detail=f"Tuyến xe buýt '{r_code}' không tồn tại trong CSDL."
        )

    k_rd = (r_code, d_str)
    shape_pts = service.extractor.route_shape_pts.get(k_rd, [])
    if not shape_pts:
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy dữ liệu tim đường cho tuyến '{r_code}' chiều '{d_str}'.",
        )

    # GeoJSON coordinates format: [lon, lat]
    coords = [[pt[2], pt[1]] for pt in shape_pts]
    route_len = service.extractor.route_shape_len.get(k_rd, 0.0)

    # Stations
    raw_stations = service.extractor.station_details.get(k_rd, [])
    station_items = [
        StationGeometryItem(
            station_order=st["station_order"],
            station_id=st["station_id"],
            station_name=st["station_name"],
            lat=st["lat"],
            lon=st["lon"],
            cum_distance_m=round(st["cum_distance_m"], 1),
        )
        for st in raw_stations
    ]

    return RouteGeometryResponse(
        route_code=r_code,
        direction=d_str,
        route_length_m=round(route_len, 1),
        shape_geojson=GeoJsonLineString(coordinates=coords),
        stations=station_items,
    )


@router.get(
    "/routes/{route_code}/live-eta",
    response_model=LiveEtaResponse,
    summary="Lấy dữ liệu xe buýt thời gian thực & dự báo ETA an toàn",
)
def get_live_eta(
    route_code: str,
    direction: str = Query("go", description="Chiều di chuyển: 'go' hoặc 're'"),
    target_station_order: Optional[int] = Query(
        None, description="Tùy chọn lọc dự báo cho riêng trạm dừng cụ thể"
    ),
) -> LiveEtaResponse:
    """
    Truy vấn snapshot xe buýt thời gian thực ngoài đường phố Hà Nội,
    tính toán dự báo ETA và cửa sổ an toàn [P10, P90] phòng ngừa rủi ro lỡ chuyến.
    Phục vụ qua bộ đệm TTL Cache 15s.
    """
    service = EtaServingService.get_instance()
    r_code = str(route_code)
    d_str = "re" if str(direction).lower() in ("1", "re", "chiều về") else "go"

    if r_code not in service.extractor.route_meta:
        raise HTTPException(
            status_code=404, detail=f"Tuyến xe buýt '{r_code}' không tồn tại trong CSDL."
        )

    cache_key = f"{r_code}:{d_str}"
    cached_payload = route_eta_cache.get(cache_key)

    if cached_payload is not None:
        # Clone response with cached flag set to True
        resp_data = dict(cached_payload)
        resp_data["cached"] = True
        return LiveEtaResponse(**resp_data)

    # Cache miss: Query live from BusMap & infer
    raw_snapshot = service.predict_route_snapshot_live(
        route_code=r_code,
        direction=d_str,
    )

    now_dt = datetime.now()
    now_iso = now_dt.isoformat()

    bus_items: List[LiveBusItem] = []
    active_speeds: List[float] = []

    for b in raw_snapshot.get("buses", []):
        status = b.get("status", "UNKNOWN")
        spd = float(b.get("speed_kmh", 0.0))
        if status == "ACTIVE_IN_TRANSIT":
            active_speeds.append(spd)

        preds: List[PredictionItem] = []
        for p in b.get("predictions", []):
            t_ord = int(p["target_station_order"])
            if target_station_order is not None and t_ord != int(target_station_order):
                continue

            eta_s = float(p["eta_seconds"])
            eta_min = float(p["eta_minutes"])

            # Asymmetric Arrival Risk Calculation:
            # P10 arrival (conservative / safe): bus arrives up to 15% faster minus 60s buffer
            p10_sec = max(0.0, eta_s * 0.85 - 60.0)
            # P90 arrival: bus encounters heavy delay (25% slower plus 90s)
            p90_sec = eta_s * 1.25 + 90.0

            t_safe = now_dt + timedelta(seconds=p10_sec)
            t_exp = now_dt + timedelta(seconds=eta_s)
            t_late = now_dt + timedelta(seconds=p90_sec)

            safe_str = t_safe.strftime("%H:%M")
            exp_str = t_exp.strftime("%H:%M")
            win_str = f"{safe_str} – {t_late.strftime('%H:%M')}"

            preds.append(
                PredictionItem(
                    target_station_order=t_ord,
                    target_station_id=int(p["target_station_id"]),
                    target_station_name=str(p["target_station_name"]),
                    target_distance_m=float(p.get("target_distance_m", 0.0)),
                    eta_seconds=round(eta_s, 1),
                    eta_minutes=round(eta_min, 1),
                    safe_arrival_time=safe_str,
                    expected_arrival_time=exp_str,
                    safe_window=win_str,
                )
            )

        bus_items.append(
            LiveBusItem(
                vehicle_id=str(b.get("vehicle_id", "")),
                plate=str(b.get("plate", "Không rõ")),
                status=status,
                lat=float(b.get("lat", 0.0)),
                lon=float(b.get("lon", 0.0)),
                speed_kmh=spd,
                heading_deg=float(b.get("heading_deg", 0.0)),
                current_s_bus_m=b.get("current_s_bus_m") or b.get("s_bus_m"),
                cross_track_m=b.get("cross_track_m"),
                current_station_order=b.get("current_station_order"),
                current_station_name=b.get("current_station_name"),
                message=b.get("message"),
                predictions=preds,
            )
        )

    # Determine corridor traffic condition
    if not active_speeds:
        traffic_cond = "Thông thoáng (Chưa có xe xuất bến)"
    else:
        avg_v = sum(active_speeds) / len(active_speeds)
        if avg_v >= 22.0:
            traffic_cond = f"Thông thoáng (Vận tốc trung bình ~{avg_v:.0f} km/h)"
        elif avg_v >= 12.0:
            traffic_cond = f"Ùn ứ chậm (Vận tốc trung bình ~{avg_v:.0f} km/h)"
        else:
            traffic_cond = f"Kẹt xe cục bộ (Vận tốc trung bình ~{avg_v:.0f} km/h)"

    response_obj = LiveEtaResponse(
        route_code=r_code,
        direction=d_str,
        timestamp=now_iso,
        cached=False,
        total_buses=len(bus_items),
        active_in_transit_count=raw_snapshot.get("active_in_transit_count", 0),
        traffic_condition=traffic_cond,
        buses=bus_items,
    )

    # Save to TTL Cache
    route_eta_cache.set(cache_key, response_obj.model_dump(), ttl_seconds=15.0)

    return response_obj


@router.get("/health", response_model=HealthResponse, summary="Giám sát trạng thái hệ thống")
def get_health() -> HealthResponse:
    """Trả về trạng thái hoạt động của máy chủ, số cache active và RAM tiêu thụ."""
    process = psutil.Process()
    rss_mb = process.memory_info().rss / (1024 * 1024)
    service_ready = EtaServingService._instance is not None

    return HealthResponse(
        status="healthy",
        service_initialized=service_ready,
        uptime_seconds=round(time.time() - SERVER_START_TIME, 1),
        active_cache_entries=route_eta_cache.count(),
        memory_rss_mb=round(rss_mb, 2),
    )
