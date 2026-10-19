"""
Step 3.2: Virtual Ghost Point Engine & Detour Compensator
Chiến thuật 'Điểm Ma' (Virtual Ghost Point) xử lý 1% trường hợp xe buýt detour, chạy tránh công trình
hoặc gặp sự cố lệch tuyến:
- Giữ nguyên tọa độ GPS trực quan thực tế (visual_lat, visual_lon) để người dùng theo dõi chính xác.
- Chiếu điểm ma (s_ghost, ghost_lat, ghost_lon) lên trục lý trình tim tuyến OSM [0, L]
  dựa trên phép chiếu vuông góc tối ưu hoặc momentum vận tốc.
- Tính toán khoảng cách còn lại (rem_dist_m) và ETA (eta_sec) ổn định, tránh làm vỡ logic 99% còn lại.
"""

import math
from typing import Dict, Any, Tuple, Optional

def compute_virtual_ghost_point(
    lat: float,
    lon: float,
    projector,
    prev_chainage_m: Optional[float] = None
) -> Dict[str, Any]:
    """
    Tính toán vị trí Điểm Ma trên tim đường cho một tọa độ GPS thực tế.
    """
    proj_lat, proj_lon, perp_dist, along_dist, is_strictly_perp = projector.project_point(lat, lon)
    total_len = projector.total_length_m

    # Nếu xe chạy lùi hoặc nhảy ngược chuỗi quá xa, sử dụng momentum
    s_ghost = along_dist
    if prev_chainage_m is not None and along_dist < prev_chainage_m:
        # Nếu thụt lùi nhẹ (< 50m) do jitter GPS, giữ nguyên s trước đó
        if (prev_chainage_m - along_dist) < 50.0:
            s_ghost = prev_chainage_m

    rem_dist_m = max(0.0, total_len - s_ghost)
    is_detour = perp_dist > 45.0  # Ngưỡng lệch tim đường coi là detour

    return {
        "visual_lat": lat,
        "visual_lon": lon,
        "ghost_lat": proj_lat,
        "ghost_lon": proj_lon,
        "s_ghost": round(s_ghost, 1),
        "perp_dist_m": round(perp_dist, 1),
        "rem_dist_m": round(rem_dist_m, 1),
        "is_detour": is_detour
    }

