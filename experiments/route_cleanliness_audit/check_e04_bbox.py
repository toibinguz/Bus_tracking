import sqlite3

conn = sqlite3.connect('data/hanoi_bus_system.db')
c = conn.cursor()

c.execute("SELECT direction, COUNT(1), min(lat), max(lat), min(lon), max(lon) FROM canonical_shape_master WHERE route_code = 'E04' GROUP BY direction")
for r in c.fetchall():
    print('Canonical E04 shape:', r)

c.execute("SELECT min(lat), max(lat), min(lon), max(lon), COUNT(1) FROM vehicle_unique_pings WHERE route_id = 101109")
print('E04 unique pings bbox:', c.fetchone())

# Compare TimBus shape vs Canonical BusMap shape for E04
c.execute("SELECT direction, COUNT(1), min(lat), max(lat), min(lon), max(lon) FROM timbus_shape_master WHERE route_code = 'E04' GROUP BY direction")
for r in c.fetchall():
    print('TimBus E04 shape:', r)

