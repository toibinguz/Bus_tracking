"""
Module 3.1: Spatial Map Matcher & Chainage Projector
Ánh xạ tọa độ GPS (lat, lon) lên tim đường cong OSM, tính lý trình s [0, L] và độ lệch vuông góc.
"""

import sys
import os

# Import RoutePolylineProjector from existing verified module
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GT_DIR = os.path.join(BASE_DIR, "ground_truth_route_station")
if GT_DIR not in sys.path:
    sys.path.insert(0, GT_DIR)

from modules.verification.projection import RoutePolylineProjector, haversine_distance_m

__all__ = [
    "RoutePolylineProjector",
    "haversine_distance_m"
]

