"""
Step 3: Orthogonal Telemetry Projection Engine
Computes exact perpendicular projections of telemetry GPS pings onto route polyline segments.
Calculates orthogonal error distance in meters, linear referencing along route,
and identifies whether pings lie on-route within tolerance.
"""

import math
from typing import Tuple, List, Dict, Any, Optional

# Reference origin for Hanoi metric coordinate projection (Equirectangular)
HANOI_LAT_ORIGIN = 21.0
HANOI_LON_ORIGIN = 105.8
EARTH_RADIUS_M = 6371000.0
RAD_LAT = math.radians(HANOI_LAT_ORIGIN)
COS_RAD_LAT = math.cos(RAD_LAT)

def to_metric_xy(lat: float, lon: float) -> Tuple[float, float]:
    """
    Projects WGS84 (lat, lon) to Cartesian metric coordinates (x, y) in meters
    relative to Hanoi center (error < 0.05% across urban extent).
    """
    x = EARTH_RADIUS_M * math.radians(lon - HANOI_LON_ORIGIN) * COS_RAD_LAT
    y = EARTH_RADIUS_M * math.radians(lat - HANOI_LAT_ORIGIN)
    return x, y

def to_wgs84_latlon(x: float, y: float) -> Tuple[float, float]:
    """Inverse projection from metric coordinates back to (lat, lon)."""
    lat = HANOI_LAT_ORIGIN + math.degrees(y / EARTH_RADIUS_M)
    lon = HANOI_LON_ORIGIN + math.degrees(x / (EARTH_RADIUS_M * COS_RAD_LAT))
    return lat, lon

def project_point_onto_segment(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float
) -> Tuple[float, float, float, float, bool]:
    """
    Calculates the perpendicular projection of point P(px, py) onto segment AB.
    
    Returns:
        proj_x: X coordinate of projected point P'
        proj_y: Y coordinate of projected point P'
        perp_dist_m: Perpendicular orthogonal distance ||P - P'|| in meters
        t_param: Projection parameter t (unclamped)
        is_strictly_perpendicular: True if 0.0 <= t <= 1.0 (interior orthogonal)
    """
    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq == 0.0:
        # Segment is degenerate (point)
        dist = math.sqrt((px - ax)**2 + (py - ay)**2)
        return ax, ay, dist, 0.0, False

    # Projection parameter t = (AP . AB) / ||AB||^2
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t_clamped = max(0.0, min(1.0, t))

    proj_x = ax + t_clamped * dx
    proj_y = ay + t_clamped * dy
    perp_dist_m = math.sqrt((px - proj_x)**2 + (py - proj_y)**2)
    is_strictly_perpendicular = (0.0 <= t <= 1.0)

    return proj_x, proj_y, perp_dist_m, t, is_strictly_perpendicular

class RoutePolylineProjector:
    """
    High-performance projector for a continuous route polyline.
    Precomputes metric segments and cumulative chainage for sub-millisecond projection.
    """
    def __init__(self, coordinates: List[List[float]]):
        """
        Args:
            coordinates: List of [lon, lat] or [[lon, lat], ...] coordinates.
        """
        if len(coordinates) < 2:
            raise ValueError("Route polyline must have at least 2 vertices.")

        self.coords_lonlat = coordinates
        self.vertices_xy: List[Tuple[float, float]] = []
        for pt in coordinates:
            lon, lat = pt[0], pt[1]
            self.vertices_xy.append(to_metric_xy(lat, lon))

        # Build segments and cumulative chainage
        self.segments = []
        self.cumulative_dist = [0.0]
        total_len = 0.0

        for i in range(len(self.vertices_xy) - 1):
            ax, ay = self.vertices_xy[i]
            bx, by = self.vertices_xy[i + 1]
            seg_len = math.sqrt((bx - ax)**2 + (by - ay)**2)
            self.segments.append({
                "idx": i,
                "a": (ax, ay),
                "b": (bx, by),
                "seg_len": seg_len,
                "start_chainage": total_len
            })
            total_len += seg_len
            self.cumulative_dist.append(total_len)

        self.total_length_m = total_len

    def project_ping(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Projects a GPS ping onto the entire route polyline.
        Finds the segment yielding minimum perpendicular distance.
        """
        px, py = to_metric_xy(lat, lon)

        min_dist = float("inf")
        best_seg = None
        best_proj_x = px
        best_proj_y = py
        best_t = 0.0
        best_is_interior = False

        for seg in self.segments:
            ax, ay = seg["a"]
            bx, by = seg["b"]
            proj_x, proj_y, dist_m, t, is_interior = project_point_onto_segment(px, py, ax, ay, bx, by)

            if dist_m < min_dist:
                min_dist = dist_m
                best_seg = seg
                best_proj_x = proj_x
                best_proj_y = proj_y
                best_t = t
                best_is_interior = is_interior

        # Compute chainage (distance along route from start)
        t_clamped = max(0.0, min(1.0, best_t))
        chainage_m = best_seg["start_chainage"] + t_clamped * best_seg["seg_len"] if best_seg else 0.0
        proj_lat, proj_lon = to_wgs84_latlon(best_proj_x, best_proj_y)

        return {
            "perp_dist_m": round(min_dist, 2),
            "proj_lat": round(proj_lat, 6),
            "proj_lon": round(proj_lon, 6),
            "chainage_m": round(chainage_m, 2),
            "chainage_pct": round(chainage_m / self.total_length_m * 100.0, 2) if self.total_length_m > 0 else 0.0,
            "segment_idx": best_seg["idx"] if best_seg else -1,
            "is_strictly_perpendicular": best_is_interior
        }

