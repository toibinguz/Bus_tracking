"""
Scripts: Ingest Canonical BusMap Master Data
Thin facade CLI to migrate and ingest BusMap native routes and stations
into canonical_shape_master, canonical_station_master, and canonical_route_master.
"""

import os
import sys

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_1_data_ingestion_and_preprocessing.step_1_5_busmap_canonical_migration.ingest_busmap_canonical import main

if __name__ == "__main__":
    main()

