"""Verify the accepted projection boundary imports in the Spark project image."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary import (  # noqa: F401
    project_route_events,
)


print("DEP-03 projection-import=ok")
