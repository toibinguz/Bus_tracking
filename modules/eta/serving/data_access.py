"""
Step 3.4 — Truy cập dữ liệu (SQLite canonical serving DB).
Module: modules/eta/serving/data_access.py

Đơn trách nhiệm: toàn bộ I/O cho tầng serving (routes/shapes/stations/baseline matrix).
Không tính ETA. Mọi ngưỡng lấy từ `config.system_config` (không magic number).
Quản lý catalog tuyến/trạm, baseline matrix và hình học tim tuyến.
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import quote

from config.system_config import (
    CONFIG_FILE,
    DAY_TYPE_SATURDAY,
    DAY_TYPE_SUNDAY,
    DEFAULT_DB_PATH,
    DEFAULT_TIMBUS_DB_PATH,
    DEFAULT_URBAN_BUS_SPEED_KMPH,
    EXCLUDE_TERMINAL_BOUNDARY_STATIONS,
)
from modules.eta.serving.dto import (
    RouteItemDTO,
    RouteShapeResponse,
    RouteStationsResponse,
    StationItemDTO,
    normalize_direction,
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Key ma trận baseline: (route_key, dir_int, from_order, to_order, day_type, hour_slot)
BaselineKey = Tuple[Union[int, str], int, int, int, int, int]


def _get_active_corridor_stations(
    st_list: List[Tuple[int, int, str, float]]
) -> List[Tuple[int, int, str, float]]:
    """TD-19: loại 2 trạm biên (order 0 và N) khi EXCLUDE_TERMINAL_BOUNDARY_STATIONS, trả [1 .. N-1]."""
    if EXCLUDE_TERMINAL_BOUNDARY_STATIONS and len(st_list) >= 4:
        return st_list[1:-1]
    return st_list


class DataAccess:
    """Nạp catalog + shape + stations + baseline matrix vào RAM; phục vụ tra cứu O(1)/O(seg)."""

    def __init__(self, db_path: Optional[str] = None, config_path: Optional[str] = None, timbus_db_path: Optional[str] = None):
        self._db_path = os.path.abspath(db_path) if db_path else os.path.join(BASE_DIR, DEFAULT_DB_PATH)
        self._config_path = os.path.abspath(config_path) if config_path else os.path.join(BASE_DIR, CONFIG_FILE)
        self._timbus_db_path = os.path.abspath(timbus_db_path) if timbus_db_path else os.path.join(BASE_DIR, DEFAULT_TIMBUS_DB_PATH)

        self._routes_cache: List[RouteItemDTO] = []
        self._routes_by_id: Dict[int, RouteItemDTO] = {}
        self._routes_by_code: Dict[str, RouteItemDTO] = {}
        self._shape_cache: Dict[Tuple[int, str], RouteShapeResponse] = {}
        self._shape_points_cache: Dict[Tuple[int, str], List[Tuple[int, float, float, float]]] = {}
        self._stations_cache: Dict[Tuple[int, str], RouteStationsResponse] = {}
        self._corridor_cache: Dict[Tuple[int, str], List[Tuple[int, int, str, float]]] = {}
        self._profile_cache: Dict[Tuple[str, int], Tuple[float, float, float]] = {}

        # key -> (p10, p50, p90, mean, std, quality_tier, seg_len_m)
        self._baseline_matrix: Dict[BaselineKey, Tuple[float, float, float, float, float, int, float]] = {}
        # (route_code, dir_int) -> [sum_seg_len, sum_p50] dùng tính route_base_speed
        self._bm_agg: Dict[Tuple[str, int], List[float]] = {}
        # route_code -> idx (theo danh mục sort của agg_segment_travel_times)
        self.route_idx_by_code: Dict[str, int] = {}
        # (route_id, dir_int) -> (timbus_enabled, [primary_sid, backup_sid])
        self._timbus_anchors: Dict[Tuple[int, int], Tuple[bool, List[int]]] = {}

        self.load_timbus_anchors()
        self.load_catalog()
        self.load_baseline_matrix()

    # ------------------------------------------------------------------ IO
    @contextmanager
    def _connect_ro(self, path: str):
        """Kết nối SQLite chỉ đọc (URI ?mode=ro), đóng chắc chắn trong finally."""
        uri = "file:" + quote(path.replace("\\", "/"), safe="/:") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _connect(self):
        """Kết nối SQLite chính chỉ đọc (URI ?mode=ro)."""
        with self._connect_ro(self._db_path) as conn:
            yield conn

    def load_timbus_anchors(self) -> Dict[Tuple[int, int], Tuple[bool, List[int]]]:
        """Nạp bảng timbus_route_anchors (dự phòng timbus_verified_anchors) vào RAM 1 lần."""
        self._timbus_anchors.clear()
        if not os.path.exists(self._timbus_db_path):
            return self._timbus_anchors
        try:
            with self._connect_ro(self._timbus_db_path) as conn:
                tables = {
                    str(r[0])
                    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
                tbl = "timbus_route_anchors" if "timbus_route_anchors" in tables else (
                    "timbus_verified_anchors" if "timbus_verified_anchors" in tables else None
                )
                if tbl is None:
                    return self._timbus_anchors
                rows = conn.execute(
                    f"SELECT route_id, direction, timbus_enabled, primary_anchor_sid, backup_anchor_sid FROM {tbl}"
                ).fetchall()
            for rid, d_int, en, pri, bak in rows:
                enabled = bool(int(en) == 1 and pri)
                anchors = [int(x) for x in (pri, bak) if x] if enabled else []
                self._timbus_anchors[(int(rid), int(d_int))] = (bool(enabled and anchors), anchors)
            logger.info("Loaded %d timbus anchor entries từ %s", len(self._timbus_anchors), tbl)
        except Exception as e:
            logger.warning("Không đọc được bảng anchor TimBus từ %s: %s", self._timbus_db_path, e)
        return self._timbus_anchors

    def get_timbus_anchors(self, route_id: int, direction: int) -> Tuple[bool, List[int]]:
        """Trả (timbus_enabled, [primary_anchor_sid, backup_anchor_sid]) cho cặp (route_id, direction)."""
        return self._timbus_anchors.get((int(route_id), int(direction)), (False, []))

    def load_catalog(self) -> Tuple[List[RouteItemDTO], Dict[int, RouteItemDTO], Dict[str, RouteItemDTO]]:
        """Tải danh mục tuyến từ canonical_route_master; dự phòng JSON config. Trả (list, by_id, by_code)."""
        loaded = False
        if os.path.exists(self._db_path):
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT route_id, route_code, route_name FROM canonical_route_master ORDER BY route_id"
                    ).fetchall()
                for row in rows:
                    r_id = int(row[0])
                    r_no = str(row[1]).strip()
                    dto = RouteItemDTO(
                        route_id=r_id,
                        route_no=r_no,
                        name=str(row[2]).strip(),
                        timbus_supported=bool(self.get_timbus_anchors(r_id, 0)[0] or self.get_timbus_anchors(r_id, 1)[0]),
                    )
                    self._routes_cache.append(dto)
                    self._routes_by_id[r_id] = dto
                    self._routes_by_code[r_no.upper()] = dto
                    self._routes_by_code[r_no.lstrip("0").upper()] = dto
                loaded = bool(rows)
                logger.info("Loaded %d routes từ canonical_route_master", len(self._routes_cache))
            except Exception as e:
                logger.warning("Lỗi nạp catalog từ SQLite (%s), fallback JSON: %s", self._db_path, e)

        if not loaded and os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data.get("routes", []):
                    r_id = int(item["route_id"])
                    r_no = str(item.get("route_no", str(r_id))).strip()
                    if r_id in self._routes_by_id:
                        continue
                    dto = RouteItemDTO(
                        route_id=r_id,
                        route_no=r_no,
                        name=str(item.get("name", f"Tuyến {r_no}")).strip(),
                        timbus_supported=bool(self.get_timbus_anchors(r_id, 0)[0] or self.get_timbus_anchors(r_id, 1)[0]),
                    )
                    self._routes_cache.append(dto)
                    self._routes_by_id[r_id] = dto
                    self._routes_by_code[r_no.upper()] = dto
                    self._routes_by_code[r_no.lstrip("0").upper()] = dto
                logger.info("Loaded %d routes từ JSON %s", len(self._routes_cache), self._config_path)
            except Exception as e:
                logger.error("Lỗi nạp catalog từ JSON %s: %s", self._config_path, e)

        return self._routes_cache, self._routes_by_id, self._routes_by_code

    def load_baseline_matrix(self) -> Dict[BaselineKey, Tuple[float, float, float, float, float, int, float]]:
        """Nạp agg_segment_travel_times vào RAM; cũng dựng route_idx_by_code + route_base_speed agg."""
        if not os.path.exists(self._db_path):
            return self._baseline_matrix

        try:
            with self._connect_ro(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT route_code, direction, from_station_order, to_station_order, day_type, hour_slot, "
                    "quality_tier, tt_p10_sec, tt_p50_sec, tt_p90_sec, tt_mean_sec, tt_std_sec, segment_length_m "
                    "FROM agg_segment_travel_times"
                ).fetchall()

            codes = sorted({str(r[0]).strip() for r in rows})
            self.route_idx_by_code = {c: i for i, c in enumerate(codes)}

            for r_code, dir_str, f_ord, t_ord, dt_v, hr_v, q_t, p10, p50, p90, mean_v, std_v, seg_l in rows:
                r_id = self.resolve_route_id(r_code)
                dir_int = 0 if str(dir_str).strip().lower() == "go" else 1
                val = (float(p10), float(p50), float(p90), float(mean_v), float(std_v), int(q_t), float(seg_l))
                if r_id is not None:
                    self._baseline_matrix[(r_id, dir_int, int(f_ord), int(t_ord), int(dt_v), int(hr_v))] = val
                code_clean = str(r_code).strip().upper()
                self._baseline_matrix[(code_clean, dir_int, int(f_ord), int(t_ord), int(dt_v), int(hr_v))] = val

                agg = self._bm_agg.setdefault((str(r_code), dir_int), [0.0, 0.0])
                agg[0] += float(seg_l)
                agg[1] += float(p50)

            logger.info("Loaded %d baseline cells vào RAM cache", len(self._baseline_matrix))
        except Exception as e:
            logger.warning("Không nạp được ma trận baseline: %s", e)
        return self._baseline_matrix

    # ----------------------------------------------------------- catalog API
    def get_routes(self) -> List[RouteItemDTO]:
        """Toàn bộ danh sách tuyến khả dụng."""
        return list(self._routes_cache)

    def resolve_route_id(self, route_ident: Union[str, int]) -> Optional[int]:
        """Phân giải mã số tuyến (string/int) sang route_id BusMap gốc."""
        if isinstance(route_ident, bool):
            return None
        if isinstance(route_ident, int):
            return route_ident if route_ident in self._routes_by_id else None

        cleaned = str(route_ident).strip().upper()
        if not cleaned:
            return None
        if cleaned in self._routes_by_code:
            return self._routes_by_code[cleaned].route_id
        stripped = cleaned.lstrip("0")
        if stripped in self._routes_by_code:
            return self._routes_by_code[stripped].route_id
        try:
            parsed_id = int(cleaned)
            return parsed_id if parsed_id in self._routes_by_id else None
        except ValueError:
            return None

    def get_route_code(self, route_id: int) -> str:
        """Số hiệu tuyến từ route_id."""
        dto = self._routes_by_id.get(int(route_id))
        return dto.route_no if dto else str(route_id)

    def get_route_idx(self, route_id: int) -> Optional[int]:
        """Chỉ mục route_id_idx (route_code trong danh mục sort của agg_segment_travel_times)."""
        return self.route_idx_by_code.get(self.get_route_code(route_id))

    # ------------------------------------------------------------ shape API
    def get_shape_points(self, route_id: int, dir_str: str) -> List[Tuple[int, float, float, float]]:
        """[(point_order, lat, lon, cum_distance_m)] sắp theo point_order."""
        cache_key = (int(route_id), dir_str)
        if cache_key in self._shape_points_cache:
            return self._shape_points_cache[cache_key]
        if not os.path.exists(self._db_path):
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT point_order, lat, lon, cum_distance_m FROM canonical_shape_master "
                    "WHERE route_id = ? AND direction = ? ORDER BY point_order ASC",
                    (int(route_id), dir_str),
                ).fetchall()
            points = [(int(r[0]), float(r[1]), float(r[2]), float(r[3])) for r in rows]
            self._shape_points_cache[cache_key] = points
            return points
        except Exception as e:
            logger.error("Lỗi truy vấn shape route %s dir %s: %s", route_id, dir_str, e)
            return []

    def get_route_shape(self, route_ident: Union[str, int], dir_str: str) -> Optional[RouteShapeResponse]:
        """Tim tuyến theo route_id/code + dir_str; None nếu không có dữ liệu."""
        route_id = self.resolve_route_id(route_ident)
        if route_id is None:
            return None
        cache_key = (route_id, dir_str)
        if cache_key in self._shape_cache:
            return self._shape_cache[cache_key]

        points = self.get_shape_points(route_id, dir_str)
        if not points:
            return None
        coords = [[p[1], p[2]] for p in points]
        resp = RouteShapeResponse(
            route_id=route_id,
            route_code=self.get_route_code(route_id),
            direction=0 if dir_str == "go" else 1,
            direction_str=dir_str,
            point_count=len(coords),
            total_distance_m=round(points[-1][3], 1),
            coordinates=coords,
        )
        self._shape_cache[cache_key] = resp
        return resp

    # ---------------------------------------------------------- station API
    def get_route_stations(self, route_ident: Union[str, int], dir_str: str) -> Optional[RouteStationsResponse]:
        """Toàn bộ trạm dừng 0..N-1 của tuyến theo chiều."""
        route_id = self.resolve_route_id(route_ident)
        if route_id is None:
            return None
        cache_key = (route_id, dir_str)
        if cache_key in self._stations_cache:
            return self._stations_cache[cache_key]
        if not os.path.exists(self._db_path):
            return None
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT station_order, station_id, station_name, address, lat, lon, cum_distance_m "
                    "FROM canonical_station_master WHERE route_id = ? AND direction = ? ORDER BY station_order ASC",
                    (route_id, dir_str),
                ).fetchall()
            if not rows:
                return None
            stations = [
                StationItemDTO(
                    station_order=int(r[0]),
                    station_id=int(r[1]),
                    station_name=str(r[2]),
                    address=str(r[3] or ""),
                    lat=float(r[4]),
                    lon=float(r[5]),
                    cum_distance_m=round(float(r[6]), 1),
                )
                for r in rows
            ]
            resp = RouteStationsResponse(
                route_id=route_id,
                route_code=self.get_route_code(route_id),
                direction=0 if dir_str == "go" else 1,
                direction_str=dir_str,
                station_count=len(stations),
                stations=stations,
            )
            self._stations_cache[cache_key] = resp
            return resp
        except Exception as e:
            logger.error("Lỗi truy vấn stations route %s dir %s: %s", route_id, dir_str, e)
            return None

    def get_corridor_stations(self, route_id: int, dir_str: str) -> List[Tuple[int, int, str, float]]:
        """Trạm hành lang nội tuyến [1 .. N-1] (khớp tập train của baseline/feature store)."""
        cache_key = (int(route_id), dir_str)
        if cache_key in self._corridor_cache:
            return self._corridor_cache[cache_key]
        resp = self.get_route_stations(route_id, dir_str)
        if resp is None:
            return []
        full = [(st.station_order, st.station_id, st.station_name, st.cum_distance_m) for st in resp.stations]
        corridor = _get_active_corridor_stations(full)
        self._corridor_cache[cache_key] = corridor
        return corridor

    def get_route_profile(self, route_id: int, dir_str: str) -> Tuple[float, float, float]:
        """(route_base_speed_kmh, route_station_spacing_m, route_len_m) đồng bộ với causal_eta."""
        r_code = self.get_route_code(route_id)
        dir_int = 0 if dir_str == "go" else 1
        key = (r_code, dir_int)
        if key in self._profile_cache:
            return self._profile_cache[key]

        corridor = self.get_corridor_stations(route_id, dir_str)
        if len(corridor) >= 2:
            corridor_len = max(100.0, corridor[-1][3] - corridor[0][3])
            spacing = round(corridor_len / max(1, len(corridor) - 1), 1)
        else:
            spacing = 0.0

        agg = self._bm_agg.get(key)
        if agg and agg[1] > 0:
            base_spd = round((agg[0] / agg[1]) * 3.6, 2)
        else:
            base_spd = DEFAULT_URBAN_BUS_SPEED_KMPH

        points = self.get_shape_points(route_id, dir_str)
        route_len = points[-1][3] if points else 0.0
        self._profile_cache[key] = (base_spd, spacing, route_len)
        return self._profile_cache[key]

    # --------------------------------------------------------- baseline API
    def get_baseline_cell(
        self, route_id: Union[int, str], dir_int: int, from_ord: int, to_ord: int, day_type: int, hour_slot: int
    ) -> Optional[Tuple[float, float, float, float, float, int, float]]:
        """Ô baseline thô (p10,p50,p90,mean,std,quality_tier,seg_len) hoặc None nếu khuyết."""
        key = (route_id, dir_int, from_ord, to_ord, day_type, hour_slot)
        if key in self._baseline_matrix:
            return self._baseline_matrix[key]
        resolved_id = self.resolve_route_id(route_id)
        if resolved_id is not None and resolved_id != route_id:
            alt = (resolved_id, dir_int, from_ord, to_ord, day_type, hour_slot)
            if alt in self._baseline_matrix:
                return self._baseline_matrix[alt]
        return None

    def lookup_baseline_tt(
        self, route_id: Union[int, str], dir_int: int, from_ord: int, to_ord: int,
        day_type: int, hour_slot: int, seg_len_m: float,
    ) -> Tuple[float, float, float, float, float]:
        """Tra ma trận [P10,P50,P90,Mean,Std]; fallback DEFAULT_URBAN_BUS_SPEED_KMPH/3.6; bảo đảm p10<=p50<=p90."""
        cell = self.get_baseline_cell(route_id, dir_int, from_ord, to_ord, day_type, hour_slot)
        if cell is not None:
            p10, p50, p90, mean_v, std_v = cell[0], cell[1], cell[2], cell[3], cell[4]
            p10 = max(0.0, p10)
            p50 = max(p10, p50)
            p90 = max(p50, p90)
            return p10, p50, p90, mean_v, std_v

        fallback_mps = DEFAULT_URBAN_BUS_SPEED_KMPH / 3.6
        tt_fallback = max(0.0, seg_len_m / fallback_mps)
        return tt_fallback, tt_fallback, tt_fallback, tt_fallback, 0.0
