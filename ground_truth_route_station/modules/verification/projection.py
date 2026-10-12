"""
Step 3: Spherical / Geodesic Orthogonal Telemetry Projection Engine
- Hoàn toàn KHÔNG sử dụng phép chiếu phẳng 2D (Equirectangular planar approximation).
- Sử dụng 100% công thức hình học mặt cầu (Spherical Trigonometry / Geodesic Cross-Track Distance):
  + Khoảng cách cung đại tròn (Great-Circle Distance via Haversine)
  + Góc phương vị mặt cầu (Spherical Initial Bearing / Azimuth)
  + Độ lệch vuông góc mặt cầu (Spherical Cross-Track Distance d_perp)
  + Khoảng cách dọc tuyến mặt cầu (Along-Track Distance d_parallel)
  + Tọa độ hình chiếu trực giao chính xác trên mặt cầu P'(lat', lon')
- Hỗ trợ cả định dạng chuỗi đơn (LineString) và danh sách các đoạn đường nguyên bản (Ways / MultiLineString).
"""

import math
from typing import Tuple, List, Dict, Any, Optional

# Bán kính trung bình bề mặt Trái Đất theo chuẩn trắc địa IUGG (WGS84)
EARTH_RADIUS_M = 6371008.8

def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách cung tròn trên mặt cầu (Great-Circle Distance) tính bằng mét."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0)**2
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))

def spherical_bearing_rad(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Góc phương vị mặt cầu (Spherical Azimuth) từ điểm 1 đến điểm 2 tính bằng radian [-pi, pi]."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return math.atan2(y, x)

def project_point_onto_spherical_segment(
    lat_p: float, lon_p: float,
    lat_a: float, lon_a: float,
    lat_b: float, lon_b: float
) -> Tuple[float, float, float, float, bool]:
    """
    Chiếu trực giao điểm P(lat_p, lon_p) lên đoạn cung đại tròn AB trên mặt cầu Trái Đất.
    
    Sử dụng định lý lượng giác mặt cầu (Napier's rules on spherical right triangles):
      delta_xt = asin( sin(sigma_ap) * sin(theta_ap - theta_ab) )
      delta_at = atan2( tan(sigma_ap) * cos(theta_ap - theta_ab), 1.0 )
      
    Returns:
      proj_lat: Vĩ độ của điểm hình chiếu P' (độ)
      proj_lon: Kinh độ của điểm hình chiếu P' (độ)
      perp_dist_m: Khoảng cách sai số vuông góc |d_perp| (mét)
      along_dist_m: Khoảng cách dọc tuyến từ A đến P' (mét)
      is_strictly_perpendicular: True nếu hình chiếu rơi vào lòng đoạn AB
    """
    d_ab = haversine_distance_m(lat_a, lon_a, lat_b, lon_b)
    if d_ab < 0.01:
        # Đoạn đường suy biến thành 1 điểm
        d_ap = haversine_distance_m(lat_a, lon_a, lat_p, lon_p)
        return lat_a, lon_a, d_ap, 0.0, False

    d_ap = haversine_distance_m(lat_a, lon_a, lat_p, lon_p)
    theta_ap = spherical_bearing_rad(lat_a, lon_a, lat_p, lon_p)
    theta_ab = spherical_bearing_rad(lat_a, lon_a, lat_b, lon_b)

    sigma_ap = d_ap / EARTH_RADIUS_M
    sigma_ab = d_ab / EARTH_RADIUS_M

    # 1. Tính góc lệch ngang (Cross-track angular distance)
    # Giới hạn trong [-1.0, 1.0] để tránh lỗi làm tròn số thực của arcsin
    sin_xt = math.sin(sigma_ap) * math.sin(theta_ap - theta_ab)
    sin_xt_clamped = max(-1.0, min(1.0, sin_xt))
    delta_xt = math.asin(sin_xt_clamped)
    perp_dist_m = abs(EARTH_RADIUS_M * delta_xt)

    # 2. Tính góc lệch dọc (Along-track angular distance từ A)
    delta_at = math.atan2(math.tan(sigma_ap) * math.cos(theta_ap - theta_ab), 1.0)
    along_dist_m = EARTH_RADIUS_M * delta_at

    # 3. Xét biên đoạn AB:
    if delta_at <= 0.0:
        # Hình chiếu rơi phía trước mút A -> Điểm gần nhất là A
        return lat_a, lon_a, d_ap, 0.0, False
    elif delta_at >= sigma_ab:
        # Hình chiếu rơi vượt quá mút B -> Điểm gần nhất là B
        d_bp = haversine_distance_m(lat_b, lon_b, lat_p, lon_p)
        return lat_b, lon_b, d_bp, d_ab, False
    else:
        # Hình chiếu rơi chính xác vào lòng cung AB (Nội suy trực giao hoàn hảo)
        phi_a = math.radians(lat_a)
        lam_a = math.radians(lon_a)
        
        # Tọa độ điểm P' xuất phát từ A theo phương vị theta_ab một góc delta_at
        phi_proj = math.asin(
            math.sin(phi_a) * math.cos(delta_at) +
            math.cos(phi_a) * math.sin(delta_at) * math.cos(theta_ab)
        )
        lam_proj = lam_a + math.atan2(
            math.sin(theta_ab) * math.sin(delta_at) * math.cos(phi_a),
            math.cos(delta_at) - math.sin(phi_a) * math.sin(phi_proj)
        )
        
        proj_lat = math.degrees(phi_proj)
        proj_lon = math.degrees(lam_proj)
        return proj_lat, proj_lon, perp_dist_m, along_dist_m, True

class RoutePolylineProjector:
    """
    Engine Chiếu Trực Giao Đo đạc Telemetry dựa trên 100% Hình Học Mặt Cầu.
    Hỗ trợ cấu trúc nhiều Ways hoặc chuỗi Polyline liên tục.
    """
    def __init__(self, segments_or_coords: Any):
        """
        Khởi tạo danh sách các đoạn tim đường trên mặt cầu.
        Chấp nhận:
          - List[List[float]]: [[lon, lat], [lon, lat], ...] (LineString)
          - List[Dict]: Danh sách các đoạn Way (chuẩn Nodes & Ways mới)
        """
        self.segments = []
        total_chainage = 0.0

        # Kiểm tra xem đầu vào là danh sách Ways hay danh sách Coordinates phẳng
        if isinstance(segments_or_coords, list) and len(segments_or_coords) > 0 and isinstance(segments_or_coords[0], dict) and "coordinates" in segments_or_coords[0]:
            # Đầu vào là danh sách Ways: [ { osm_id, coordinates: [[lon, lat], ...] }, ... ]
            seg_idx = 0
            for w in segments_or_coords:
                w_coords = w.get("coordinates", [])
                w_name = w.get("name", "")
                w_id = w.get("osm_id", 0)
                for i in range(len(w_coords) - 1):
                    lon_a, lat_a = w_coords[i][0], w_coords[i][1]
                    lon_b, lat_b = w_coords[i + 1][0], w_coords[i + 1][1]
                    d_ab = haversine_distance_m(lat_a, lon_a, lat_b, lon_b)
                    self.segments.append({
                        "seg_idx": seg_idx,
                        "way_id": w_id,
                        "street_name": w_name,
                        "a": (lat_a, lon_a),
                        "b": (lat_b, lon_b),
                        "length_m": d_ab,
                        "start_chainage_m": total_chainage
                    })
                    total_chainage += d_ab
                    seg_idx += 1
        else:
            # Đầu vào là mảng tọa độ: [[lon, lat], [lon, lat], ...]
            coords = segments_or_coords
            for i in range(len(coords) - 1):
                lon_a, lat_a = coords[i][0], coords[i][1]
                lon_b, lat_b = coords[i + 1][0], coords[i + 1][1]
                d_ab = haversine_distance_m(lat_a, lon_a, lat_b, lon_b)
                self.segments.append({
                    "seg_idx": i,
                    "way_id": 0,
                    "street_name": "",
                    "a": (lat_a, lon_a),
                    "b": (lat_b, lon_b),
                    "length_m": d_ab,
                    "start_chainage_m": total_chainage
                })
                total_chainage += d_ab

        self.total_length_m = total_chainage

    def project_ping(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Chiếu một điểm GPS ping lên toàn bộ mạng lưới tim đường của tuyến xe buýt.
        Tìm đoạn đường cho khoảng cách vuông góc mặt cầu nhỏ nhất (min d_perp).
        """
        min_dist = float("inf")
        best_seg = None
        best_proj_lat = lat
        best_proj_lon = lon
        best_along_m = 0.0
        best_is_interior = False

        for seg in self.segments:
            lat_a, lon_a = seg["a"]
            lat_b, lon_b = seg["b"]

            p_lat, p_lon, dist_m, along_m, is_interior = project_point_onto_spherical_segment(
                lat, lon, lat_a, lon_a, lat_b, lon_b
            )

            if dist_m < min_dist:
                min_dist = dist_m
                best_seg = seg
                best_proj_lat = p_lat
                best_proj_lon = p_lon
                best_along_m = along_m
                best_is_interior = is_interior

        # Tính khoảng cách tích lũy (chainage) từ đầu tuyến
        chainage_m = best_seg["start_chainage_m"] + best_along_m if best_seg else 0.0

        return {
            "perp_dist_m": round(min_dist, 2),
            "proj_lat": round(best_proj_lat, 6),
            "proj_lon": round(best_proj_lon, 6),
            "chainage_m": round(chainage_m, 2),
            "chainage_pct": round(chainage_m / self.total_length_m * 100.0, 2) if self.total_length_m > 0 else 0.0,
            "segment_idx": best_seg["seg_idx"] if best_seg else -1,
            "way_id": best_seg["way_id"] if best_seg else 0,
            "street_name": best_seg["street_name"] if best_seg else "",
            "is_strictly_perpendicular": best_is_interior
        }

# Wrapper tương thích ngược cho các module cũ
def project_point_onto_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float):
    """Tương thích ngược: Chiếu điểm lên đoạn thẳng."""
    p_lat, p_lon, dist, along, is_interior = project_point_onto_spherical_segment(py, px, ay, ax, by, bx)
    return p_lon, p_lat, dist, along, is_interior

def to_metric_xy(lat: float, lon: float):
    """Tương thích ngược: Đổi lat, lon sang mét cục bộ."""
    return lon * 111320.0 * math.cos(math.radians(lat)), lat * 110540.0

def to_wgs84_latlon(x: float, y: float):
    """Tương thích ngược: Đổi mét sang lat, lon."""
    lat = y / 110540.0
    lon = x / (111320.0 * math.cos(math.radians(lat)))
    return lat, lon

