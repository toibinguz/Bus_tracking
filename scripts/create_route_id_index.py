import sqlite3
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('data/hanoi_bus_system.db')
cur = conn.cursor()

t0 = time.time()
cur.execute("SELECT count(*) FROM vehicle_unique_pings WHERE route_id = 2")
cnt = cur.fetchone()[0]
print(f"Without index: count={cnt:,} in {time.time()-t0:.3f}s")

# Let's create index
t0 = time.time()
print("Creating index idx_vup_route_id...")
cur.execute("CREATE INDEX IF NOT EXISTS idx_vup_route_id ON vehicle_unique_pings(route_id)")
conn.commit()
print(f"Index created in {time.time()-t0:.2f}s")

t0 = time.time()
cur.execute("SELECT count(*) FROM vehicle_unique_pings WHERE route_id = 2")
cnt = cur.fetchone()[0]
print(f"With index: count={cnt:,} in {time.time()-t0:.4f}s")

conn.close()

