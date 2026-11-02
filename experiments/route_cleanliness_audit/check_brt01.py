import sqlite3

conn = sqlite3.connect('data/hanoi_bus_system.db')
c = conn.cursor()

c.execute("SELECT route_id, route_code, point_count_go, point_count_re, station_count_go, station_count_re FROM canonical_route_master WHERE route_code = 'BRT01'")
print('Canonical BRT01:', c.fetchall())

c.execute("SELECT direction, count(1), min(lat), max(lat), min(lon), max(lon) FROM canonical_shape_master WHERE route_code = 'BRT01' GROUP BY direction")
print('Canonical BRT01 shapes:', c.fetchall())

c.execute("SELECT direction, count(1), min(lat), max(lat), min(lon), max(lon) FROM timbus_shape_master WHERE route_code = 'BRT01' GROUP BY direction")
print('TimBus BRT01 shapes:', c.fetchall())

