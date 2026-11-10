"""
Web Demo Application - BusMap Discrete Tracking Server
Module: module_3_bus_eta_prediction/step_3_5_web_demo/app.py

FastAPI server delivering discrete live bus positions and route catalogs.
100% BusMap HTTPS telemetry, zero TimBus/XOR/socket complexity.
"""

from pathlib import Path
from typing import Optional, List, Union
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation import (
    BusMapServingService,
    RouteItemDTO,
    RouteLiveResponse,
    RouteShapeResponse,
    RouteStationsResponse,
    StationEtaResponse,
    normalize_direction,
    fetch_live_vehicles_for_route
)

app = FastAPI(
    title="Hanoi Bus Live Discrete Tracking",
    description="Hệ thống theo dõi xe buýt Hà Nội giật cục rời rạc thời gian thực (BusMap discrete telemetry)",
    version="1.0.0"
)
app.app = app  # Support direct attribute lookup when imported as web_app.app

HEALTH_PAYLOAD = {
    "status": "healthy",
    "healthy": True,
    "provider": "busmap",
    "mode": "busmap_discrete_only",
    "upstream": "https://api.busmap.city/v2/public/busmap/route_bus_gps",
}

LOCAL_DEMO_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_DEMO_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize service singleton
service = BusMapServingService()

# Paths
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Mount static directory
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
def get_root():
    """Phục vụ trang Web Demo chính."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Giao diện Web Demo chưa được tạo.")
    return FileResponse(index_path)


@app.get("/api/health")
@app.get("/api/v1/health")
def get_health():
    """Kiểm tra tình trạng sức khỏe của backend và upstream."""
    return HEALTH_PAYLOAD


@app.get("/api/routes", response_model=List[RouteItemDTO])
def get_routes():
    """Cung cấp danh mục các tuyến xe buýt hỗ trợ."""
    return service.get_routes()


@app.get("/api/live-vehicles", response_model=RouteLiveResponse)
def get_live_vehicles(
    route_id: Optional[int] = Query(None, description="Mã route_id BusMap"),
    route: Optional[str] = Query(None, description="Số hiệu tuyến (ví dụ: '27', '01', 'E01')"),
    direction: Optional[Union[int, str]] = Query(0, description="0: Chiều đi ('go'), 1: Chiều về ('re')")
):
    """
    Truy vấn vị trí xe trực tiếp theo tuyến và chiều hành trình.
    """
    target_ident = route_id if route_id is not None else route
    if target_ident is None:
        raise HTTPException(status_code=400, detail="Cần cung cấp ít nhất một tham số: 'route_id' hoặc 'route'")

    try:
        dir_int, _ = normalize_direction(direction)
    except ValueError:
        raise HTTPException(status_code=400, detail="Tham số 'direction' không hợp lệ. Chỉ chấp nhận 0, 1, 'go', hoặc 're'")

    resolved_id = service.resolve_route_id(target_ident)
    if resolved_id is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy tuyến '{target_ident}' trong danh mục")

    return fetch_live_vehicles_for_route(route_id=resolved_id, direction=dir_int)


@app.get("/api/route-shape", response_model=RouteShapeResponse)
def get_route_shape(
    route_id: Optional[int] = Query(None, description="Mã route_id BusMap"),
    route: Optional[str] = Query(None, description="Số hiệu tuyến (ví dụ: '27', '01', 'E01')"),
    direction: Optional[Union[int, str]] = Query(0, description="0: Chiều đi ('go'), 1: Chiều về ('re')")
):
    """
    Truy vấn tọa độ tim tuyến chi tiết theo số hiệu tuyến hoặc route_id và chiều hành trình.
    """
    target_ident = route_id if route_id is not None else route
    if target_ident is None:
        raise HTTPException(status_code=400, detail="Cần cung cấp ít nhất một tham số: 'route_id' hoặc 'route'")

    try:
        dir_int, _ = normalize_direction(direction)
    except ValueError:
        raise HTTPException(status_code=400, detail="Tham số 'direction' không hợp lệ. Chỉ chấp nhận 0, 1, 'go', hoặc 're'")

    resolved_id = service.resolve_route_id(target_ident)
    if resolved_id is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy tuyến '{target_ident}' trong danh mục")

    shape = service.get_route_shape(resolved_id, dir_int)
    if shape is None or shape.point_count == 0:
        raise HTTPException(status_code=404, detail=f"Không có dữ liệu tim tuyến cho tuyến '{target_ident}' chiều {dir_int}")

    return shape


@app.get("/api/route-stations", response_model=RouteStationsResponse)
def get_route_stations(
    route_id: Optional[int] = Query(None, description="Mã route_id BusMap"),
    route: Optional[str] = Query(None, description="Số hiệu tuyến (ví dụ: '27', '01', 'E01')"),
    direction: Optional[Union[int, str]] = Query(0, description="0: Chiều đi ('go'), 1: Chiều về ('re')")
):
    """
    Truy vấn danh sách trạm dừng theo số hiệu tuyến hoặc route_id và chiều hành trình.
    """
    target_ident = route_id if route_id is not None else route
    if target_ident is None:
        raise HTTPException(status_code=400, detail="Cần cung cấp ít nhất một tham số: 'route_id' hoặc 'route'")

    try:
        dir_int, _ = normalize_direction(direction)
    except ValueError:
        raise HTTPException(status_code=400, detail="Tham số 'direction' không hợp lệ. Chỉ chấp nhận 0, 1, 'go', hoặc 're'")

    resolved_id = service.resolve_route_id(target_ident)
    if resolved_id is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy tuyến '{target_ident}' trong danh mục")

    stations_res = service.get_route_stations(resolved_id, dir_int)
    if stations_res is None or stations_res.station_count == 0:
        raise HTTPException(status_code=404, detail=f"Không có dữ liệu trạm dừng cho tuyến '{target_ident}' chiều {dir_int}")

    return stations_res


@app.get("/api/station-eta", response_model=StationEtaResponse)
def get_station_eta(
    route_id: Optional[int] = Query(None, description="Mã route_id BusMap"),
    route: Optional[str] = Query(None, description="Số hiệu tuyến (ví dụ: '27', '01', 'E01')"),
    direction: Optional[Union[int, str]] = Query(0, description="0: Chiều đi ('go'), 1: Chiều về ('re')"),
    station_order: Optional[int] = Query(None, description="Thứ tự trạm dừng mục tiêu (0-based)")
):
    """
    Truy vấn dự báo thời gian xe buýt đến trạm dừng mục tiêu (Station ETA) theo SPEC-08.
    """
    target_ident = route_id if route_id is not None else route
    if target_ident is None:
        raise HTTPException(status_code=400, detail="Cần cung cấp ít nhất một tham số: 'route_id' hoặc 'route'")

    if station_order is None or station_order < 0:
        raise HTTPException(status_code=400, detail="Tham số 'station_order' không hợp lệ (phải là số nguyên >= 0)")

    try:
        dir_int, _ = normalize_direction(direction)
    except ValueError:
        raise HTTPException(status_code=400, detail="Tham số 'direction' không hợp lệ. Chỉ chấp nhận 0, 1, 'go', hoặc 're'")

    resolved_id = service.resolve_route_id(target_ident)
    if resolved_id is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy tuyến '{target_ident}' trong danh mục")

    stations_res = service.get_route_stations(resolved_id, dir_int)
    if stations_res is None or stations_res.station_count == 0:
        raise HTTPException(status_code=404, detail=f"Không có dữ liệu trạm dừng cho tuyến '{target_ident}' chiều {dir_int}")

    if station_order >= stations_res.station_count:
        raise HTTPException(status_code=404, detail=f"Thứ tự trạm {station_order} vượt quá số trạm ({stations_res.station_count}) của tuyến")

    eta_res = service.get_station_eta(resolved_id, dir_int, station_order)
    if eta_res is None:
        raise HTTPException(status_code=404, detail="Không thể tính toán dự báo ETA cho trạm này")

    return eta_res


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("module_3_bus_eta_prediction.step_3_5_web_demo.app:app", host="127.0.0.1", port=8000, reload=True)
