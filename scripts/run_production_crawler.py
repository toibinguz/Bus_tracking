"""
Production Crawler Entrypoint
Thin facade delegating directly to module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.local_production_crawler.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.local_production_crawler import main

if __name__ == "__main__":
    main()
