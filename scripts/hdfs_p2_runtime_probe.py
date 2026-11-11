"""Print the pinned projection runtime identities inside the Spark image."""

import platform
from pathlib import Path
import sys

import numpy

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.projection_boundary import (  # noqa: F401
    project_route_events,
)


print(f"python={platform.python_version()}")
print(f"numpy={numpy.__version__}")
print("projection-import=ok")
