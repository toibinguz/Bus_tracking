"""
Module 1.1.3: Telemetry Processing Subpackage
"""

from .kinematics import haversine_distance
from .sanitizer import sanitize_and_validate_telemetry

__all__ = [
    "haversine_distance",
    "sanitize_and_validate_telemetry"
]

