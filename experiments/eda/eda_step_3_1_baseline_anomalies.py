"""
EDA & Anomaly Forensics on Step 3.1 (Trip Segmentation) & Step 3.2 (Baseline Matrix)
Analyzes:
1. Why is multi-station sum(P50) positively biased (+57s on >15 stations) vs sum(mean)?
   Compares sum(tt_p50_sec) vs sum(tt_mean_sec) on multi-station horizons.
2. Why are 15,804 cells (12.5%) in Tier 3 (0 historical samples)?
   Breaks down Tier 3 cells by:
   - Station position (origin terminal k=0, destination terminal k=N-2, mid-route)
   - Hour slot (05:00, 21:00, 22:00 vs daytime 06:00-20:00)
   - Specific routes with high Tier 3 ratio
3. Trip Span & Station Coverage EDA across the 102,496 trips:
   - Distribution of trip start position s_start and trip end position s_end relative to route length L.
   - How many segments are skipped due to Bracketing Guard (dt > 150s or ds > 1000m) vs speed bounds (1.5..65 km/h).
"""

import os
import sqlite3
import sys
import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.join(BASE_DIR, "data", "hanoi_bus_system.db")


def run_eda_baseline():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM agg_segment_travel_times", conn)
    st_df = pd.read_sql_query(
        "SELECT route_code, direction, MAX(station_order) AS max_ord, COUNT(*) AS n_st FROM canonical_station_master GROUP BY route_code, direction",
        conn,
    )
    conn.close()

    df = df.merge(st_df, on=["route_code", "direction"], how="left")
    df["implied_speed_p50_kmh"] = (df["segment_length_m"] / df["tt_p50_sec"]) * 3.6
    df["implied_speed_mean_kmh"] = (df["segment_length_m"] / df["tt_mean_sec"]) * 3.6
    df["mean_minus_p50_sec"] = df["tt_mean_sec"] - df["tt_p50_sec"]
    df["p90_to_p50_ratio"] = df["tt_p90_sec"] / np.maximum(1.0, df["tt_p50_sec"])

    print("\n" + "=" * 88)
    print("EDA 5: WHY IS TIER 0 AT 49.7%? (WEEKDAY vs WEEKEND & SUBURBAN CORRIDOR ANALYSIS)")
    print("=" * 88)
    for wknd_val, wknd_lbl in [(0, "Weekday (15 Train days)"), (1, "Weekend (6 Train days)")]:
        sub_w = df[(df["is_weekend"] == wknd_val) & (df["hour_slot"].between(6, 20))]
        t0_p = (sub_w["quality_tier"] == 0).mean() * 100
        t01_p = (sub_w["quality_tier"].isin([0, 1])).mean() * 100
        t2_p = (sub_w["quality_tier"] == 2).mean() * 100
        t3_p = (sub_w["quality_tier"] == 3).mean() * 100
        print(
            f"  * {wknd_lbl:<25} (Hours 06..20): "
            f"Tier 0 (N>=10)={t0_p:>5.1f}% | Tier 0+1 (N>=3)={t01_p:>5.1f}% | "
            f"Tier 2={t2_p:>5.1f}% | Tier 3={t3_p:>5.1f}% | Med N={sub_w['sample_count'].median():>4.0f}"
        )

    conn = sqlite3.connect(DB_PATH)
    for rc in ["67", "92", "101A", "107", "02"]:
        tel_min_max = conn.execute(
            "SELECT direction, MIN(s_bus_m), MAX(s_bus_m), COUNT(*) FROM route_projected_telemetry WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        st_min_max = conn.execute(
            "SELECT direction, MIN(cum_distance_m), MAX(cum_distance_m), COUNT(*) FROM canonical_station_master WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        print(f"  * Route {rc:<5} Telemetry s_bus_m: {tel_min_max} | Stations cum_dist_m: {st_min_max}")
    conn.close()
    print("=" * 88)
    print("EDA 1: OVERALL BASELINE MATRIX DISTRIBUTION (126,792 CELLS)")
    print("\n" + "=" * 88)
    print("EDA 5: WHY IS TIER 0 AT 49.7%? (WEEKDAY vs WEEKEND & SUBURBAN CORRIDOR ANALYSIS)")
    print("=" * 88)
    for wknd_val, wknd_lbl in [(0, "Weekday (15 Train days)"), (1, "Weekend (6 Train days)")]:
        sub_w = df[(df["is_weekend"] == wknd_val) & (df["hour_slot"].between(6, 20))]
        t0_p = (sub_w["quality_tier"] == 0).mean() * 100
        t01_p = (sub_w["quality_tier"].isin([0, 1])).mean() * 100
        t2_p = (sub_w["quality_tier"] == 2).mean() * 100
        t3_p = (sub_w["quality_tier"] == 3).mean() * 100
        print(
            f"  * {wknd_lbl:<25} (Hours 06..20): "
            f"Tier 0 (N>=10)={t0_p:>5.1f}% | Tier 0+1 (N>=3)={t01_p:>5.1f}% | "
            f"Tier 2={t2_p:>5.1f}% | Tier 3={t3_p:>5.1f}% | Med N={sub_w['sample_count'].median():>4.0f}"
        )

    conn = sqlite3.connect(DB_PATH)
    for rc in ["67", "92", "101A", "107", "02"]:
        tel_min_max = conn.execute(
            "SELECT direction, MIN(s_bus_m), MAX(s_bus_m), COUNT(*) FROM route_projected_telemetry WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        st_min_max = conn.execute(
            "SELECT direction, MIN(cum_distance_m), MAX(cum_distance_m), COUNT(*) FROM canonical_station_master WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        print(f"  * Route {rc:<5} Telemetry s_bus_m: {tel_min_max} | Stations cum_dist_m: {st_min_max}")
    conn.close()
    print("=" * 88)
    for tier in sorted(df["quality_tier"].unique()):
        sub = df[df["quality_tier"] == tier]
        print(
            f"  * Tier {tier}: {len(sub):>6,} cells ({len(sub)/len(df)*100:>5.1f}%) | "
            f"Med N={sub['sample_count'].median():>4.0f} | "
            f"Med SegLen={sub['segment_length_m'].median():>5.1f}m | "
            f"Med P50={sub['tt_p50_sec'].median():>5.1f}s ({sub['implied_speed_p50_kmh'].median():>4.1f} km/h) | "
            f"Med(Mean-P50)={sub['mean_minus_p50_sec'].median():>+5.2f}s"
        )

    print("\n" + "=" * 88)
    print("EDA 2: ANOMALY 1 — RIGHT-SKEWNESS (MEAN vs P50 ADDITIVITY IN MULTI-STATION ETA)")
    print("\n" + "=" * 88)
    print("EDA 5: WHY IS TIER 0 AT 49.7%? (WEEKDAY vs WEEKEND & SUBURBAN CORRIDOR ANALYSIS)")
    print("=" * 88)
    for wknd_val, wknd_lbl in [(0, "Weekday (15 Train days)"), (1, "Weekend (6 Train days)")]:
        sub_w = df[(df["is_weekend"] == wknd_val) & (df["hour_slot"].between(6, 20))]
        t0_p = (sub_w["quality_tier"] == 0).mean() * 100
        t01_p = (sub_w["quality_tier"].isin([0, 1])).mean() * 100
        t2_p = (sub_w["quality_tier"] == 2).mean() * 100
        t3_p = (sub_w["quality_tier"] == 3).mean() * 100
        print(
            f"  * {wknd_lbl:<25} (Hours 06..20): "
            f"Tier 0 (N>=10)={t0_p:>5.1f}% | Tier 0+1 (N>=3)={t01_p:>5.1f}% | "
            f"Tier 2={t2_p:>5.1f}% | Tier 3={t3_p:>5.1f}% | Med N={sub_w['sample_count'].median():>4.0f}"
        )

    conn = sqlite3.connect(DB_PATH)
    for rc in ["67", "92", "101A", "107", "02"]:
        tel_min_max = conn.execute(
            "SELECT direction, MIN(s_bus_m), MAX(s_bus_m), COUNT(*) FROM route_projected_telemetry WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        st_min_max = conn.execute(
            "SELECT direction, MIN(cum_distance_m), MAX(cum_distance_m), COUNT(*) FROM canonical_station_master WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        print(f"  * Route {rc:<5} Telemetry s_bus_m: {tel_min_max} | Stations cum_dist_m: {st_min_max}")
    conn.close()
    print("=" * 88)
    t01 = df[df["quality_tier"].isin([0, 1])]
    print(f"  * Across {len(t01):,} measured cells (Tier 0 & 1):")
    print(f"    - Average (tt_mean_sec - tt_p50_sec) per segment : {t01['mean_minus_p50_sec'].mean():+.2f}s")
    print(f"    - Median  (tt_mean_sec - tt_p50_sec) per segment : {t01['mean_minus_p50_sec'].median():+.2f}s")
    print(f"    - P90     (tt_mean_sec - tt_p50_sec) per segment : {np.percentile(t01['mean_minus_p50_sec'], 90):+.2f}s")
    print(f"    - Implication over 20 segments: 20 * {t01['mean_minus_p50_sec'].mean():.2f}s = +{20 * t01['mean_minus_p50_sec'].mean():.1f}s systematic underestimation if summing P50 instead of Mean!")

    print("\n" + "=" * 88)
    print("EDA 3: ANOMALY 2 — ANATOMY OF THE 15,804 TIER-3 FALLBACK CELLS (WHY N=0?)")
    print("\n" + "=" * 88)
    print("EDA 5: WHY IS TIER 0 AT 49.7%? (WEEKDAY vs WEEKEND & SUBURBAN CORRIDOR ANALYSIS)")
    print("=" * 88)
    for wknd_val, wknd_lbl in [(0, "Weekday (15 Train days)"), (1, "Weekend (6 Train days)")]:
        sub_w = df[(df["is_weekend"] == wknd_val) & (df["hour_slot"].between(6, 20))]
        t0_p = (sub_w["quality_tier"] == 0).mean() * 100
        t01_p = (sub_w["quality_tier"].isin([0, 1])).mean() * 100
        t2_p = (sub_w["quality_tier"] == 2).mean() * 100
        t3_p = (sub_w["quality_tier"] == 3).mean() * 100
        print(
            f"  * {wknd_lbl:<25} (Hours 06..20): "
            f"Tier 0 (N>=10)={t0_p:>5.1f}% | Tier 0+1 (N>=3)={t01_p:>5.1f}% | "
            f"Tier 2={t2_p:>5.1f}% | Tier 3={t3_p:>5.1f}% | Med N={sub_w['sample_count'].median():>4.0f}"
        )

    conn = sqlite3.connect(DB_PATH)
    for rc in ["67", "92", "101A", "107", "02"]:
        tel_min_max = conn.execute(
            "SELECT direction, MIN(s_bus_m), MAX(s_bus_m), COUNT(*) FROM route_projected_telemetry WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        st_min_max = conn.execute(
            "SELECT direction, MIN(cum_distance_m), MAX(cum_distance_m), COUNT(*) FROM canonical_station_master WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        print(f"  * Route {rc:<5} Telemetry s_bus_m: {tel_min_max} | Stations cum_dist_m: {st_min_max}")
    conn.close()
    print("=" * 88)
    t3 = df[df["quality_tier"] == 3].copy()
    is_first_seg = t3["from_station_order"] == 0
    is_second_seg = t3["from_station_order"] == 1
    is_last_seg = t3["to_station_order"] == t3["max_ord"]
    is_Boundary_hour = t3["hour_slot"].isin([5, 21, 22])

    print(f"  * Total Tier 3 cells: {len(t3):,} / {len(df):,} ({len(t3)/len(df)*100:.2f}%)")
    print(f"    - At Origin Terminal Segment 0 (st 0 -> 1)    : {is_first_seg.sum():>6,} cells ({is_first_seg.mean()*100:>5.1f}% of Tier 3)")
    print(f"    - At Origin Segment 1 (st 1 -> 2)             : {is_second_seg.sum():>6,} cells ({is_second_seg.mean()*100:>5.1f}% of Tier 3)")
    print(f"    - At Destination Final Segment (N-1 -> N)     : {is_last_seg.sum():>6,} cells ({is_last_seg.mean()*100:>5.1f}% of Tier 3)")
    mid_t3 = t3[~is_first_seg & ~is_second_seg & ~is_last_seg]
    print(f"    - At Mid-Route Segments (2 .. N-2)            : {len(mid_t3):>6,} cells ({len(mid_t3)/len(t3)*100:>5.1f}% of Tier 3)")

    print("\n  * Tier 3 rate by Station Position across ALL cells:")
    df["pos_cat"] = "Mid-Route (2..N-2)"
    df.loc[df["from_station_order"] == 0, "pos_cat"] = "Origin Seg 0 (0->1)"
    df.loc[df["from_station_order"] == 1, "pos_cat"] = "Origin Seg 1 (1->2)"
    df.loc[df["to_station_order"] == df["max_ord"], "pos_cat"] = "Dest Last Seg (N-1->N)"
    for cat, grp in df.groupby("pos_cat"):
        t3_pct = (grp["quality_tier"] == 3).mean() * 100
        t01_pct = (grp["quality_tier"].isin([0, 1])).mean() * 100
        print(f"    - {cat:<24}: Total={len(grp):>6,} | Tier 0/1={t01_pct:>5.1f}% | Tier 3={t3_pct:>5.1f}%")

    print("\n  * Tier 3 rate by Operating Hour Slot (5..22):")
    for hr, grp in df.groupby("hour_slot"):
        if hr in (5, 6, 7, 8, 12, 17, 18, 20, 21, 22):
            t3_pct = (grp["quality_tier"] == 3).mean() * 100
            t0_pct = (grp["quality_tier"] == 0).mean() * 100
            print(f"    - Hour {hr:02d}:00 : Tier 0={t0_pct:>5.1f}% | Tier 3={t3_pct:>5.1f}% | Avg Samples/Cell={grp['sample_count'].mean():>5.1f}")

    print("\n" + "=" * 88)
    print("EDA 4: ANOMALY 3 — HIGH-VARIANCE BOTTLENECK SEGMENTS & MICRO-SEGMENTS")
    print("\n" + "=" * 88)
    print("EDA 5: WHY IS TIER 0 AT 49.7%? (WEEKDAY vs WEEKEND & SUBURBAN CORRIDOR ANALYSIS)")
    print("=" * 88)
    for wknd_val, wknd_lbl in [(0, "Weekday (15 Train days)"), (1, "Weekend (6 Train days)")]:
        sub_w = df[(df["is_weekend"] == wknd_val) & (df["hour_slot"].between(6, 20))]
        t0_p = (sub_w["quality_tier"] == 0).mean() * 100
        t01_p = (sub_w["quality_tier"].isin([0, 1])).mean() * 100
        t2_p = (sub_w["quality_tier"] == 2).mean() * 100
        t3_p = (sub_w["quality_tier"] == 3).mean() * 100
        print(
            f"  * {wknd_lbl:<25} (Hours 06..20): "
            f"Tier 0 (N>=10)={t0_p:>5.1f}% | Tier 0+1 (N>=3)={t01_p:>5.1f}% | "
            f"Tier 2={t2_p:>5.1f}% | Tier 3={t3_p:>5.1f}% | Med N={sub_w['sample_count'].median():>4.0f}"
        )

    conn = sqlite3.connect(DB_PATH)
    for rc in ["67", "92", "101A", "107", "02"]:
        tel_min_max = conn.execute(
            "SELECT direction, MIN(s_bus_m), MAX(s_bus_m), COUNT(*) FROM route_projected_telemetry WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        st_min_max = conn.execute(
            "SELECT direction, MIN(cum_distance_m), MAX(cum_distance_m), COUNT(*) FROM canonical_station_master WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        print(f"  * Route {rc:<5} Telemetry s_bus_m: {tel_min_max} | Stations cum_dist_m: {st_min_max}")
    conn.close()
    print("=" * 88)
    short_segs = df[(df["segment_length_m"] <= 50.0) & (df["hour_slot"] == 8) & (df["is_weekend"] == 0)]
    long_segs = df[(df["segment_length_m"] > 1000.0) & (df["hour_slot"] == 8) & (df["is_weekend"] == 0)]
    print(f"  * Very short station pairs (<= 50m)  : {len(short_segs):>4} segments (e.g. min={df['segment_length_m'].min():.1f}m)")
    print(f"  * Long station pairs (> 1000m)       : {len(long_segs):>4} segments (max={df['segment_length_m'].max():.1f}m) -> Wait! Bracketing Guard BRACKET_MAX_DS_M=1000m blocks segments > 1000m if crossed in 1 step!")
    t3_long = df[df["segment_length_m"] > 800.0]
    print(f"    - Tier 3 rate for segments > 800m  : {(t3_long['quality_tier']==3).mean()*100:.1f}% vs segments <= 800m: {(df[df['segment_length_m']<=800.0]['quality_tier']==3).mean()*100:.1f}%")

    print("\n  * Top 8 Routes with Highest Tier-3 Fallback Percentage:")
    r_summary = (
        df.groupby("route_code")
        .agg(
            total_cells=("quality_tier", "count"),
            tier01_pct=("quality_tier", lambda s: s.isin([0, 1]).mean() * 100),
            tier3_pct=("quality_tier", lambda s: (s == 3).mean() * 100),
            avg_samples=("sample_count", "mean"),
            max_seg_len=("segment_length_m", "max"),
        )
        .sort_values("tier3_pct", ascending=False)
    )
    for rc, row in r_summary.head(8).iterrows():
        print(
            f"    - Route {rc:<6}: Tier0/1={row['tier01_pct']:>5.1f}% | Tier3={row['tier3_pct']:>5.1f}% | "
            f"Avg Samples/Cell={row['avg_samples']:>5.1f} | Max SegLen={row['max_seg_len']:>6.1f}m"
        )
    print("\n" + "=" * 88)
    print("EDA 5: WHY IS TIER 0 AT 49.7%? (WEEKDAY vs WEEKEND & SUBURBAN CORRIDOR ANALYSIS)")
    print("=" * 88)
    for wknd_val, wknd_lbl in [(0, "Weekday (15 Train days)"), (1, "Weekend (6 Train days)")]:
        sub_w = df[(df["is_weekend"] == wknd_val) & (df["hour_slot"].between(6, 20))]
        t0_p = (sub_w["quality_tier"] == 0).mean() * 100
        t01_p = (sub_w["quality_tier"].isin([0, 1])).mean() * 100
        t2_p = (sub_w["quality_tier"] == 2).mean() * 100
        t3_p = (sub_w["quality_tier"] == 3).mean() * 100
        print(
            f"  * {wknd_lbl:<25} (Hours 06..20): "
            f"Tier 0 (N>=10)={t0_p:>5.1f}% | Tier 0+1 (N>=3)={t01_p:>5.1f}% | "
            f"Tier 2={t2_p:>5.1f}% | Tier 3={t3_p:>5.1f}% | Med N={sub_w['sample_count'].median():>4.0f}"
        )

    conn = sqlite3.connect(DB_PATH)
    for rc in ["67", "92", "101A", "107", "02"]:
        tel_min_max = conn.execute(
            "SELECT direction, MIN(s_bus_m), MAX(s_bus_m), COUNT(*) FROM route_projected_telemetry WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        st_min_max = conn.execute(
            "SELECT direction, MIN(cum_distance_m), MAX(cum_distance_m), COUNT(*) FROM canonical_station_master WHERE route_code=? GROUP BY direction",
            (rc,),
        ).fetchall()
        print(f"  * Route {rc:<5} Telemetry s_bus_m: {tel_min_max} | Stations cum_dist_m: {st_min_max}")
    conn.close()
    print("=" * 88)


if __name__ == "__main__":
    run_eda_baseline()
