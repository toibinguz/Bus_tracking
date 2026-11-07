"""
EDA 5: Deep-dive into why Tier 0 is 49.7% and why Routes 67, 92, 101A, 107 have Tier 3 cells.
"""
import os
import sqlite3
import sys
import pandas as pd

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "hanoi_bus_system.db")

conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query("SELECT * FROM agg_segment_travel_times", conn)

print("=" * 88)
print("1. WEEKDAY (15 TRAIN DAYS) vs WEEKEND (6 TRAIN DAYS) BREAKDOWN")
print("=" * 88)
for wknd_val, wknd_lbl in [(0, "Weekday (Mon-Fri, 15 Train days)"), (1, "Weekend (Sat-Sun, 6 Train days)")]:
    sub = df[df["is_weekend"] == wknd_val]
    sub_day = sub[sub["hour_slot"].between(6, 20)]
    print(f"  * {wknd_lbl} (All hours 05..22, {len(sub):,} cells):")
    print(f"    - Tier 0 (N>=10) : {(sub['quality_tier']==0).mean()*100:>5.1f}% | Tier 1 (3..9): {(sub['quality_tier']==1).mean()*100:>5.1f}% | Tier 0+1: {(sub['quality_tier'].isin([0,1])).mean()*100:>5.1f}% | Median N={sub['sample_count'].median():.0f}")
    print(f"  * {wknd_lbl} (Operating Daytime 06..20, {len(sub_day):,} cells):")
    print(f"    - Tier 0 (N>=10) : {(sub_day['quality_tier']==0).mean()*100:>5.1f}% | Tier 1 (3..9): {(sub_day['quality_tier']==1).mean()*100:>5.1f}% | Tier 0+1: {(sub_day['quality_tier'].isin([0,1])).mean()*100:>5.1f}% | Median N={sub_day['sample_count'].median():.0f}")

print("\n" + "=" * 88)
print("2. WHY DO ROUTES 67, 92, 101A, 107 HAVE HIGH TIER 3? (FLEET SIZE & S_BUS_M COVERAGE)")
print("=" * 88)
for rc in ["67", "92", "101A", "107", "E11", "02"]:
    tel = conn.execute(
        "SELECT direction, COUNT(DISTINCT vehicle_id), COUNT(*), ROUND(MIN(s_bus_m),1), ROUND(MAX(s_bus_m),1) FROM route_projected_telemetry WHERE route_code=? GROUP BY direction",
        (rc,),
    ).fetchall()
    st = conn.execute(
        "SELECT direction, COUNT(*), ROUND(MIN(cum_distance_m),1), ROUND(MAX(cum_distance_m),1) FROM canonical_station_master WHERE route_code=? GROUP BY direction",
        (rc,),
    ).fetchall()
    print(f"  * Route {rc:<5}:")
    print(f"    - Telemetry (dir, buses, pings, min_s, max_s) : {tel}")
    print(f"    - Stations  (dir, count, min_s, max_s)        : {st}")

print("\n" + "=" * 88)
print("3. ANATOMY OF THE REMAINING 134 TIER-3 STATION SEGMENTS (OUT OF 3,522 TOTAL SEGMENTS)")
print("=" * 88)
t3_segs = (
    df[df["quality_tier"] == 3]
    .groupby(["route_code", "direction", "from_station_order", "to_station_order", "from_station_name", "to_station_name", "segment_length_m"])
    .size()
    .reset_index(name="n_cells")
)
max_ord_map = df.groupby(["route_code", "direction"])["to_station_order"].max().to_dict()
t3_segs["max_ord"] = t3_segs.apply(lambda r: max_ord_map[(r["route_code"], r["direction"])], axis=1)
t3_segs["is_terminal_edge"] = (t3_segs["from_station_order"] <= 1) | (t3_segs["to_station_order"] >= t3_segs["max_ord"] - 1)
print(f"  * Total unique station segments in network : {len(df)//36:,}")
print(f"  * Unique station segments in Tier 3        : {len(t3_segs):,} ({len(t3_segs)/(len(df)//36)*100:.2f}%)")
print(f"    - First/Last terminal boundary segments  : {int(t3_segs['is_terminal_edge'].sum()):,} / {len(t3_segs):,} ({t3_segs['is_terminal_edge'].mean()*100:.1f}%)")
print(f"    - Interior detour / variant segments     : {int((~t3_segs['is_terminal_edge']).sum()):,} / {len(t3_segs):,}")
for rc, grp in t3_segs[~t3_segs["is_terminal_edge"]].groupby("route_code"):
    ords = sorted(grp["from_station_order"].unique().tolist())
    print(f"      -> Route {rc:<5}: {len(grp):>2} interior segments | orders={ords}")

conn.close()
