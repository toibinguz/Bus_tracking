"""
Step 3.4 — Hợp đồng DTO công khai (public API schema) cho tầng ETA serving.
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/dto.py

Chỉ định nghĩa schema (Pydantic). Không chứa logic nghiệp vụ/IO.
Đã sửa các trường zombie so với `busmap_service.py` cũ:
  - BusVehicleDTO: bỏ `lon` (alias trùng `lng`), bỏ `distance_to_next_m` (luôn None).
  - SafeWindowDTO: `conservative_eta_seconds`/`buffer_seconds`/`is_delayed`/`delay_seconds` mang giá trị thực.
  - ApproachingBusDTO: `eta_minutes:int` (lượng tử hóa) + `eta_minutes_precise:float` (hiển thị song song).
"""

from typing import Literal, Optional, List, Tuple, Union

from pydantic import BaseModel, Field


class BusVehicleDTO(BaseModel):
    """Xe buýt trực tiếp từ BusMap (đã chuẩn hóa)."""

    id: int = Field(..., description="ID xe duy nhất từ BusMap")
    plate: str = Field(..., description="Biển số xe (ví dụ: 29B-400.44)")
    route_id: int = Field(..., description="Mã định danh tuyến xe buýt")
    direction: int = Field(..., description="0: Chiều đi ('go'), 1: Chiều về ('re')")
    lat: float = Field(..., description="Vĩ độ WGS84")
    lng: float = Field(..., description="Kinh độ WGS84")
    deg: float = Field(default=0.0, description="Góc xoay theo hướng di chuyển (0 - 360 độ)")
    speed_kmh: float = Field(default=0.0, description="Vận tốc hiện tại (km/h)")
    updated_at: str = Field(..., description="Mốc thời gian cập nhật của xe (ISO 8601)")
    current_station_id: Optional[int] = Field(default=None, description="ID trạm hiện tại")
    next_station_id: Optional[int] = Field(default=None, description="ID trạm kế tiếp")


class RouteItemDTO(BaseModel):
    """Tuyến xe buýt trong danh mục."""

    route_id: int = Field(..., description="Mã tuyến ID BusMap")
    route_no: str = Field(..., description="Số hiệu tuyến (ví dụ: 27, 01, E01)")
    name: str = Field(..., description="Tên tuyến chi tiết (Đầu bến - Cuối bến)")


class RouteLiveResponse(BaseModel):
    """Phản hồi vị trí xe trực tiếp theo tuyến/chiều."""

    route_id: int
    direction: int
    count: int
    timestamp: str
    vehicles: List[BusVehicleDTO]


class StationItemDTO(BaseModel):
    """Trạm dừng trong lý trình tuyến."""

    station_order: int = Field(..., description="Thứ tự trạm từ đầu bến (0-based)")
    station_id: int = Field(..., description="ID trạm dừng gốc")
    station_name: str = Field(..., description="Tên trạm dừng")
    address: Optional[str] = Field(default="", description="Địa chỉ trạm dừng")
    lat: float = Field(..., description="Vĩ độ WGS84")
    lon: float = Field(..., description="Kinh độ WGS84")
    cum_distance_m: float = Field(..., description="Lý trình lũy kế từ trạm xuất phát (mét)")


class RouteStationsResponse(BaseModel):
    """Danh sách trạm dừng của tuyến theo chiều."""

    route_id: int
    route_code: str
    direction: int
    direction_str: str
    station_count: int
    stations: List[StationItemDTO]


class RouteShapeResponse(BaseModel):
    """Tim tuyến (shape) của tuyến theo chiều."""

    route_id: int
    route_code: str
    direction: int
    direction_str: str
    point_count: int
    total_distance_m: float
    coordinates: List[List[float]] = Field(..., description="Danh sách [lat, lon]")


class SafeWindowDTO(BaseModel):
    """Cửa sổ an toàn bất đối xứng [P10, P90] kèm thông số độ đệm thực."""

    p10_seconds: float = Field(..., description="Phân vị ETA P10 (nhanh nhất) tính bằng giây")
    p50_seconds: float = Field(..., description="Phân vị ETA P50 (trung vị, ML core) tính bằng giây")
    p90_seconds: float = Field(..., description="Phân vị ETA P90 (chậm nhất) tính bằng giây")
    p10_minutes: int = Field(default=0, description="Phút an toàn P10: ceil(p10_seconds / 60.0)")
    p90_minutes: int = Field(default=0, description="Phút an toàn P90: ceil(p90_seconds / 60.0)")
    conservative_eta_seconds: float = Field(..., description="Thời gian ETA bảo vệ hành khách (giây)")
    buffer_seconds: float = Field(..., description="Độ đệm an toàn thực delta_buffer (giây), không hardcode 0")
    display_eta_minutes: int = Field(default=0, description="Số phút nguyên lượng tử hóa trần M = ceil(conservative_eta_seconds/60)")
    is_delayed: bool = Field(default=False, description="Cờ cảnh báo trễ: delta_delay >= REALTIME_DELAY_ALERT_SEC")
    delay_seconds: float = Field(default=0.0, description="Độ trễ thực đo so với baseline (giây)")
    recommended_arrival_time: str = Field(..., description="Giờ khuyến nghị có mặt tại trạm (HH:MM:SS)")


class ApproachingBusDTO(BaseModel):
    """Xe đang tiếp cận trạm mục tiêu."""

    vehicle_id: int = Field(..., description="ID xe duy nhất từ BusMap")
    plate: str = Field(..., description="Biển số xe")
    distance_to_station_m: float = Field(..., description="Khoảng cách lý trình tới trạm đích (m)")
    stops_remaining: int = Field(..., description="Số trạm dừng còn lại trước khi tới đích")
    eta_seconds: float = Field(..., description="Thời gian ETA hiển thị (conservative, giây)")
    eta_minutes: int = Field(..., description="Phút nguyên lượng tử hóa M = ceil(conservative_eta_seconds/60)")
    eta_minutes_precise: float = Field(..., description="Phút thập phân (1 chữ số) — chỉ hiển thị song song ở demo")
    display_eta_minutes: int = Field(default=0, description="Số phút nguyên lượng tử hóa trần hiển thị")
    display_text: str = Field(default="", description="Chuỗi nhãn hiển thị UI: '0 phút' / '~1 phút' / 'M phút'")
    prediction_source: Literal["ml_calibrated", "baseline_fallback"] = Field(
        ..., description="Nguồn ETA runtime: ml_calibrated hoặc baseline_fallback"
    )
    safe_window: SafeWindowDTO = Field(..., description="Cửa sổ an toàn bất đối xứng [P10, P90] và thông số đệm")
    speed_kmh: float = Field(..., description="Vận tốc đo tức thời (km/h)")
    traffic_status: str = Field(default="BINH_THUONG", description="Điều kiện giao thông: THONG_THOANG, BINH_THUONG, UN_TAC")
    ping_time: Optional[str] = Field(default=None, description="Mốc thời gian GPS thực tế của xe (ISO 8601)")
    ping_age_seconds: Optional[float] = Field(default=0.0, description="Độ trôi tuổi gói tin GPS tính bằng giây")
    arrival_time_epoch: Optional[float] = Field(default=None, description="Thời điểm xe cập bến dự kiến (Unix epoch seconds)")


class StationEtaResponse(BaseModel):
    """Phản hồi dự báo ETA các xe đang tiếp cận trạm mục tiêu."""

    route_id: int = Field(..., description="Mã route_id BusMap")
    route_code: str = Field(..., description="Số hiệu tuyến")
    direction: int = Field(..., description="0: Chiều đi, 1: Chiều về")
    direction_str: str = Field(..., description="'go' hoặc 're'")
    target_station: StationItemDTO = Field(..., description="Thông tin trạm dừng mục tiêu")
    query_time: str = Field(..., description="Mốc thời gian truy vấn ISO 8601")
    day_type: int = Field(..., description="Loại ngày: 0 (Ngày thường), 1 (Thứ 7), 2 (Chủ nhật)")
    hour_slot: int = Field(..., description="Khung giờ hiện tại (5..21)")
    traffic_condition: str = Field(..., description="Điều kiện giao thông: THONG_THOANG, BINH_THUONG, UN_TAC")
    approaching_count: int = Field(..., description="Số lượng xe đang tiếp cận trạm")
    buses: List[ApproachingBusDTO] = Field(default_factory=list, description="Danh sách các xe đang chạy về trạm")
    message: str = Field(..., description="Thông điệp hiển thị cho người dùng")


def normalize_direction(direction_val: Union[int, str, None]) -> Tuple[int, str]:
    """
    Chuẩn hóa tham số direction thành cặp (dir_int, dir_str):
    0, '0', 'go' -> (0, 'go')
    1, '1', 're' -> (1, 're')
    Khác -> raise ValueError("Tham số 'direction' không hợp lệ. Chỉ chấp nhận 0, 1, 'go', hoặc 're'")
    """
    if direction_val is None:
        return 0, "go"
    if isinstance(direction_val, bool):
        raise ValueError("Tham số 'direction' không hợp lệ. Chỉ chấp nhận 0, 1, 'go', hoặc 're'")
    if isinstance(direction_val, int):
        if direction_val == 0:
            return 0, "go"
        elif direction_val == 1:
            return 1, "re"
        else:
            raise ValueError("Tham số 'direction' không hợp lệ. Chỉ chấp nhận 0, 1, 'go', hoặc 're'")
    s = str(direction_val).strip().lower()
    if s in ("0", "go"):
        return 0, "go"
    elif s in ("1", "re"):
        return 1, "re"
    else:
        raise ValueError("Tham số 'direction' không hợp lệ. Chỉ chấp nhận 0, 1, 'go', hoặc 're'")
