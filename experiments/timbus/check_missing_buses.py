import sys
import os
sys.path.insert(0, os.path.abspath("."))
from experiments.timbus.timbus_tracker import TimBusClient

missing_plates = ["29F01520", "29F05200", "29F05210", "29F05140", "29F05245", "29F05192"]
print("INVESTIGATING UNMATCHED BUSES IN TIMBUS:")
for p in missing_plates:
    # Try querying with station 157 (Giáp Bát) and 510 (Nhổn)
    r1 = TimBusClient.query_targeted_vehicle(157, "32", p, direction=0)
    r2 = TimBusClient.query_targeted_vehicle(510, "32", p, direction=1)
    # also try Route 02 for 29F01520
    r02_go = TimBusClient.query_targeted_vehicle(1750, "02", p, direction=0)
    r02_re = TimBusClient.query_targeted_vehicle(1667, "02", p, direction=1)
    
    found = []
    if r1: found.append(f"32 dir 0 (lat={r1.latitude}, lon={r1.longitude}, spd={r1.speed_kmh})")
    if r2: found.append(f"32 dir 1 (lat={r2.latitude}, lon={r2.longitude}, spd={r2.speed_kmh})")
    if r02_go: found.append(f"02 dir 0 (lat={r02_go.latitude}, lon={r02_go.longitude}, spd={r02_go.speed_kmh})")
    if r02_re: found.append(f"02 dir 1 (lat={r02_re.latitude}, lon={r02_re.longitude}, spd={r02_re.speed_kmh})")
    
    print(f"Plate {p}: {' | '.join(found) if found else 'NOT FOUND IN TIMBUS'}")
