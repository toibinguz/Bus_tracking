import sys
import os
sys.path.insert(0, os.path.abspath("."))
from experiments.timbus.timbus_tracker import TimBusClient

plate = "29F05281" # near Giáp Bát
print(f"Testing station queries for plate {plate}:")
# Let's test several stations: Giáp Bát (157), Nhổn (510), Kim Mã (283), Cầu Giấy (58), Giải Phóng (157)
for st in [157, 510, 283, 58, 240, 242]:
    for d in [0, 1]:
        rec = TimBusClient.query_targeted_vehicle(st, "32", plate, direction=d)
        if rec:
            print(f"FOUND with st={st}, dir={d}: lat={rec.latitude}, lon={rec.longitude}, spd={rec.speed_kmh}")
            break
    else:
        continue
    break
else:
    print("Not found with any tested station ID!")
