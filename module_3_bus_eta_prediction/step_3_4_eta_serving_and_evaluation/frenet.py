"""
Step 3.4 — Chiếu Frenet 1D lên tim tuyến (hợp nhất với module 1.4).
Module: module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/frenet.py

Tái lập CHÍNH XÁC công thức của `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py::project_points_to_shape`
(nhánh Global Search) để loại bỏ train/serve skew:
    kx = METERS_PER_DEG_LON_EQUATOR * cos(radians(mean_lat)); ky = METERS_PER_DEG_LAT
Bổ sung `seg_idx` (module 1.4 không trả) phục vụ bộ lọc hướng vector (heading cosine).
Với 1 ping đơn lẻ ở serving, bỏ qua Forward Sliding Window (cần prev_s) và dùng đúng nhánh global.
"""

import math
from typing import List, Sequence, Tuple

import numpy as np

from config.system_config import (
    METERS_PER_DEG_LAT,
    METERS_PER_DEG_LON_EQUATOR,
)


class ShapeProjectionModel:
    """Mô hình chiếu trực giao Cartesian 1D cho 1 tim tuyến (route_id, direction)."""

    def __init__(
        self,
        kx: float,
        ky: float,
        x1: np.ndarray,
        y1: np.ndarray,
        dx: np.ndarray,
        dy: np.ndarray,
        safe_lens_sq: np.ndarray,
        seg_lens: np.ndarray,
        cum_starts: np.ndarray,
        total_len: float,
    ):
        self.kx = kx
        self.ky = ky
        self._x1 = x1
        self._y1 = y1
        self._dx = dx
        self._dy = dy
        self._safe_lens_sq = safe_lens_sq
        self._seg_lens = seg_lens
        self._cum_starts = cum_starts
        self._total_len = total_len

    @classmethod
    def build(cls, shape_points: Sequence[Tuple[float, float, float, float]]) -> "ShapeProjectionModel":
        """shape_points = [(point_order, lat, lon, cum_distance_m)] sắp xếp theo point_order tăng dần."""
        s_lats = np.array([float(p[1]) for p in shape_points], dtype=np.float64)
        s_lons = np.array([float(p[2]) for p in shape_points], dtype=np.float64)
        s_cums = np.array([float(p[3]) for p in shape_points], dtype=np.float64)

        mean_lat = float(np.mean(s_lats))
        kx = METERS_PER_DEG_LON_EQUATOR * math.cos(math.radians(mean_lat))
        ky = METERS_PER_DEG_LAT

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

        return cls(
            kx=kx,
            ky=ky,
            x1=x1,
            y1=y1,
            dx=dx,
            dy=dy,
            safe_lens_sq=safe_lens_sq,
            seg_lens=seg_lens,
            cum_starts=cum_starts,
            total_len=float(s_cums[-1]),
        )

    def project_point(self, lat: float, lon: float) -> Tuple[float, float, int]:
        """
        Chiếu trực giao điểm GPS (lat, lon) lên toàn bộ tim tuyến (Global Search).
        Trả về (s_bus_m, d_perp_m, seg_idx) — làm tròn 1 chữ số thập phân như module 1.4.
        """
        px = lon * self.kx
        py = lat * self.ky

        p_dx1 = px - self._x1
        p_dy1 = py - self._y1
        t = np.clip((p_dx1 * self._dx + p_dy1 * self._dy) / self._safe_lens_sq, 0.0, 1.0)
        proj_x = self._x1 + t * self._dx
        proj_y = self._y1 + t * self._dy
        dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
        best_seg = int(np.argmin(dist_sq))

        min_d = math.sqrt(float(dist_sq[best_seg]))
        best_t = float(t[best_seg])
        best_s = round(float(self._cum_starts[best_seg] + best_t * self._seg_lens[best_seg]), 1)
        s_bus = max(0.0, min(self._total_len, best_s))
        return s_bus, round(min_d, 1), best_seg

    def segment_unit_tangent(self, seg_idx: int) -> Tuple[float, float]:
        """Vector đơn vị tiếp tuyến tim tuyến tại đoạn seg_idx theo (East, North)."""
        idx = int(min(max(0, seg_idx), len(self._dx) - 1))
        seg_len = float(self._seg_lens[idx])
        if seg_len < 1e-9:
            return 1.0, 0.0
        return float(self._dx[idx] / seg_len), float(self._dy[idx] / seg_len)
