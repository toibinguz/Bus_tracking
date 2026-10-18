"""
Module 3: Map Matching, Trajectory Fusion & Anomaly Handling Subpackage
"""

from .matcher import RoutePolylineProjector, haversine_distance_m

__all__ = [
    "RoutePolylineProjector",
    "haversine_distance_m"
]
