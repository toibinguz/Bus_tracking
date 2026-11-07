"""
CLI Entry Point: Parallel 1D Frenet Spatial Projection (Module 1 - Step 1.4)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector import (
    run_parallel_projection,
)

if __name__ == "__main__":
    run_parallel_projection()
