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
    busmap_updated_at: Optional[str] = Field(
        default=None, description="Mốc thời gian thiết bị gốc từ BusMap (ISO 8601)"
    )
    # Internal projection result shared by speed, features and station filtering.
    matched_projection: Optional[Tuple[float,float,int]] = Field(default=None,exclude=True)
    projection_checked: bool = Field(default=False,exclude=True)
    projection_status: str = Field(default='uninitialized',exclude=True)
    projection_generation: int = Field(default=0,exclude=True)
    current_station_id: Optional[int] = Field(default=None, description="ID trạm hiện tại")
    next_station_id: Optional[int] = Field(default=None, description="ID trạm kế tiếp")
    telemetry_source: Literal["busmap", "timbus"] = Field(
        default="busmap", description="Nguồn tọa độ trực tiếp: busmap hoặc timbus"
    )
    raw_speed_kmh: Optional[float] = Field(
        default=None, description="Vận tốc tức thời hộp đen gốc trước khi tổng quát hóa (km/h)"
    )
    speed_window_sec: Optional[float] = Field(
        default=None, description="Độ dài cửa sổ delta_t (giây) dùng ước lượng vận tốc vĩ mô"
    )


class RouteItemDTO(BaseModel):
    """Tuyến xe buýt trong danh mục."""

    route_id: int = Field(..., description="Mã tuyến ID BusMap")
    route_no: str = Field(..., description="Số hiệu tuyến (ví dụ: 27, 01, E01)")
    name: str = Field(..., description="Tên tuyến chi tiết (Đầu bến - Cuối bến)")
    timbus_supported: bool = Field(False, description="Tuyến có hỗ trợ đồng bộ TimBus 5s")


class RouteIncidentDTO(BaseModel):
    """Sự cố giao thông live từ TomTom (đồng bộ qua Hugging Face) đã chiếu lên hành lang tuyến."""

    incident_id: str = Field(default="", description="ID sự cố TomTom")
    description: str = Field(default="", description="Mô tả sự cố")
    icon_category: int = Field(default=0, description="Loại sự cố TomTom")
    magnitude_of_delay: int = Field(default=0, description="Mức độ ùn tắc (0..4)")
    delay_seconds: float = Field(default=0.0, description="Thời gian trễ ước tính (giây)")
    length_meters: float = Field(default=0.0, description="Chiều dài đoạn sự cố (mét)")
    s_min_m: float = Field(default=0.0, description="Lý trình bắt đầu trên tuyến (m)")
    s_max_m: float = Field(default=0.0, description="Lý trình kết thúc trên tuyến (m)")


class RouteLiveResponse(BaseModel):
    """Phản hồi vị trí xe trực tiếp theo tuyến/chiều."""

    route_id: int
    direction: int
    count: int
    timestamp: str
    timbus_supported: bool = Field(default=False, description="Tuyến/chiều có hỗ trợ tăng tốc TimBus 5s")
    poll_interval_sec: int = Field(default=15, description="Chu kỳ làm mới bản đồ khuyến nghị (5s hoặc 15s)")
    upstream_status: Literal["ok", "empty", "upstream_error"] = Field(
        default="ok", description="Trạng thái truy vấn BusMap upstream"
    )
    upstream_error: Optional[str] = Field(default=None, description="Chi tiết lỗi BusMap upstream nếu có")
    timbus_status: Literal["ok", "partial_error", "upstream_error", "unsupported"] = Field(
        default="unsupported", description="Trạng thái đồng bộ TimBus upstream"
    )
    timbus_error: Optional[str] = Field(default=None, description="Chi tiết lỗi TimBus upstream nếu có")
    incidents: List[RouteIncidentDTO] = Field(default_factory=list, description="Sự cố giao thông live trên tuyến")
    incidents_fetched_at: Optional[str] = Field(default=None, description="Mốc thời gian TomTom snapshot gần nhất")
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
    p50_seconds: float = Field(..., description="Ước tính ETA trung tâm (tên P50); cần kiểm chứng calibration theo dữ liệu")
    p90_seconds: float = Field(..., description="Phân vị ETA P90 (chậm nhất) tính bằng giây")
    p10_minutes: int = Field(default=0, description="Phút an toàn P10: ceil(p10_seconds / 60.0)")
    p90_minutes: int = Field(default=0, description="Phút an toàn P90: ceil(p90_seconds / 60.0)")
    conservative_eta_seconds: float = Field(..., description="Thời gian ETA P50+buffer tham chiếu (giây)")
    buffer_seconds: float = Field(..., description="Độ đệm an toàn thực delta_buffer (giây), không hardcode 0")
    display_eta_minutes: int = Field(default=0, description="Số phút nguyên lượng tử hóa trần M = ceil(p50_seconds/60)")
    optimistic_eta_seconds: float = Field(default=0.0, description="Ước tính lạc quan chống trễ: max(0, p50_seconds - buffer_seconds)")
    optimistic_minutes: int = Field(default=0, description="Phút nguyên ước tính lạc quan: ceil(optimistic_eta_seconds/60)")
    optimistic_display_text: str = Field(default="", description="Chuỗi nhãn lạc quan UI")
    optimistic_arrival_time: str = Field(default="", description="Mốc thời gian đến lạc quan (now + optimistic_eta_seconds, HH:MM:SS)")
    is_delayed: bool = Field(default=False, description="Cờ cảnh báo trễ: delta_delay >= REALTIME_DELAY_ALERT_SEC")
    delay_seconds: float = Field(default=0.0, description="Độ trễ thực đo so với baseline (giây)")
    recommended_arrival_time: str = Field(..., description="Giờ khuyến nghị có mặt tại trạm theo mốc lạc quan (HH:MM:SS)")


class ApproachingBusDTO(BaseModel):
    """Xe đang tiếp cận trạm mục tiêu."""

    vehicle_id: int = Field(..., description="ID xe duy nhất từ BusMap")
    plate: str = Field(..., description="Biển số xe")
    distance_to_station_m: float = Field(..., description="Khoảng cách lý trình tới trạm đích (m)")
    stops_remaining: int = Field(..., description="Số trạm dừng còn lại trước khi tới đích")
    eta_seconds: float = Field(..., description="Thời gian ETA dự kiến P50/eta_core (bỏ +delta_buffer, giây)")
    eta_minutes: int = Field(..., description="Phút nguyên lượng tử hóa M = ceil(eta_seconds/60)")
    eta_minutes_precise: float = Field(..., description="Phút thập phân (1 chữ số) — chỉ hiển thị song song ở demo")
    display_eta_minutes: int = Field(default=0, description="Số phút nguyên lượng tử hóa trần hiển thị")
    display_text: str = Field(default="", description="Chuỗi nhãn hiển thị UI: '0 phút' / '~1 phút' / 'M phút'")
    optimistic_eta_seconds: float = Field(default=0.0, description="Ước tính lạc quan chống trễ max(0, p50 - delta_buffer) (giây)")
    optimistic_display_text: str = Field(default="", description="Nhãn thời gian còn lại lạc quan")
    optimistic_arrival_time: str = Field(default="", description="Mốc thời gian đến lạc quan theo giờ Hà Nội HH:MM:SS (now + optimistic_eta_seconds)")
    prediction_source: Literal["ml_calibrated", "baseline_fallback"] = Field(
        ..., description="Nguồn ETA runtime: ml_calibrated hoặc baseline_fallback"
    )
    fallback_reason: Literal["ok", "cold_start_causal", "model_unavailable", "unknown_route", "predict_error"] = Field(
        default="ok", description="Lý do dùng baseline fallback (hoặc 'ok' nếu dùng ML)"
    )
    safe_window: SafeWindowDTO = Field(..., description="Cửa sổ an toàn bất đối xứng [P10, P90] và thông số đệm")
    speed_kmh: float = Field(..., description="Vận tốc dùng cho ETA sau làm mượt nếu có (km/h)")
    traffic_status: str = Field(default="BINH_THUONG", description="Điều kiện giao thông: THONG_THOANG, BINH_THUONG, UN_TAC")
    ping_time: Optional[str] = Field(default=None, description="Mốc thời gian GPS dùng tính ETA (ISO 8601)")
    busmap_updated_at: Optional[str] = Field(
        default=None, description="Mốc thời gian thiết bị gốc từ BusMap (ISO 8601)"
    )
    ping_age_seconds: Optional[float] = Field(default=0.0, description="Độ trôi tuổi gói tin GPS tính bằng giây")
    arrival_time_epoch: Optional[float] = Field(default=None, description="Thời điểm xe cập bến dự kiến P50 (Unix epoch seconds)")
    estimated_arrival_time: str = Field(
        default="", description="Thời điểm xe dự kiến đến trạm theo giờ Hà Nội HH:MM:SS (time now + P50/eta_core)"
    )
    telemetry_source: Literal["busmap", "timbus"] = Field(
        default="busmap", description="Nguồn tọa độ dùng để dự báo ETA: busmap hoặc timbus"
    )
    raw_speed_kmh: Optional[float] = Field(
        default=None, description="Vận tốc tức thời hộp đen gốc trước tổng quát hóa (km/h)"
    )
    speed_window_sec: Optional[float] = Field(
        default=None, description="Cửa sổ delta_t (giây) ước lượng vận tốc vĩ mô"
    )


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
    timbus_supported: bool = Field(default=False, description="Tuyến/chiều có hỗ trợ tăng tốc TimBus 5s")
    poll_interval_sec: int = Field(default=15, description="Chu kỳ làm mới khuyến nghị (5s hoặc 15s)")
    upstream_status: Literal["ok", "empty", "upstream_error"] = Field(
        default="ok", description="Trạng thái truy vấn BusMap upstream"
    )
    upstream_error: Optional[str] = Field(default=None, description="Chi tiết lỗi BusMap upstream nếu có")
    timbus_status: Literal["ok", "partial_error", "upstream_error", "unsupported"] = Field(
        default="unsupported", description="Trạng thái đồng bộ TimBus upstream"
    )
    timbus_error: Optional[str] = Field(default=None, description="Chi tiết lỗi TimBus upstream nếu có")
    fallback_reason: Optional[str] = Field(
        default=None, description="Lý do fallback chính nếu tuyến đang dùng baseline"
    )
    incidents: List[RouteIncidentDTO] = Field(default_factory=list, description="Sự cố giao thông live trên tuyến")
    incidents_fetched_at: Optional[str] = Field(default=None, description="Mốc thời gian TomTom snapshot gần nhất")


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
