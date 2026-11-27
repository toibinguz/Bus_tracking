"""
Module 1.1.3: Kinematic Calculations & Spatial Distances
"""

import math

def haversine_distance(lat1, lon1, lat2, lon2):
    """Tính khoảng cách Great-circle giữa 2 tọa độ WGS84 (mét)."""
    R = 6371000.0  # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

