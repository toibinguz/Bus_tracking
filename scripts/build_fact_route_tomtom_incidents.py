"""
CLI Entry Point: Causal TomTom Incident Spatial Projection (Module 1 - Step 1.4)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.tomtom_incident_projector import (
    main,
)

if __name__ == "__main__":
    main()
