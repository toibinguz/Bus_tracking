"""
Find all new 7-digit vehicle IDs on Route 40 (`routeId == 40`) on BusMap right now!
"""

import os
import sys

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from module_1_data_ingestion_and_preprocessing import (
    fetch_single_bus_raw,
    search_vehicles_by_query,
)


def main() -> None:
    print("1. Live `fetch_single_bus_raw(8836704)`:")
    print("  ->", fetch_single_bus_raw(8836704))

    print("\n2. Scanning prefixes `29B19`, `29B20`, `29B18`, `29B21`, `29F00`, `29F01`, `29F02`, `29F03`, `29F04`, `29F05` for `routeId == 40`:")
    found_40 = {}
    for prefix in [f"29B{i:02d}" for i in range(10, 35)] + [f"29F{i:02d}" for i in range(0, 10)]:
        res = search_vehicles_by_query(prefix)
        for item in res:
            if item.get("routeId") == 40:
                found_40[item["id"]] = item

    print(f"  * Discovered {len(found_40)} vehicles on Route 40:")
    for vid, item in sorted(found_40.items()):
        live = fetch_single_bus_raw(vid)
        print(f"    -> id={vid} | title={item.get('title')} | live={live}")


if __name__ == "__main__":
    main()
