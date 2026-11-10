"""
BusMap Serving Service - Discrete Tracking Architecture (Simplicity First)
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/busmap_service.py

Provides clean, normalized real-time bus telemetry sourced 100% from BusMap HTTPS API.
Strictly 0% TimBus, 0% XOR cipher, 0% raw TCP socket.
"""

from datetime import datetime, timezone, timedelta
import time
from typing import Optional, List, Dict, Union, Any, Tuple
from pathlib import Path
import sqlite3
import json
import logging
import math
import numpy as np
from pydantic import BaseModel, Field

# Import raw upstream BusMap fetcher
from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import (
    fetch_route_buses_live
)
from config.system_config import (
    HANOI_BBOX,
    LAT_DEGREE_TO_METERS,
    LON_DEGREE_TO_METERS,
    BUS_FALLBACK_CORRIDOR_MPS,
    CORRIDOR_DEVIATION_METERS
)

logger = logging.getLogger(__name__)

HANOI_TZ = timezone(timedelta(hours=7))


class BusVehicleDTO(BaseModel):
    id: int = Field(..., description="ID xe duy nhất từ BusMap")
    plate: str = Field(..., description="Biển số xe (ví dụ: 29B-400.44)")
    route_id: int = Field(..., description="Mã định danh tuyến xe buýt")
    direction: int = Field(..., description="0: Chiều về, 1: Chiều đi")
    lat: float = Field(..., description="Vĩ độ WGS84")
    lng: float = Field(..., description="Kinh độ WGS84")
    lon: float = Field(..., description="Bí danh kinh độ WGS84")
    deg: float = Field(default=0.0, description="Góc xoay theo hướng di chuyển (0 - 360 độ)")
    speed_kmh: float = Field(default=0.0, description="Vận tốc hiện tại (km/h)")
    updated_at: str = Field(..., description="Mốc thời gian cập nhật của xe (ISO 8601)")
    distance_to_next_m: Optional[float] = Field(default=None, description="Khoảng cách ước tính tới trạm kế (m)")
    current_station_id: Optional[int] = Field(default=None, description="ID trạm hiện tại")
    next_station_id: Optional[int] = Field(default=None, description="ID trạm kế tiếp")


class RouteItemDTO(BaseModel):
    route_id: int = Field(..., description="Mã tuyến ID BusMap")
    route_no: str = Field(..., description="Số hiệu tuyến (ví dụ: 27, 01, E01)")
    name: str = Field(..., description="Tên tuyến chi tiết (Đầu bến - Cuối bến)")


class RouteLiveResponse(BaseModel):
    route_id: int
    direction: int
    count: int
    timestamp: str
    vehicles: List[BusVehicleDTO]


class StationItemDTO(BaseModel):
    station_order: int = Field(..., description="Thứ tự trạm từ đầu bến (0-based)")
    station_id: int = Field(..., description="ID trạm dừng gốc")
    station_name: str = Field(..., description="Tên trạm dừng")
    address: Optional[str] = Field(default="", description="Địa chỉ trạm dừng")
    lat: float = Field(..., description="Vĩ độ WGS84")
    lon: float = Field(..., description="Kinh độ WGS84")
    cum_distance_m: float = Field(..., description="Lý trình lũy kế từ trạm xuất phát (mét)")


class RouteStationsResponse(BaseModel):
    route_id: int
    route_code: str
    direction: int
    direction_str: str
    station_count: int
    stations: List[StationItemDTO]


class RouteShapeResponse(BaseModel):
    route_id: int
    route_code: str
    direction: int
    direction_str: str
    point_count: int
    total_distance_m: float
    coordinates: List[List[float]] = Field(..., description="Danh sách [lat, lon]")


class SafeWindowDTO(BaseModel):
    p10_seconds: float = Field(..., description="Phân vị ETA P10 (nhanh nhất) tính bằng giây")
    p50_seconds: float = Field(..., description="Phân vị ETA P50 (trung vị) tính bằng giây")
    p90_seconds: float = Field(..., description="Phân vị ETA P90 (chậm nhất) tính bằng giây")
    p10_minutes: int = Field(default=0, description="Phút an toàn P10: ceil(p10_seconds / 60.0)")
    p90_minutes: int = Field(default=0, description="Phút an toàn P90: ceil(p90_seconds / 60.0)")
    display_eta_minutes: int = Field(default=0, description="Số phút nguyên lượng tử hóa trần M = ceil(p50_seconds / 60.0)")
    conservative_eta_seconds: Optional[float] = Field(default=None, description="Thời gian ETA bảo vệ hành khách")
    buffer_seconds: Optional[float] = Field(default=0.0, description="Độ đệm an toàn")
    is_delayed: bool = Field(default=False, description="Cờ cảnh báo trễ/ùn ứ")
    delay_seconds: float = Field(default=0.0, description="Độ trễ đo được so với kỳ vọng baseline (giây)")
    recommended_arrival_time: str = Field(..., description="Giờ khuyến nghị có mặt tại trạm (HH:MM:SS)")


class ApproachingBusDTO(BaseModel):
    vehicle_id: int = Field(..., description="ID xe duy nhất từ BusMap")
    plate: str = Field(..., description="Biển số xe")
    distance_to_station_m: float = Field(..., description="Khoảng cách lý trình tới trạm đích (m)")
    stops_remaining: int = Field(..., description="Số trạm dừng còn lại trước khi tới đích")
    eta_seconds: float = Field(..., description="Thời gian ETA P50 tính bằng giây")
    eta_minutes: float = Field(..., description="Thời gian ETA P50 tính bằng phút (làm tròn 1 chữ số thập phân)")
    display_eta_minutes: int = Field(default=0, description="Số phút nguyên lượng tử hóa trần M = ceil(p50_seconds / 60.0)")
    display_text: str = Field(default="", description="Chuỗi nhãn hiển thị trực quan UI: 'M phút' hoặc '~1 phút'")
    safe_window: SafeWindowDTO = Field(..., description="Cửa sổ an toàn bất đối xứng [P10, P90] và thông số đệm")
    speed_kmh: float = Field(..., description="Vận tốc đo tức thời (km/h)")
    status: str = Field(default="IN_TRANSIT", description="Trạng thái: IN_TRANSIT")
    traffic_status: str = Field(default="BINH_THUONG", description="Điều kiện giao thông: THONG_THOANG, BINH_THUONG, UN_TAC")
    ping_time: Optional[str] = Field(default=None, description="Mốc thời gian GPS thực tế của xe (ISO 8601)")
    ping_age_seconds: Optional[float] = Field(default=0.0, description="Độ trôi tuổi gói tin GPS tính bằng giây")
    arrival_time_epoch: Optional[float] = Field(default=None, description="Thời điểm xe cập bến dự kiến (Unix epoch seconds)")


class StationEtaResponse(BaseModel):
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


def _now_hanoi_iso() -> str:
    """Trả về thời gian hiện tại theo múi giờ Hà Nội (ISO 8601)."""
    return datetime.now(HANOI_TZ).isoformat()


def _parse_ping_epoch(ts_val: Any, default_epoch: float) -> Tuple[float, str]:
    """
    Parse timestamp viễn trắc GPS xe thành cặp (epoch_seconds, iso_string).
    Hỗ trợ ISO 8601 string, Unix epoch seconds/milliseconds, fallback an toàn về default_epoch.
    """
    if ts_val is None:
        dt = datetime.fromtimestamp(default_epoch, tz=HANOI_TZ)
        return default_epoch, dt.isoformat()

    if isinstance(ts_val, (int, float)):
        epoch = float(ts_val)
        if epoch > 1e11:  # milliseconds
            epoch /= 1000.0
        dt = datetime.fromtimestamp(epoch, tz=HANOI_TZ)
        return epoch, dt.isoformat()

    s = str(ts_val).strip()
    if not s:
        dt = datetime.fromtimestamp(default_epoch, tz=HANOI_TZ)
        return default_epoch, dt.isoformat()

    try:
        val = float(s)
        if val > 1e11:
            val /= 1000.0
        dt = datetime.fromtimestamp(val, tz=HANOI_TZ)
        return val, dt.isoformat()
    except ValueError:
        pass

    try:
        clean_s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HANOI_TZ)
        return dt.timestamp(), dt.isoformat()
    except Exception:
        pass

    dt = datetime.fromtimestamp(default_epoch, tz=HANOI_TZ)
    return default_epoch, dt.isoformat()


# In-memory short-lived cache for live telemetry to achieve SLA < 20ms and protect upstream BusMap
_live_vehicles_cache: Dict[Tuple[int, int], Tuple[float, RouteLiveResponse]] = {}
LIVE_CACHE_TTL_SEC: float = 8.0


def fetch_live_vehicles_for_route(route_id: int, direction: int = 0) -> RouteLiveResponse:
    """
    Truy vấn xe đang chạy trực tiếp từ BusMap API qua fetch_route_buses_live.
    Lọc các bản ghi không hợp lệ hoặc ngoài phạm vi địa lý Hà Nội.
    Trả về RouteLiveResponse chứa danh sách BusVehicleDTO.
    Áp dụng cache RAM ngắn hạn (TTL 8s) đáp ứng cam kết SLA Latency < 20ms.
    """
    if direction not in (0, 1):
        direction = 0

    cache_key = (route_id, direction)
    now_mono = time.monotonic()
    if cache_key in _live_vehicles_cache:
        cached_ts, cached_res = _live_vehicles_cache[cache_key]
        if now_mono - cached_ts < LIVE_CACHE_TTL_SEC:
            return cached_res

    raw_items = fetch_route_buses_live(route_id=route_id, direction=direction)
    timestamp_str = _now_hanoi_iso()
    now_fetch_epoch = datetime.now(HANOI_TZ).timestamp()

    if not raw_items or not isinstance(raw_items, list):
        empty_res = RouteLiveResponse(
            route_id=route_id,
            direction=direction,
            count=0,
            timestamp=timestamp_str,
            vehicles=[]
        )
        _live_vehicles_cache[cache_key] = (now_mono, empty_res)
        return empty_res

    seen_ids = set()
    cleaned_vehicles: List[BusVehicleDTO] = []

    for raw in raw_items:
        if not isinstance(raw, dict):
            continue

        vehicle_id = raw.get("Id")
        if not vehicle_id or not isinstance(vehicle_id, int) or vehicle_id <= 0:
            continue

        if vehicle_id in seen_ids:
            continue

        try:
            lat = float(raw.get("Lat", 0.0))
            lng = float(raw.get("Lng", 0.0))
        except (ValueError, TypeError):
            continue

        # Data Hygiene: Hà Nội Bounding Box check (from centralized system config)
        if not (HANOI_BBOX["lat_min"] <= lat <= HANOI_BBOX["lat_max"] and HANOI_BBOX["lon_min"] <= lng <= HANOI_BBOX["lon_max"]):
            continue

        plate = str(raw.get("VehicleNumber") or "").strip()
        if not plate:
            plate = f"BUS-{vehicle_id}"

        # Normalize degree
        try:
            deg = float(raw.get("Deg", 0.0)) % 360.0
            if deg < 0:
                deg += 360.0
        except (ValueError, TypeError):
            deg = 0.0

        # Normalize speed
        try:
            speed = max(0.0, float(raw.get("Speed", 0.0)))
        except (ValueError, TypeError):
            speed = 0.0

        raw_update_time = raw.get("lastUpdateTime")
        _, updated_at = _parse_ping_epoch(raw_update_time, now_fetch_epoch)

        current_station_id = raw.get("currentStationId")
        if isinstance(current_station_id, int) and current_station_id <= 0:
            current_station_id = None

        next_station_id = raw.get("nextStationId")
        if isinstance(next_station_id, int) and next_station_id <= 0:
            next_station_id = None

        dto = BusVehicleDTO(
            id=vehicle_id,
            plate=plate,
            route_id=route_id,
            direction=direction,
            lat=lat,
            lng=lng,
            lon=lng,
            deg=round(deg, 2),
            speed_kmh=round(speed, 1),
            updated_at=str(updated_at),
            distance_to_next_m=None,
            current_station_id=current_station_id,
            next_station_id=next_station_id
        )

        seen_ids.add(vehicle_id)
        cleaned_vehicles.append(dto)

    resp = RouteLiveResponse(
        route_id=route_id,
        direction=direction,
        count=len(cleaned_vehicles),
        timestamp=timestamp_str,
        vehicles=cleaned_vehicles
    )
    _live_vehicles_cache[cache_key] = (now_mono, resp)
    return resp


class BusMapServingService:
    """
    Service quản lý danh mục tuyến và phục vụ truy vấn vị trí xe trực tiếp từ BusMap.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        config_path: Optional[Union[str, Path]] = None
    ):
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.db_path = Path(db_path) if db_path else base_dir / "data" / "hanoi_bus_system.db"
        self.config_path = Path(config_path) if config_path else base_dir / "data" / "metadata" / "hust_cluster_config.json"

        self._routes_cache: List[RouteItemDTO] = []
        self._routes_by_id: Dict[int, RouteItemDTO] = {}
        self._routes_by_code: Dict[str, RouteItemDTO] = {}
        self._shape_cache: Dict[Tuple[int, str], RouteShapeResponse] = {}
        self._stations_cache: Dict[Tuple[int, str], RouteStationsResponse] = {}

        # Preloaded in-memory Baseline Travel Time Matrix
        # Key: (route_id, direction, from_station_order, to_station_order, day_type, hour_slot)
        # Value: (tt_p10_sec, tt_p50_sec, tt_p90_sec, tt_mean_sec, tt_std_sec)
        self._baseline_matrix: Dict[Tuple[int, int, int, int, int, int], Tuple[float, float, float, float, float]] = {}
        # Precomputed Cartesian projection models: (route_id, dir_str) -> projection_model
        self._shape_proj_cache: Dict[Tuple[int, str], Any] = {}

        self._load_catalog()
        self._load_baseline_matrix()

    def _load_baseline_matrix(self) -> None:
        """
        Nạp sẵn ma trận Baseline agg_segment_travel_times vào bộ nhớ RAM lúc khởi tạo service.
        Key: (route_id, direction, from_station_order, to_station_order, day_type, hour_slot)
        Value: (tt_p10_sec, tt_p50_sec, tt_p90_sec, tt_mean_sec, tt_std_sec)
        """
        if not self.db_path.exists():
            return

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT route_code, direction, from_station_order, to_station_order, "
                "day_type, hour_slot, tt_p10_sec, tt_p50_sec, tt_p90_sec, tt_mean_sec, tt_std_sec "
                "FROM agg_segment_travel_times"
            )
            rows = cursor.fetchall()
            conn.close()

            for r_code, dir_str, from_ord, to_ord, dt_v, hr_v, p10, p50, p90, mean_v, std_v in rows:
                r_id = self.resolve_route_id(r_code)
                dir_int = 0 if str(dir_str).strip().lower() == "go" else 1
                val = (float(p10), float(p50), float(p90), float(mean_v), float(std_v))

                if r_id is not None:
                    key_id = (r_id, dir_int, int(from_ord), int(to_ord), int(dt_v), int(hr_v))
                    self._baseline_matrix[key_id] = val

                code_clean = str(r_code).strip().upper()
                key_code = (code_clean, dir_int, int(from_ord), int(to_ord), int(dt_v), int(hr_v))
                self._baseline_matrix[key_code] = val
            logger.info("Loaded %d baseline cells into RAM cache", len(self._baseline_matrix))
        except Exception as e:
            logger.warning("Could not preload baseline travel time matrix: %s", e)

    def _load_catalog(self) -> None:
        """Tải danh mục tuyến từ SQLite canonical_route_master hoặc JSON config dự phòng."""
        loaded = False

        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT route_id, route_code, route_name FROM canonical_route_master ORDER BY route_id"
                )
                rows = cursor.fetchall()
                conn.close()

                if rows:
                    for row in rows:
                        r_id = int(row[0])
                        r_no = str(row[1]).strip()
                        r_name = str(row[2]).strip()
                        dto = RouteItemDTO(route_id=r_id, route_no=r_no, name=r_name)
                        self._routes_cache.append(dto)
                        self._routes_by_id[r_id] = dto
                        self._routes_by_code[r_no.upper()] = dto
                        self._routes_by_code[r_no.lstrip("0").upper()] = dto
                    loaded = True
                    logger.info("Loaded %d routes from SQLite canonical_route_master", len(self._routes_cache))
            except Exception as e:
                logger.warning("Failed loading routes from SQLite (%s), falling back to JSON: %s", self.db_path, e)

        if not loaded and self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                routes_raw = data.get("routes", [])
                for item in routes_raw:
                    r_id = int(item["route_id"])
                    r_no = str(item.get("route_no", str(r_id))).strip()
                    r_name = str(item.get("name", f"Tuyến {r_no}")).strip()
                    dto = RouteItemDTO(route_id=r_id, route_no=r_no, name=r_name)
                    if r_id not in self._routes_by_id:
                        self._routes_cache.append(dto)
                        self._routes_by_id[r_id] = dto
                        self._routes_by_code[r_no.upper()] = dto
                        self._routes_by_code[r_no.lstrip("0").upper()] = dto
                logger.info("Loaded %d routes from JSON %s", len(self._routes_cache), self.config_path)
            except Exception as e:
                logger.error("Failed loading routes from JSON %s: %s", self.config_path, e)

    def get_routes(self) -> List[RouteItemDTO]:
        """Trả về toàn bộ danh sách tuyến khả dụng."""
        return list(self._routes_cache)

    def resolve_route_id(self, route_ident: Union[str, int]) -> Optional[int]:
        """
        Phân giải mã số tuyến (string hoặc int) sang route_id nguyên bản BusMap.
        Ví dụ: '27' -> 27, 27 -> 27, '01' -> 1, 'E01' -> 101103.
        """
        if isinstance(route_ident, bool):
            return None

        if isinstance(route_ident, int):
            if route_ident in self._routes_by_id:
                return route_ident
            return None

        cleaned = str(route_ident).strip().upper()
        if not cleaned:
            return None

        # Check by code directly
        if cleaned in self._routes_by_code:
            return self._routes_by_code[cleaned].route_id

        # Try stripped leading zero
        stripped = cleaned.lstrip("0")
        if stripped in self._routes_by_code:
            return self._routes_by_code[stripped].route_id

        # Try integer parse
        try:
            parsed_id = int(cleaned)
            if parsed_id in self._routes_by_id:
                return parsed_id
            return None
        except ValueError:
            return None

    def get_route_shape(
        self,
        route_ident: Union[str, int],
        direction: Union[int, str] = 0
    ) -> Optional[RouteShapeResponse]:
        """
        Truy vấn chuỗi tọa độ tim tuyến từ canonical_shape_master theo route_id và direction.
        Sắp xếp theo point_order ASC.
        """
        dir_int, dir_str = normalize_direction(direction)
        route_id = self.resolve_route_id(route_ident)
        if route_id is None:
            return None

        cache_key = (route_id, dir_str)
        if cache_key in self._shape_cache:
            return self._shape_cache[cache_key]

        if not self.db_path.exists():
            return None

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT lat, lon, cum_distance_m FROM canonical_shape_master "
                "WHERE route_id = ? AND direction = ? ORDER BY point_order ASC",
                (route_id, dir_str)
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return None

            coords = [[float(r[0]), float(r[1])] for r in rows]
            total_dist = float(rows[-1][2]) if rows else 0.0
            route_code = self._routes_by_id[route_id].route_no if route_id in self._routes_by_id else str(route_id)

            resp = RouteShapeResponse(
                route_id=route_id,
                route_code=route_code,
                direction=dir_int,
                direction_str=dir_str,
                point_count=len(coords),
                total_distance_m=round(total_dist, 1),
                coordinates=coords
            )
            self._shape_cache[cache_key] = resp
            return resp
        except Exception as e:
            logger.error("Error querying route shape for route %s dir %s: %s", route_id, dir_str, e)
            return None

    def get_route_stations(
        self,
        route_ident: Union[str, int],
        direction: Union[int, str] = 0
    ) -> Optional[RouteStationsResponse]:
        """
        Truy vấn danh sách trạm dừng từ canonical_station_master theo route_id và direction.
        Sắp xếp theo station_order ASC.
        """
        dir_int, dir_str = normalize_direction(direction)
        route_id = self.resolve_route_id(route_ident)
        if route_id is None:
            return None

        cache_key = (route_id, dir_str)
        if cache_key in self._stations_cache:
            return self._stations_cache[cache_key]

        if not self.db_path.exists():
            return None

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT station_order, station_id, station_name, address, lat, lon, cum_distance_m "
                "FROM canonical_station_master "
                "WHERE route_id = ? AND direction = ? ORDER BY station_order ASC",
                (route_id, dir_str)
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return None

            route_code = self._routes_by_id[route_id].route_no if route_id in self._routes_by_id else str(route_id)
            station_items = [
                StationItemDTO(
                    station_order=int(r[0]),
                    station_id=int(r[1]),
                    station_name=str(r[2]),
                    address=str(r[3] or ""),
                    lat=float(r[4]),
                    lon=float(r[5]),
                    cum_distance_m=round(float(r[6]), 1)
                )
                for r in rows
            ]

            resp = RouteStationsResponse(
                route_id=route_id,
                route_code=route_code,
                direction=dir_int,
                direction_str=dir_str,
                station_count=len(station_items),
                stations=station_items
            )
            self._stations_cache[cache_key] = resp
            return resp
        except Exception as e:
            logger.error("Error querying route stations for route %s dir %s: %s", route_id, dir_str, e)
            return None

    def get_live_vehicles(
        self,
        route_code: Union[str, int],
        direction: int = 0
    ) -> RouteLiveResponse:
        """
        Lấy vị trí xe trực tiếp theo số hiệu tuyến hoặc route_id.
        """
        route_id = self.resolve_route_id(route_code)
        if route_id is None:
            return RouteLiveResponse(
                route_id=0,
                direction=direction if direction in (0, 1) else 0,
                count=0,
                timestamp=_now_hanoi_iso(),
                vehicles=[]
            )

        return fetch_live_vehicles_for_route(route_id=route_id, direction=direction)

    def _get_shape_projection_model(self, route_id: int, dir_str: str) -> Optional[Any]:
        """
        Khởi tạo hoặc lấy từ cache mô hình chiếu trực giao Cartesian cho tim tuyến (route_id, dir_str).
        """
        cache_key = (route_id, dir_str)
        if cache_key in self._shape_proj_cache:
            return self._shape_proj_cache[cache_key]

        if not self.db_path.exists():
            return None

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT lat, lon, cum_distance_m FROM canonical_shape_master "
                "WHERE route_id = ? AND direction = ? ORDER BY point_order ASC",
                (route_id, dir_str)
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows or len(rows) < 2:
                return None

            s_lats = np.array([float(r[0]) for r in rows], dtype=np.float64)
            s_lons = np.array([float(r[1]) for r in rows], dtype=np.float64)
            s_cums = np.array([float(r[2]) for r in rows], dtype=np.float64)

            mean_lat = float(np.mean(s_lats))
            kx = LON_DEGREE_TO_METERS * math.cos(math.radians(mean_lat))
            ky = LAT_DEGREE_TO_METERS

            x1 = s_lons[:-1] * kx
            y1 = s_lats[:-1] * ky
            x2 = s_lons[1:] * kx
            y2 = s_lats[1:] * ky

            dx = x2 - x1
            dy = y2 - y1
            seg_lens_sq = dx * dx + dy * dy
            safe_lens_sq = np.maximum(seg_lens_sq, 1e-6)
            seg_lens = np.sqrt(seg_lens_sq)
            cum_starts = s_cums[:-1]

            model = (kx, ky, x1, y1, dx, dy, safe_lens_sq, seg_lens, cum_starts, float(s_cums[-1]))
            self._shape_proj_cache[cache_key] = model
            return model
        except Exception as e:
            logger.error("Error building shape projection model for route %s dir %s: %s", route_id, dir_str, e)
            return None

    def _project_point(self, model: Any, lat: float, lon: float) -> Tuple[float, float]:
        """
        Chiếu trực giao 1D Frenet điểm GPS (lat, lon) lên tim tuyến.
        Trả về: (s_bus_m, d_perp_m)
        """
        kx, ky, x1, y1, dx, dy, safe_lens_sq, seg_lens, cum_starts, total_len = model
        px = lon * kx
        py = lat * ky

        p_dx1 = px - x1
        p_dy1 = py - y1
        t = np.clip((p_dx1 * dx + p_dy1 * dy) / safe_lens_sq, 0.0, 1.0)
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
        best_seg = int(np.argmin(dist_sq))

        min_d = float(math.sqrt(dist_sq[best_seg]))
        s_bus = float(cum_starts[best_seg] + t[best_seg] * seg_lens[best_seg])
        s_bus = max(0.0, min(total_len, s_bus))
        return s_bus, min_d

    def _lookup_baseline_tt(
        self,
        route_id: Union[int, str],
        dir_int: int,
        from_ord: int,
        to_ord: int,
        day_type: int,
        hour_slot: int,
        seg_len_m: float
    ) -> Tuple[float, float, float, float, float]:
        """
        Tra cứu ma trận thời gian di chuyển phân vị Baseline [P10, P50, P90, Mean, Std].
        Toàn bộ P10, P50, P90 được trích xuất trực tiếp từ 169.830 ô thực nghiệm của agg_segment_travel_times.
        Nếu phân đoạn thiếu dữ liệu Baseline, dùng vận tốc thiết kế fallback chuẩn BUS_FALLBACK_CORRIDOR_MPS = 5.0 (18.0 km/h).
        Bảo đảm bất biến vật lý và toán học: 0 <= P10 <= P50 <= P90.
        """
        key = (route_id, dir_int, from_ord, to_ord, day_type, hour_slot)
        if key in self._baseline_matrix:
            p10, p50, p90, mean_v, std_v = self._baseline_matrix[key]
            p10 = max(0.0, p10)
            p50 = max(p10, p50)
            p90 = max(p50, p90)
            return p10, p50, p90, mean_v, std_v

        # Thử phân giải route_id nếu khóa truy vấn là route_code hoặc ngược lại
        resolved_id = self.resolve_route_id(route_id)
        if resolved_id is not None and resolved_id != route_id:
            key_alt = (resolved_id, dir_int, from_ord, to_ord, day_type, hour_slot)
            if key_alt in self._baseline_matrix:
                p10, p50, p90, mean_v, std_v = self._baseline_matrix[key_alt]
                p10 = max(0.0, p10)
                p50 = max(p10, p50)
                p90 = max(p50, p90)
                return p10, p50, p90, mean_v, std_v

        # Fallback chuẩn vật lý khi khuyết thiếu Baseline:
        # Vận tốc thiết kế fallback chuẩn BUS_FALLBACK_CORRIDOR_MPS = 5.0 m/s (18.0 km/h)
        tt_fallback = max(0.0, seg_len_m / BUS_FALLBACK_CORRIDOR_MPS)
        return tt_fallback, tt_fallback, tt_fallback, tt_fallback, 0.0

    def get_station_eta(
        self,
        route_ident: Union[str, int],
        direction: Union[int, str] = 0,
        station_order: int = 0
    ) -> Optional[StationEtaResponse]:
        """
        Dự báo thời gian xe buýt đến trạm dừng (Station ETA) theo SPEC-08 và SPEC-09 Kịch bản 1.
        Tích hợp phân vị Baseline [P10, P50, P90] và cửa sổ an toàn bất đối xứng.
        """
        route_id = self.resolve_route_id(route_ident)
        if route_id is None:
            return None

        dir_int, dir_str = normalize_direction(direction)
        stations_resp = self.get_route_stations(route_id, dir_int)
        if stations_resp is None or not stations_resp.stations:
            return None

        n_stations = len(stations_resp.stations)
        if station_order < 0 or station_order >= n_stations:
            return None

        target_st = stations_resp.stations[station_order]
        s_target = target_st.cum_distance_m

        now_hn = datetime.now(HANOI_TZ)
        now_iso = now_hn.isoformat()
        day_type = 0 if now_hn.weekday() < 5 else (1 if now_hn.weekday() == 5 else 2)
        hour_slot = min(21, max(5, now_hn.hour))
        route_code = self._routes_by_id[route_id].route_no if route_id in self._routes_by_id else str(route_id)

        # Ca Biên 1: Trạm Đầu Bến (S0)
        if station_order == 0:
            return StationEtaResponse(
                route_id=route_id,
                route_code=route_code,
                direction=dir_int,
                direction_str=dir_str,
                target_station=target_st,
                query_time=now_iso,
                day_type=day_type,
                hour_slot=hour_slot,
                traffic_condition="THONG_THOANG",
                approaching_count=0,
                buses=[],
                message="Trạm đầu bến. Xe xuất bến theo nốt điều độ."
            )

        live_resp = fetch_live_vehicles_for_route(route_id=route_id, direction=dir_int)
        if live_resp.count == 0:
            return StationEtaResponse(
                route_id=route_id,
                route_code=route_code,
                direction=dir_int,
                direction_str=dir_str,
                target_station=target_st,
                query_time=now_iso,
                day_type=day_type,
                hour_slot=hour_slot,
                traffic_condition="THONG_THOANG",
                approaching_count=0,
                buses=[],
                message="Hiện chưa có xe nào chạy về trạm này. Giãn cách dự kiến: ~10-15 phút."
            )

        shape_model = self._get_shape_projection_model(route_id, dir_str)
        if shape_model is None:
            return StationEtaResponse(
                route_id=route_id,
                route_code=route_code,
                direction=dir_int,
                direction_str=dir_str,
                target_station=target_st,
                query_time=now_iso,
                day_type=day_type,
                hour_slot=hour_slot,
                traffic_condition="THONG_THOANG",
                approaching_count=0,
                buses=[],
                message="Đang đồng bộ hình học tuyến..."
            )

        station_s = [st.cum_distance_m for st in stations_resp.stations]
        approaching_buses: List[ApproachingBusDTO] = []
        speeds: List[float] = []
        now_epoch = now_hn.timestamp()

        for v in live_resp.vehicles:
            s_bus, d_perp = self._project_point(shape_model, v.lat, v.lng)

            # 1. Trích xuất timestamp GPS thực tế của xe (t_ping)
            t_ping, ping_time_str = _parse_ping_epoch(v.updated_at, now_epoch)
            delta_t_age = max(0.0, now_epoch - t_ping)

            # Lọc Hành lang An toàn (Corridor Hygiene <= CORRIDOR_DEVIATION_METERS)
            if d_perp > CORRIDOR_DEVIATION_METERS:
                continue

            # Điều kiện Tiếp cận Hợp lệ (s_bus < s_target - 10.0m)
            if s_bus >= s_target - 10.0:
                continue

            dist_to_st = s_target - s_bus
            speeds.append(v.speed_kmh)

            # Xác định đoạn trạm hiện tại [k, k+1]
            k = 0
            for idx in range(n_stations - 1):
                if station_s[idx] <= s_bus < station_s[idx + 1]:
                    k = idx
                    break
            if s_bus >= station_s[-1]:
                k = n_stations - 2

            stops_rem = max(1, station_order - k)
            l_k = max(1.0, station_s[k + 1] - station_s[k])
            rem_in_seg = max(0.0, station_s[k + 1] - s_bus)
            rho = min(1.0, max(0.0, rem_in_seg / l_k))

            # Thời gian dư đoạn hiện tại
            t_p10, t_p50, t_p90, _, _ = self._lookup_baseline_tt(route_id, dir_int, k, k + 1, day_type, hour_slot, l_k)
            res_p10 = rho * t_p10
            res_p50 = rho * t_p50
            res_p90 = rho * t_p90

            # Cộng dồn các phân đoạn tiếp theo
            inter_p10 = 0.0
            inter_p50 = 0.0
            inter_p90 = 0.0
            for m in range(k + 1, station_order):
                seg_len_m = max(1.0, station_s[m + 1] - station_s[m])
                m_p10, m_p50, m_p90, _, _ = self._lookup_baseline_tt(route_id, dir_int, m, m + 1, day_type, hour_slot, seg_len_m)
                inter_p10 += m_p10
                inter_p50 += m_p50
                inter_p90 += m_p90

            raw_eta_p10 = max(0.0, res_p10 + inter_p10)
            raw_eta_p50 = max(raw_eta_p10, res_p50 + inter_p50)
            raw_eta_p90 = max(raw_eta_p50, res_p90 + inter_p90)

            # Mô hình vật lý trung thực nguyên bản (First-Principles):
            # TUYỆT ĐỐI KHÔNG trừ lùi tuổi gói tin thành số âm.
            # ETA là thời gian cần thiết để đi từ vị trí ghi nhận cuối cùng đến trạm đích.
            display_eta_min = int(math.ceil(raw_eta_p50 / 60.0))
            p10_min = int(math.ceil(raw_eta_p10 / 60.0))
            p90_min = int(math.ceil(raw_eta_p90 / 60.0))

            if display_eta_min <= 1:
                disp_text = "~1 phút"
            else:
                disp_text = f"{display_eta_min} phút"

            # Giờ hiển thị định dạng HH:MM:SS tính từ t_early = now_epoch + raw_eta_p10 (bảo đảm luôn ở tương lai)
            t_early = now_epoch + raw_eta_p10
            rec_time_dt = datetime.fromtimestamp(t_early, tz=HANOI_TZ)
            rec_arr_time = rec_time_dt.strftime("%H:%M:%S")

            # Trạng thái giao thông tức thời của xe
            if v.speed_kmh < 5.0:
                tr_status = "UN_TAC"
            elif v.speed_kmh < 15.0:
                tr_status = "BINH_THUONG"
            else:
                tr_status = "THONG_THOANG"

            safe_window = SafeWindowDTO(
                p10_seconds=round(raw_eta_p10, 1),
                p50_seconds=round(raw_eta_p50, 1),
                p90_seconds=round(raw_eta_p90, 1),
                p10_minutes=p10_min,
                p90_minutes=p90_min,
                conservative_eta_seconds=round(raw_eta_p50, 1),
                buffer_seconds=0.0,
                display_eta_minutes=display_eta_min,
                is_delayed=False,
                delay_seconds=0.0,
                recommended_arrival_time=rec_arr_time
            )

            approaching_buses.append(ApproachingBusDTO(
                vehicle_id=v.id,
                plate=v.plate,
                distance_to_station_m=round(dist_to_st, 1),
                stops_remaining=stops_rem,
                eta_seconds=round(raw_eta_p50, 1),
                eta_minutes=round(raw_eta_p50 / 60.0, 1),
                display_eta_minutes=display_eta_min,
                display_text=disp_text,
                safe_window=safe_window,
                speed_kmh=round(v.speed_kmh, 1),
                status="IN_TRANSIT",
                traffic_status=tr_status,
                ping_time=ping_time_str,
                ping_age_seconds=round(delta_t_age, 1),
                arrival_time_epoch=round(now_epoch + raw_eta_p50, 1)
            ))

        approaching_buses.sort(key=lambda b: (b.eta_seconds, b.distance_to_station_m))

        if speeds:
            avg_spd = sum(speeds) / len(speeds)
            if avg_spd >= 20.0:
                traffic_cond = "THONG_THOANG"
            elif avg_spd >= 12.0:
                traffic_cond = "BINH_THUONG"
            else:
                traffic_cond = "UN_TAC"
        else:
            traffic_cond = "THONG_THOANG"

        app_count = len(approaching_buses)
        if app_count > 0:
            msg = f"Có {app_count} xe đang di chuyển về trạm."
        else:
            msg = "Hiện chưa có xe nào chạy về trạm này. Giãn cách dự kiến: ~10-15 phút."

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
            approaching_count=app_count,
            buses=approaching_buses,
            message=msg
        )
