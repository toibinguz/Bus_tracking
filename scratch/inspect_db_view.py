import sqlite3
import time
import os

DB_PATH = "data/hanoi_bus_system.db"

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}")
    exit(1)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

print("=== TABLES & ROW COUNTS ===")
tables = cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
for name, typ in tables:
    if typ == 'table':
        cnt = cur.execute(f"SELECT count(1) FROM {name}").fetchone()[0]
        print(f"Table {name:<35}: {cnt:,} rows")
    else:
        print(f"View  {name:<35}")

print("\n=== INDEXES ===")
indexes = cur.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index'").fetchall()
for name, tbl, sql in indexes:
    print(f"Index {name} on {tbl}: {sql}")

print("\n=== TEST VIEW QUERY PERFORMANCE ===")
# Test EXPLAIN QUERY PLAN for v_bus_to_next_station
explain_sql = """
EXPLAIN QUERY PLAN
SELECT * FROM v_bus_to_next_station LIMIT 100;
"""
print("EXPLAIN QUERY PLAN for v_bus_to_next_station LIMIT 100:")
for row in cur.execute(explain_sql).fetchall():
    print(" ", row)

# Test query with LIMIT 10
t0 = time.time()
sample_rows = cur.execute("SELECT * FROM v_bus_to_next_station LIMIT 10;").fetchall()
t_limit10 = time.time() - t0
print(f"\nSELECT * FROM v_bus_to_next_station LIMIT 10 executed in {t_limit10*1000:.2f} ms")
for r in sample_rows[:2]:
    print(" Sample row:", r)

# Test query for a specific vehicle or route
t0 = time.time()
route_rows = cur.execute("SELECT * FROM v_bus_to_next_station WHERE route_code = '01' LIMIT 100;").fetchall()
t_route = time.time() - t0
print(f"SELECT for route '01' LIMIT 100 executed in {t_route*1000:.2f} ms (rows: {len(route_rows)})")

# Test total count on view
print("\nTesting SELECT COUNT(1) FROM v_bus_to_next_station (with timeout tracking)...")
t0 = time.time()
try:
    total_view_rows = cur.execute("SELECT count(1) FROM v_bus_to_next_station;").fetchone()[0]
    t_full = time.time() - t0
    print(f"Full view count: {total_view_rows:,} rows in {t_full:.3f} s")
except Exception as e:
    print(f"Error executing full view count: {e}")
