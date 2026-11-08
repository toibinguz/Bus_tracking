import sys, os, sqlite3
sys.path.insert(0, os.path.abspath('.'))
from experiments.timbus.timbus_tracker import TimBusClient

conn = sqlite3.connect('data/hanoi_bus_system.db')
c = conn.cursor()
c.execute("SELECT station_id, station_name FROM canonical_station_master WHERE route_code='32'")
stations = c.fetchall()
plate = '29F05241'
found = False
for sid, sname in stations[:20]:
    for d in [0, 1]:
        res = TimBusClient.query_targeted_vehicle(sid, '32', plate, direction=d)
        if res:
            print(f'FOUND with station {sid} ({sname}) dir={d}!')
            found = True
            break
    if found:
        break
if not found:
    print('Not found in tested stations.')
