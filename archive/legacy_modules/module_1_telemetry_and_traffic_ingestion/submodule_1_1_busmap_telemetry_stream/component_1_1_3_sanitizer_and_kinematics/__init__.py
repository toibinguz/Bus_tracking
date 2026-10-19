"""
Component 1.1.3: Telemetry Sanitizer & Kinematic Filter
"""

from .kinematic_engine import haversine_distance
from .telemetry_sanitizer import sanitize_and_validate_telemetry

__all__ = [
    "haversine_distance",
    "sanitize_and_validate_telemetry"
]

