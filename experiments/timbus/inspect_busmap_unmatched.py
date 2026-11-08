import sys
import os
sys.path.insert(0, os.path.abspath("."))
from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay.catalog_refresher import fetch_route_buses_live
from experiments.timbus.timbus_tracker import TimBusClient

bm_0 = fetch_route_buses_live(32, 0) or []
bm_1 = fetch_route_buses_live(32, 1) or []
all_bm = bm_0 + bm_1

print(f"Current live BusMap Route 32 buses: {len(all_bm)}")
for b in all_bm:
    plate = str(b.get("VehicleNumber", "")).replace("-", "").replace(".", "").strip().upper()
    spd = b.get("Speed")
    ts = b.get("lastUpdateTime")
    lat = b.get("Lat")
    lng = b.get("Lng")
    tb = TimBusClient.query_targeted_vehicle(157, "32", plate, direction=0)
    if not tb:
        tb = TimBusClient.query_targeted_vehicle(510, "32", plate, direction=1)
    
    status = f"MATCHED (TB spd={tb.speed_kmh}, lat={tb.latitude}, lon={tb.longitude})" if tb else "UNMATCHED IN TIMBUS"
    print(f"Plate {plate:<10} | BM spd={spd:<4} | BM ts={ts} | coord=({lat:.5f}, {lng:.5f}) | {status}")
