"""
Module 3 - Step 3.5: API Contract Definition (Contract-First Paradigm).
Defines standard Pydantic v2 models and OpenAPI schema structures.
All backend endpoints and frontend data contracts MUST conform 100% to this file.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class RouteItem(BaseModel):
    """Metadata for a single bus route in the catalog."""
    route_code: str = Field(..., description="Mã tuyến (ví dụ: '02', '32', 'E01')")
    route_id: int = Field(..., description="ID định danh số của tuyến trong CSDL BusMap")
    route_name: str = Field(..., description="Tên tuyến (ví dụ: 'Bác Cổ - BX Yên Nghĩa')")
    has_go_direction: bool = Field(True, description="Tuyến có dữ liệu chiều đi")
    has_re_direction: bool = Field(True, description="Tuyến có dữ liệu chiều về")


class StationGeometryItem(BaseModel):
    """Geographic and spatial attributes of a bus station along a corridor."""
    station_order: int = Field(..., description="Thứ tự trạm dừng dọc hành lang (0..N-1)")
    station_id: int = Field(..., description="Mã ID chuẩn của trạm dừng trong CSDL BusMap")
    station_name: str = Field(..., description="Tên định danh của trạm dừng")
    lat: float = Field(..., description="Vĩ độ WGS84")
    lon: float = Field(..., description="Kinh độ WGS84")
    cum_distance_m: float = Field(..., description="Khoảng cách tích lũy dọc tim đường (Frenet s_m) tính từ bến xuất phát")


class GeoJsonLineString(BaseModel):
    """GeoJSON LineString geometry representing route corridor polyline."""
    type: str = Field("LineString", description="Loại đối tượng GeoJSON")
    coordinates: List[List[float]] = Field(..., description="Danh sách tọa độ [[lon, lat], ...] theo chuẩn GeoJSON")


class RouteGeometryResponse(BaseModel):
    """Full corridor geometry and ordered station list for a specific route and direction."""
    route_code: str = Field(..., description="Mã tuyến")
    direction: str = Field(..., description="Chiều di chuyển: 'go' (chiều đi) hoặc 're' (chiều về)")
    route_length_m: float = Field(..., description="Tổng chiều dài lộ trình hành lang (mét)")
    shape_geojson: GeoJsonLineString = Field(..., description="GeoJSON LineString tim đường")
    stations: List[StationGeometryItem] = Field(..., description="Danh sách các trạm dừng được sắp xếp theo station_order")


class PredictionItem(BaseModel):
    """ETA prediction for a specific upcoming station."""
    target_station_order: int = Field(..., description="Thứ tự trạm đích")
    target_station_id: int = Field(..., description="Mã ID trạm đích")
    target_station_name: str = Field(..., description="Tên trạm đích")
    target_distance_m: float = Field(0.0, description="Khoảng cách trạm đích tính từ bến xuất phát (mét)")
    eta_seconds: float = Field(..., description="Thời gian dự báo xe đến trạm (giây)")
    eta_minutes: float = Field(..., description="Thời gian dự báo xe đến trạm (phút)")
    baseline_p10_sec: Optional[float] = Field(None, description="Thời gian chạy theo phân vị an toàn P10 (giây)")
    baseline_p50_sec: Optional[float] = Field(None, description="Thời gian chạy trung vị Baseline P50 (giây)")
    baseline_p90_sec: Optional[float] = Field(None, description="Thời gian chạy theo phân vị trễ P90 (giây)")
    safe_arrival_time: str = Field(..., description="Mốc giờ khuyến nghị có mặt tại trạm (HH:MM) theo phân vị an toàn P10")
    expected_arrival_time: str = Field(..., description="Mốc giờ đến trạm dự kiến (HH:MM)")
    safe_window: str = Field(..., description="Cửa sổ thời gian an toàn [P10, P90] dạng chuỗi 'HH:MM – HH:MM'")


class LiveBusItem(BaseModel):
    """Real-time operational status and telemetry of an individual bus on the corridor."""
    vehicle_id: str = Field(..., description="ID thiết bị viễn trắc GPS")
    plate: str = Field(..., description="Biển số xe (ví dụ: '29B-205.54')")
    status: str = Field(
        ...,
        description="Trạng thái vận hành: 'ACTIVE_IN_TRANSIT', 'AT_ORIGIN_TERMINAL', 'AT_DESTINATION_TERMINAL', 'DETOUR_OFF_CORRIDOR'",
    )
    lat: float = Field(..., description="Vĩ độ hiện tại WGS84")
    lon: float = Field(..., description="Kinh độ hiện tại WGS84")
    speed_kmh: float = Field(0.0, description="Vận tốc tức thời (km/h)")
    heading_deg: float = Field(0.0, description="Góc hướng di chuyển (độ, 0..360)")
    current_s_bus_m: Optional[float] = Field(None, description="Tọa độ dọc trục Frenet s (mét)")
    cross_track_m: Optional[float] = Field(None, description="Khoảng cách vuông góc tim đường d_perp (mét)")
    current_station_order: Optional[int] = Field(None, description="Thứ tự trạm dừng gần nhất vừa đi qua")
    current_station_name: Optional[str] = Field(None, description="Tên trạm dừng gần nhất vừa đi qua")
    message: Optional[str] = Field(None, description="Thông báo trạng thái (dành cho detour hoặc bến chờ)")
    telemetry_source: Optional[str] = Field("busmap_relay", description="Nguồn viễn trắc GPS: 'timbus_5s' hoặc 'busmap_relay'")
    predictions: List[PredictionItem] = Field(default_factory=list, description="Danh sách dự báo ETA đến các trạm kế tiếp")


class LiveEtaResponse(BaseModel):
    """Snapshot of real-time corridor operations and passenger ETA predictions."""
    route_code: str = Field(..., description="Mã tuyến xe buýt")
    direction: str = Field(..., description="Chiều di chuyển ('go' hoặc 're')")
    timestamp: str = Field(..., description="Thời điểm tạo snapshot theo định dạng ISO-8601")
    cached: bool = Field(False, description="Cờ đánh dấu dữ liệu được phục vụ từ TTL Cache")
    total_buses: int = Field(..., description="Tổng số xe ghi nhận trên tuyến")
    active_in_transit_count: int = Field(..., description="Số xe đang lăn bánh tích cực trên hành lang")
    traffic_condition: str = Field(..., description="Đánh giá tình trạng lưu thông: 'Thông thoáng', 'Ùn ứ chậm', 'Kẹt xe cục bộ'")
    buses: List[LiveBusItem] = Field(..., description="Danh sách toàn bộ xe và dự báo ETA tương ứng")


class HealthResponse(BaseModel):
    """Service health and operational memory telemetry."""
    status: str = Field("healthy", description="Trạng thái dịch vụ ('healthy')")
    service_initialized: bool = Field(..., description="Trạng thái nạp mô hình và CSDL vào RAM")
    uptime_seconds: float = Field(..., description="Thời gian máy chủ đã chạy (giây)")
    active_cache_entries: int = Field(..., description="Số lượng mục lưu tạm trong TTL Cache")
    memory_rss_mb: float = Field(..., description="Dung lượng bộ nhớ RAM (Resident Set Size) đang sử dụng (MB)")
