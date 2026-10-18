"""
Step 3.3: 1D Route-Curve Kinematic Interpolator (60 FPS)
Triệt tiêu hoàn toàn hiện tượng 'cắt góc 90 độ' (chord shortcutting) khi xe buýt rẽ cua:
- Thay vì nội suy đường thẳng dây cung giữa 2 tọa độ GPS (P1 -> P2),
- Ánh xạ P1 -> s1 và P2 -> s2 trên tim tuyến OSM,
- Nội suy lý trình tuyến s(t) = s1 + (s2 - s1) * alpha (0 <= alpha <= 1),
- Chiếu ngược s(t) -> (lat, lon) uốn lượn chính xác 100% theo từng khúc cua của đường cong OSM (pointAtChainage).
"""

import math
from typing import List, Tuple, Dict, Any

def point_at_chainage(cum_lengths: List[float], polyline_coords: List[Tuple[float, float]], target_s: float) -> Tuple[float, float]:
    """
    Tính tọa độ (lat, lon) tại lý trình target_s mét dọc theo đường cong tim tuyến polyline_coords.
    """
    if not polyline_coords:
        return 0.0, 0.0
    if target_s <= 0:
        return polyline_coords[0]
    total_len = cum_lengths[-1] if cum_lengths else 0.0
    if target_s >= total_len:
        return polyline_coords[-1]

    # Tìm phân đoạn chứa target_s
    for i in range(len(cum_lengths) - 1):
        s_start = cum_lengths[i]
        s_end = cum_lengths[i + 1]
        if s_start <= target_s <= s_end:
            seg_len = s_end - s_start
            if seg_len < 1e-6:
                return polyline_coords[i]
            frac = (target_s - s_start) / seg_len
            lat_a, lon_a = polyline_coords[i]
            lat_b, lon_b = polyline_coords[i + 1]
            interp_lat = lat_a + (lat_b - lat_a) * frac
            interp_lon = lon_a + (lon_b - lon_a) * frac
            return interp_lat, interp_lon

    return polyline_coords[-1]

