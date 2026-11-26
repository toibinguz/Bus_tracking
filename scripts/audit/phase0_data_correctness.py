"""
Giai đoạn 0 — Kiểm định Tính đúng đắn của Dữ liệu (Read-Only Data Correctness Audit).

Tuyệt đối chỉ đọc (mode=ro) trên SQLite và Parquet trong data/ & experiments/.
Xuất evidence ra:
  - docs/evidence/codebase_audit_20261126/00_data_correctness.json
  - docs/evidence/codebase_audit_20261126/00_data_correctness.md
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
MAIN_DB = ROOT / "data" / "hanoi_bus_system.db"
TIMBUS_DB = ROOT / "experiments" / "timbus" / "timbus_hanoi.sqlite"
OUT_DIR = ROOT / "docs" / "evidence" / "codebase_audit_20261126"

TZ_HANOI = timezone(timedelta(hours=7))
HANOI_BBOX = {
    "min_lat": 19.50,
    "max_lat": 22.50,
    "min_lon": 104.50,
    "max_lon": 107.50,
}


def ro_connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def fmt_hn(epoch: float | int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=TZ_HANOI).strftime("%Y-%m-%d %H:%M:%S%z")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def norm_dir(val: Any) -> str:
    s = str(val).strip().lower()
    if s in ("1", "re", "chiều về", "chieu ve", "chieure", "return", "back"):
        return "re"
    return "go"


# ---------------------------------------------------------------------------
# D1: Canonical Geometry
# ---------------------------------------------------------------------------
def audit_d1_geometry(con: sqlite3.Connection) -> dict[str, Any]:
    baseline_routes = {
        r[0]
        for r in con.execute("SELECT DISTINCT route_code FROM agg_segment_travel_times ORDER BY route_code")
    }
    total_routes = con.execute("SELECT COUNT(*) FROM canonical_route_master").fetchone()[0]
    total_stations = con.execute("SELECT COUNT(*) FROM canonical_station_master").fetchone()[0]
    total_shapes = con.execute("SELECT COUNT(*) FROM canonical_shape_master").fetchone()[0]

    # Station checks
    st_rows = con.execute(
        """
        SELECT route_id, route_code, direction, station_order, station_id, station_name,
               lat, lon, cum_distance_m, snap_dist_m
        FROM canonical_station_master
        ORDER BY route_id, direction, station_order
        """
    ).fetchall()

    non_mono_all: list[dict[str, Any]] = []
    non_mono_base: list[dict[str, Any]] = []
    order_anomalies: list[dict[str, Any]] = []
    short_segs: list[dict[str, Any]] = []
    long_segs: list[dict[str, Any]] = []
    snap_gt_35_all = 0
    snap_gt_100_all = 0
    snap_gt_35_base = 0
    snap_gt_100_base = 0
    worst_snaps: list[dict[str, Any]] = []

    groups: dict[tuple[int, str, str], list[sqlite3.Row]] = {}
    for r in st_rows:
        is_base = r["route_code"] in baseline_routes
        snap = float(r["snap_dist_m"] or 0.0)
        if snap > 35.0:
            snap_gt_35_all += 1
            if is_base:
                snap_gt_35_base += 1
            worst_snaps.append(
                {
                    "route_id": r["route_id"],
                    "route_code": r["route_code"],
                    "is_baseline": is_base,
                    "direction": r["direction"],
                    "station_order": r["station_order"],
                    "station_name": r["station_name"],
                    "snap_dist_m": round(snap, 2),
                }
            )
        if snap > 100.0:
            snap_gt_100_all += 1
            if is_base:
                snap_gt_100_base += 1
        groups.setdefault((r["route_id"], r["route_code"], r["direction"]), []).append(r)

    for (rid, rcode, d), pts in groups.items():
        is_base = rcode in baseline_routes
        orders = [int(p["station_order"]) for p in pts]
        if len(orders) != len(set(orders)) or orders != list(range(orders[0], orders[0] + len(orders))):
            order_anomalies.append(
                {"route_id": rid, "route_code": rcode, "direction": d, "is_baseline": is_base, "orders_head": orders[:10], "count": len(orders)}
            )
        for i in range(1, len(pts)):
            prev, curr = pts[i - 1], pts[i]
            ds = float(curr["cum_distance_m"]) - float(prev["cum_distance_m"])
            if ds <= 0.0:
                item = {
                    "route_id": rid,
                    "route_code": rcode,
                    "direction": d,
                    "is_baseline": is_base,
                    "prev_order": prev["station_order"],
                    "curr_order": curr["station_order"],
                    "prev_name": prev["station_name"],
                    "curr_name": curr["station_name"],
                    "prev_s_m": round(float(prev["cum_distance_m"]), 2),
                    "curr_s_m": round(float(curr["cum_distance_m"]), 2),
                    "ds_m": round(ds, 2),
                }
                non_mono_all.append(item)
                if is_base:
                    non_mono_base.append(item)
            elif ds < 50.0:
                short_segs.append(
                    {"route_code": rcode, "direction": d, "is_baseline": is_base, "from_order": prev["station_order"], "to_order": curr["station_order"], "ds_m": round(ds, 2)}
                )
            elif ds > 5000.0:
                long_segs.append(
                    {"route_code": rcode, "direction": d, "is_baseline": is_base, "from_order": prev["station_order"], "to_order": curr["station_order"], "from_name": prev["station_name"], "to_name": curr["station_name"], "ds_m": round(ds, 2)}
                )

    worst_snaps.sort(key=lambda x: x["snap_dist_m"], reverse=True)
    non_mono_all.sort(key=lambda x: x["ds_m"])

    # Shape checks via SQL aggregation
    shape_oob = con.execute(
        """
        SELECT COUNT(*) FROM canonical_shape_master
        WHERE lat < ? OR lat > ? OR lon < ? OR lon > ? OR lat IS NULL OR lon IS NULL
        """,
        (HANOI_BBOX["min_lat"], HANOI_BBOX["max_lat"], HANOI_BBOX["min_lon"], HANOI_BBOX["max_lon"]),
    ).fetchone()[0]

    shape_non_mono = con.execute(
        """
        WITH s AS (
            SELECT route_id, route_code, direction, point_order, cum_distance_m,
                   LAG(cum_distance_m) OVER (PARTITION BY route_id, direction ORDER BY point_order) AS prev_s
            FROM canonical_shape_master
        )
        SELECT COUNT(*) FROM s WHERE prev_s IS NOT NULL AND cum_distance_m < prev_s - 1e-6
        """
    ).fetchone()[0]

    return {
        "baseline_route_count": len(baseline_routes),
        "total_canonical_routes": total_routes,
        "total_canonical_stations": total_stations,
        "total_canonical_shapes": total_shapes,
        "station_non_monotonic_count_all": len(non_mono_all),
        "station_non_monotonic_count_baseline": len(non_mono_base),
        "station_non_monotonic_samples": non_mono_all[:15],
        "station_order_anomalies_count": len(order_anomalies),
        "station_order_anomalies_samples": order_anomalies[:10],
        "station_snap_gt_35m_all": snap_gt_35_all,
        "station_snap_gt_35m_baseline": snap_gt_35_base,
        "station_snap_gt_100m_all": snap_gt_100_all,
        "station_snap_gt_100m_baseline": snap_gt_100_base,
        "worst_snap_stations_top15": worst_snaps[:15],
        "short_segments_lt_50m_all": len(short_segs),
        "short_segments_lt_50m_baseline": sum(1 for x in short_segs if x["is_baseline"]),
        "long_segments_gt_5000m_all": len(long_segs),
        "long_segments_gt_5000m_baseline": sum(1 for x in long_segs if x["is_baseline"]),
        "long_segments_samples": sorted(long_segs, key=lambda x: x["ds_m"], reverse=True)[:10],
        "shape_oob_count": shape_oob,
        "shape_non_monotonic_count": shape_non_mono,
    }


# ---------------------------------------------------------------------------
# D2: Silver Telemetry & Gold Feature Store
# ---------------------------------------------------------------------------
def audit_d2_telemetry_and_features(con: sqlite3.Connection, ddb: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    baseline_routes = {
        r[0]
        for r in con.execute("SELECT DISTINCT route_code FROM agg_segment_travel_times ORDER BY route_code")
    }

    silver_glob = (ROOT / "data/lakehouse/silver/route_projected_telemetry/route_code=*/dt=*/*.parquet").as_posix()
    silver_stats = ddb.execute(
        f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT route_code) AS distinct_routes,
            MIN(device_epoch) AS min_epoch,
            MAX(device_epoch) AS max_epoch,
            SUM(CASE WHEN cross_track_m > 35.0 THEN 1 ELSE 0 END) AS ct_gt_35,
            SUM(CASE WHEN s_bus_m < 0 THEN 1 ELSE 0 END) AS s_lt_0,
            SUM(CASE WHEN derived_speed_kmh < 0 OR derived_speed_kmh > 80.0 THEN 1 ELSE 0 END) AS speed_oob,
            SUM(CASE WHEN route_id IS NULL OR vehicle_id IS NULL OR device_epoch IS NULL OR s_bus_m IS NULL THEN 1 ELSE 0 END) AS nulls
        FROM read_parquet('{silver_glob}', hive_partitioning=true)
        """
    ).fetchone()

    silver_dups = ddb.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT route_id, vehicle_id, device_epoch, COUNT(*) AS c
            FROM read_parquet('{silver_glob}', hive_partitioning=true)
            GROUP BY 1, 2, 3
            HAVING c > 1
        )
        """
    ).fetchone()[0]

    silver_cov_rows = ddb.execute(
        f"""
        SELECT route_code, direction, COUNT(*) AS cnt
        FROM read_parquet('{silver_glob}', hive_partitioning=true)
        GROUP BY 1, 2
        """
    ).fetchall()
    cov_map: dict[str, dict[str, int]] = {}
    for rc, dr, cnt in silver_cov_rows:
        cov_map.setdefault(str(rc), {})[str(dr)] = int(cnt)

    missing_dir_routes = []
    for rc in sorted(baseline_routes):
        dirs = cov_map.get(rc, {})
        if dirs.get("go", 0) == 0 or dirs.get("re", 0) == 0:
            missing_dir_routes.append({"route_code": rc, "go": dirs.get("go", 0), "re": dirs.get("re", 0)})

    # Compare with SQLite route_projected_telemetry
    sqlite_tel = con.execute(
        """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT route_code) AS distinct_routes,
               MIN(device_epoch) AS min_epoch, MAX(device_epoch) AS max_epoch
        FROM route_projected_telemetry
        """
    ).fetchone()

    # Gold eta_feature_store
    fs_glob = (ROOT / "data/lakehouse/gold/eta_feature_store/split=*/route_code=*/*.parquet").as_posix()
    fs_splits = ddb.execute(
        f"""
        SELECT
            split,
            COUNT(*) AS rows,
            COUNT(DISTINCT route_code) AS distinct_routes,
            MIN(dt) AS min_dt,
            MAX(dt) AS max_dt,
            MIN(device_epoch) AS min_epoch,
            MAX(device_epoch) AS max_epoch,
            SUM(CASE WHEN actual_eta_sec <= 0 THEN 1 ELSE 0 END) AS eta_le_0,
            SUM(CASE WHEN actual_eta_sec > 3600 THEN 1 ELSE 0 END) AS eta_gt_3600,
            SUM(CASE WHEN actual_eta_sec IS NULL OR isnan(actual_eta_sec) THEN 1 ELSE 0 END) AS eta_nan,
            QUANTILE_CONT(actual_eta_sec, 0.01) AS p01,
            QUANTILE_CONT(actual_eta_sec, 0.50) AS p50,
            QUANTILE_CONT(actual_eta_sec, 0.95) AS p95,
            QUANTILE_CONT(actual_eta_sec, 0.99) AS p99,
            MAX(actual_eta_sec) AS max_eta
        FROM read_parquet('{fs_glob}', hive_partitioning=true)
        GROUP BY split
        ORDER BY split
        """
    ).fetchall()

    splits_out = {}
    for row in fs_splits:
        splits_out[row[0]] = {
            "rows": int(row[1]),
            "distinct_routes": int(row[2]),
            "min_dt": row[3],
            "max_dt": row[4],
            "min_epoch_hn": fmt_hn(row[5]),
            "max_epoch_hn": fmt_hn(row[6]),
            "min_epoch": row[5],
            "max_epoch": row[6],
            "eta_le_0": int(row[7]),
            "eta_gt_3600": int(row[8]),
            "eta_nan": int(row[9]),
            "p01": round(float(row[10]), 2),
            "p50": round(float(row[11]), 2),
            "p95": round(float(row[12]), 2),
            "p99": round(float(row[13]), 2),
            "max_eta": round(float(row[14]), 2),
        }

    temporal_leakage = False
    if "train" in splits_out and "test" in splits_out:
        temporal_leakage = float(splits_out["train"]["max_epoch"]) >= float(splits_out["test"]["min_epoch"])

    return {
        "silver_parquet": {
            "rows": int(silver_stats[0]),
            "distinct_routes": int(silver_stats[1]),
            "min_epoch_hn": fmt_hn(silver_stats[2]),
            "max_epoch_hn": fmt_hn(silver_stats[3]),
            "cross_track_gt_35": int(silver_stats[4]),
            "s_bus_lt_0": int(silver_stats[5]),
            "derived_speed_oob": int(silver_stats[6]),
            "null_key_cols": int(silver_stats[7]),
            "duplicate_route_veh_epoch_groups": int(silver_dups),
            "baseline_routes_missing_direction": missing_dir_routes,
        },
        "sqlite_route_projected_telemetry": {
            "rows": int(sqlite_tel[0]),
            "distinct_routes": int(sqlite_tel[1]),
            "min_epoch_hn": fmt_hn(sqlite_tel[2]),
            "max_epoch_hn": fmt_hn(sqlite_tel[3]),
        },
        "gold_eta_feature_store": {
            "splits": splits_out,
            "temporal_leakage_train_ge_test": temporal_leakage,
        },
    }


# ---------------------------------------------------------------------------
# D3: TimBus Anchor Mapping Consistency
# ---------------------------------------------------------------------------
def audit_d3_timbus_anchors(main_con: sqlite3.Connection, tb_con: sqlite3.Connection) -> dict[str, Any]:
    diff_rows = tb_con.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT route_id, route_code, direction, timbus_enabled, primary_anchor_sid, backup_anchor_sid
            FROM timbus_route_anchors
            EXCEPT
            SELECT route_id, route_code, direction, timbus_enabled, primary_anchor_sid, backup_anchor_sid
            FROM timbus_verified_anchors
        )
        """
    ).fetchone()[0]

    tb_stations = {
        int(r["station_id"]): (float(r["lat"]), float(r["lng"]), r["name"])
        for r in tb_con.execute("SELECT station_id, lat, lng, name FROM stations WHERE lat IS NOT NULL AND lng IS NOT NULL")
    }

    canon_stations: dict[tuple[int, str], list[tuple[float, float, str, int]]] = {}
    for r in main_con.execute("SELECT route_id, direction, lat, lon, station_name, station_order FROM canonical_station_master"):
        canon_stations.setdefault((int(r["route_id"]), norm_dir(r["direction"])), []).append(
            (float(r["lat"]), float(r["lon"]), str(r["station_name"]), int(r["station_order"]))
        )

    anchors = tb_con.execute(
        """
        SELECT route_id, route_code, direction, direction_str, timbus_enabled, audit_status,
               primary_anchor_sid, backup_anchor_sid, anchor_source, verified_tb_route
        FROM timbus_route_anchors
        """
    ).fetchall()

    enabled_rows = [r for r in anchors if int(r["timbus_enabled"] or 0) == 1]
    enabled_routes = {r["route_code"] for r in enabled_rows}

    missing_primary_sid = []
    missing_backup_sid = []
    missing_canon_dir = []
    far_anchors = []
    wrong_dir_candidates = []
    all_checked = []

    for r in enabled_rows:
        rid = int(r["route_id"])
        rcode = str(r["route_code"])
        d_str = norm_dir(r["direction_str"])
        opp_dir = "re" if d_str == "go" else "go"
        psid = r["primary_anchor_sid"]
        bsid = r["backup_anchor_sid"]

        if psid is None or int(psid) not in tb_stations:
            missing_primary_sid.append({"route_code": rcode, "direction": d_str, "primary_anchor_sid": psid})
            continue
        if bsid is not None and int(bsid) not in tb_stations:
            missing_backup_sid.append({"route_code": rcode, "direction": d_str, "backup_anchor_sid": bsid})

        plat, plon, pname = tb_stations[int(psid)]
        same_list = canon_stations.get((rid, d_str), [])
        opp_list = canon_stations.get((rid, opp_dir), [])
        if not same_list:
            missing_canon_dir.append({"route_id": rid, "route_code": rcode, "direction": d_str})
            continue

        same_best = min(((haversine_m(plat, plon, s[0], s[1]), s[2], s[3]) for s in same_list), key=lambda x: x[0])
        opp_best = min(((haversine_m(plat, plon, s[0], s[1]), s[2], s[3]) for s in opp_list), key=lambda x: x[0]) if opp_list else (math.inf, "", -1)

        rec = {
            "route_id": rid,
            "route_code": rcode,
            "direction": d_str,
            "primary_anchor_sid": int(psid),
            "tb_station_name": pname,
            "same_dir_min_dist_m": round(same_best[0], 1),
            "same_dir_nearest_station": same_best[1],
            "opp_dir_min_dist_m": round(opp_best[0], 1) if opp_best[0] != math.inf else None,
            "opp_dir_nearest_station": opp_best[1],
        }
        all_checked.append(rec)
        if same_best[0] > 100.0:
            far_anchors.append(rec)
        if opp_best[0] + 30.0 < same_best[0]:
            wrong_dir_candidates.append(rec)

    all_checked.sort(key=lambda x: x["same_dir_min_dist_m"], reverse=True)

    return {
        "anchors_vs_verified_diff_count": int(diff_rows),
        "total_anchor_rows": len(anchors),
        "enabled_anchor_rows": len(enabled_rows),
        "enabled_distinct_routes": len(enabled_routes),
        "missing_primary_sid_count": len(missing_primary_sid),
        "missing_primary_sid_samples": missing_primary_sid[:10],
        "missing_backup_sid_count": len(missing_backup_sid),
        "missing_canonical_dir_count": len(missing_canon_dir),
        "far_anchors_gt_100m_count": len(far_anchors),
        "far_anchors_gt_100m": far_anchors,
        "wrong_direction_candidates_count": len(wrong_dir_candidates),
        "wrong_direction_candidates": wrong_dir_candidates,
        "top10_furthest_anchors": all_checked[:10],
    }


# ---------------------------------------------------------------------------
# D4: TomTom Incidents Integrity
# ---------------------------------------------------------------------------
def audit_d4_tomtom(con: sqlite3.Connection, ddb: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    bronze_glob = (ROOT / "data/lakehouse/bronze/tomtom_incidents_raw/dt=*/*.parquet").as_posix()
    bronze = ddb.execute(
        f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT dt) AS distinct_dt,
            MIN(dt) AS min_dt,
            MAX(dt) AS max_dt,
            SUM(CASE WHEN delay_seconds <= 0 THEN 1 ELSE 0 END) AS delay_le_0,
            SUM(CASE WHEN length_meters <= 0 THEN 1 ELSE 0 END) AS len_le_0,
            SUM(CASE WHEN coordinates_json IS NULL OR length(coordinates_json) < 5 THEN 1 ELSE 0 END) AS bad_coords
        FROM read_parquet('{bronze_glob}', hive_partitioning=true)
        """
    ).fetchone()

    silver_glob = (ROOT / "data/lakehouse/silver/fact_route_tomtom_incidents/route_code=*/*.parquet").as_posix()
    silver = ddb.execute(
        f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT route_code) AS distinct_routes,
            MIN(t_start_epoch) AS min_start,
            MAX(t_end_epoch) AS max_end,
            SUM(CASE WHEN delay_seconds <= 0 THEN 1 ELSE 0 END) AS delay_le_0,
            SUM(CASE WHEN s_max_m < s_min_m THEN 1 ELSE 0 END) AS s_inverted,
            SUM(CASE WHEN overlap_length_m <= 0 THEN 1 ELSE 0 END) AS ov_le_0,
            SUM(CASE WHEN t_end_epoch < t_start_epoch THEN 1 ELSE 0 END) AS t_inverted,
            SUM(CASE WHEN d_perp_m > 35.0 THEN 1 ELSE 0 END) AS d_perp_gt_35
        FROM read_parquet('{silver_glob}', hive_partitioning=true)
        """
    ).fetchone()

    bleed = ddb.execute(
        f"""
        WITH ep AS (
            SELECT route_code, incident_id, episode_idx,
                   COUNT(DISTINCT direction) AS n_dirs
            FROM read_parquet('{silver_glob}', hive_partitioning=true)
            GROUP BY 1, 2, 3
        )
        SELECT COUNT(*) AS total_episodes,
               SUM(CASE WHEN n_dirs >= 2 THEN 1 ELSE 0 END) AS both_dir_episodes
        FROM ep
        """
    ).fetchone()

    sqlite_inc = con.execute(
        """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT route_code) AS distinct_routes,
               MIN(t_start_epoch) AS min_start, MAX(t_end_epoch) AS max_end
        FROM fact_route_tomtom_incidents
        """
    ).fetchone()

    total_ep = int(bleed[0] or 0)
    both_ep = int(bleed[1] or 0)
    return {
        "bronze_incidents": {
            "rows": int(bronze[0]),
            "distinct_dt": int(bronze[1]),
            "min_dt": str(bronze[2]),
            "max_dt": str(bronze[3]),
            "delay_le_0": int(bronze[4]),
            "length_le_0": int(bronze[5]),
            "bad_coordinates_json": int(bronze[6]),
        },
        "silver_incidents_parquet": {
            "rows": int(silver[0]),
            "distinct_routes": int(silver[1]),
            "min_start_hn": fmt_hn(silver[2]),
            "max_end_hn": fmt_hn(silver[3]),
            "delay_le_0": int(silver[4]),
            "s_max_lt_s_min": int(silver[5]),
            "overlap_le_0": int(silver[6]),
            "t_end_lt_t_start": int(silver[7]),
            "d_perp_gt_35": int(silver[8]),
            "total_route_episodes": total_ep,
            "both_dir_bleed_episodes": both_ep,
            "both_dir_bleed_pct": round(100.0 * both_ep / total_ep, 2) if total_ep else 0.0,
        },
        "sqlite_fact_route_tomtom_incidents": {
            "rows": int(sqlite_inc[0]),
            "distinct_routes": int(sqlite_inc[1]),
            "min_start_hn": fmt_hn(sqlite_inc[2]),
            "max_end_hn": fmt_hn(sqlite_inc[3]),
        },
    }


# ---------------------------------------------------------------------------
# D5: Gold Baseline Matrix Integrity
# ---------------------------------------------------------------------------
def audit_d5_gold_baseline(con: sqlite3.Connection, ddb: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    gold_glob = (ROOT / "data/lakehouse/gold/agg_segment_travel_times/*.parquet").as_posix()
    pq_stats = ddb.execute(
        f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT route_code) AS distinct_routes,
            SUM(CASE WHEN tt_p10_sec > tt_p50_sec + 1e-6 OR tt_p50_sec > tt_p90_sec + 1e-6 THEN 1 ELSE 0 END) AS non_mono_quantiles,
            SUM(CASE WHEN tt_p50_sec <= 0 THEN 1 ELSE 0 END) AS p50_le_0,
            SUM(CASE WHEN tt_p50_sec > 1800.0 THEN 1 ELSE 0 END) AS p50_gt_1800,
            SUM(CASE WHEN segment_length_m <= 0 THEN 1 ELSE 0 END) AS seg_len_le_0,
            SUM(CASE WHEN tt_std_sec < 0 THEN 1 ELSE 0 END) AS std_lt_0
        FROM read_parquet('{gold_glob}')
        """
    ).fetchone()

    tiers = ddb.execute(
        f"""
        SELECT quality_tier, COUNT(*) AS cnt
        FROM read_parquet('{gold_glob}')
        GROUP BY quality_tier
        ORDER BY quality_tier
        """
    ).fetchall()

    lowest_tier0 = ddb.execute(
        f"""
        SELECT route_code,
               COUNT(*) AS total_cells,
               SUM(CASE WHEN quality_tier = 0 THEN 1 ELSE 0 END) AS tier0_cells,
               ROUND(100.0 * SUM(CASE WHEN quality_tier = 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS tier0_pct
        FROM read_parquet('{gold_glob}')
        GROUP BY route_code
        ORDER BY tier0_pct ASC, route_code ASC
        LIMIT 10
        """
    ).fetchall()

    # Parity check between Parquet and SQLite
    sq_rows = con.execute(
        """
        SELECT route_code, direction, from_station_order, to_station_order, day_type, hour_slot, tt_p50_sec
        FROM agg_segment_travel_times
        """
    ).fetchall()
    sq_map = {(r[0], r[1], r[2], r[3], r[4], r[5]): float(r[6]) for r in sq_rows}

    pq_rows = ddb.execute(
        f"""
        SELECT route_code, direction, from_station_order, to_station_order, day_type, hour_slot, tt_p50_sec
        FROM read_parquet('{gold_glob}')
        """
    ).fetchall()
    pq_map = {(r[0], r[1], int(r[2]), int(r[3]), int(r[4]), int(r[5])): float(r[6]) for r in pq_rows}

    common_keys = set(sq_map.keys()) & set(pq_map.keys())
    max_abs_diff = max((abs(sq_map[k] - pq_map[k]) for k in common_keys), default=0.0)

    return {
        "parquet_rows": int(pq_stats[0]),
        "sqlite_rows": len(sq_rows),
        "parquet_distinct_routes": int(pq_stats[1]),
        "key_overlap_count": len(common_keys),
        "sqlite_only_keys": len(sq_map) - len(common_keys),
        "parquet_only_keys": len(pq_map) - len(common_keys),
        "max_abs_diff_tt_p50_sec": round(max_abs_diff, 6),
        "non_monotonic_quantiles": int(pq_stats[2]),
        "p50_le_0": int(pq_stats[3]),
        "p50_gt_1800": int(pq_stats[4]),
        "seg_len_le_0": int(pq_stats[5]),
        "std_lt_0": int(pq_stats[6]),
        "quality_tier_distribution": {str(int(t[0])): int(t[1]) for t in tiers},
        "lowest_tier0_routes_top10": [
            {"route_code": r[0], "total_cells": int(r[1]), "tier0_cells": int(r[2]), "tier0_pct": float(r[3])}
            for r in lowest_tier0
        ],
    }


def render_markdown(res: dict[str, Any]) -> str:
    d1, d2, d3, d4, d5 = res["D1"], res["D2"], res["D3"], res["D4"], res["D5"]
    lines: list[str] = [
        "# Giai đoạn 0 — Evidence Kiểm định Tính đúng đắn của Dữ liệu",
        "",
        f"- **Thời điểm chạy:** `{res['generated_at']}`",
        "- **Chế độ:** Read-only 100% (`SQLite mode=ro` + `DuckDB` trên Parquet cục bộ).",
        "",
        "---",
        "",
        "## D1. Hình học Chuẩn hóa (`canonical_shape_master`, `canonical_station_master`)",
        f"- Tổng số tuyến canonical: `{d1['total_canonical_routes']}` (trong đó tập Baseline: `{d1['baseline_route_count']}` tuyến).",
        f"- Tổng số trạm: `{d1['total_canonical_stations']}`, tổng số điểm polyline: `{d1['total_canonical_shapes']}`.",
        "",
        "| Kiểm tra | Toàn mạng (176 tuyến) | Tập Baseline (48 tuyến) |",
        "| :--- | :---: | :---: |",
        f"| Trạm `cum_distance_m` không đơn điệu tăng (`ds <= 0`) | `{d1['station_non_monotonic_count_all']}` | `{d1['station_non_monotonic_count_baseline']}` |",
        f"| Lỗi `station_order` trùng/thiếu | `{d1['station_order_anomalies_count']}` | `{sum(1 for x in d1['station_order_anomalies_samples'] if x['is_baseline'])}` |",
        f"| Trạm có `snap_dist_m > 35.0m` | `{d1['station_snap_gt_35m_all']}` | `{d1['station_snap_gt_35m_baseline']}` |",
        f"| Trạm có `snap_dist_m > 100.0m` | `{d1['station_snap_gt_100m_all']}` | `{d1['station_snap_gt_100m_baseline']}` |",
        f"| Chặng `< 50m` | `{d1['short_segments_lt_50m_all']}` | `{d1['short_segments_lt_50m_baseline']}` |",
        f"| Chặng `> 5000m` | `{d1['long_segments_gt_5000m_all']}` | `{d1['long_segments_gt_5000m_baseline']}` |",
        f"| Điểm shape ngoài `HANOI_BBOX` / không đơn điệu | `{d1['shape_oob_count']}` / `{d1['shape_non_monotonic_count']}` | — |",
        "",
    ]

    if d1["station_non_monotonic_samples"]:
        lines.append("**Mẫu trạm không đơn điệu (tối đa 10 dòng đầu):**")
        lines.append("")
        lines.append("| Tuyến | Baseline | Chiều | Order | Trạm trước -> sau | `ds_m` |")
        lines.append("| :--- | :---: | :---: | :---: | :--- | ---: |")
        for s in d1["station_non_monotonic_samples"][:10]:
            lines.append(
                f"| `{s['route_code']}` | `{s['is_baseline']}` | `{s['direction']}` | `{s['prev_order']}->{s['curr_order']}` | {s['prev_name']} -> {s['curr_name']} | `{s['ds_m']}` |"
            )
        lines.append("")

    if d1["worst_snap_stations_top15"]:
        lines.append("**Top trạm có `snap_dist_m > 35.0m` lớn nhất (tối đa 10):**")
        lines.append("")
        lines.append("| Tuyến | Baseline | Chiều | Order | Tên trạm | `snap_dist_m` |")
        lines.append("| :--- | :---: | :---: | :---: | :--- | ---: |")
        for s in d1["worst_snap_stations_top15"][:10]:
            lines.append(
                f"| `{s['route_code']}` | `{s['is_baseline']}` | `{s['direction']}` | `{s['station_order']}` | {s['station_name']} | `{s['snap_dist_m']}` |"
            )
        lines.append("")

    sp = d2["silver_parquet"]
    sq_t = d2["sqlite_route_projected_telemetry"]
    fs = d2["gold_eta_feature_store"]
    lines.extend(
        [
            "---",
            "",
            "## D2. Silver Telemetry & Gold Feature Store",
            "| Nguồn | Số dòng | Số tuyến | Khoảng thời gian (Hanoi UTC+7) |",
            "| :--- | ---: | :---: | :--- |",
            f"| Silver Parquet (`route_projected_telemetry`) | `{sp['rows']:,}` | `{sp['distinct_routes']}` | `{sp['min_epoch_hn']}` → `{sp['max_epoch_hn']}` |",
            f"| SQLite (`route_projected_telemetry`) | `{sq_t['rows']:,}` | `{sq_t['distinct_routes']}` | `{sq_t['min_epoch_hn']}` → `{sq_t['max_epoch_hn']}` |",
            "",
            f"- Silver bất thường: `cross_track > 35m` = `{sp['cross_track_gt_35']}`, `s_bus < 0` = `{sp['s_bus_lt_0']}`, `speed < 0 or > 80` = `{sp['derived_speed_oob']}`, `null_cols` = `{sp['null_key_cols']}`, nhóm trùng `(route_id, vehicle_id, device_epoch)` = `{sp['duplicate_route_veh_epoch_groups']}`.",
            f"- Tuyến Baseline thiếu chiều `go` hoặc `re` trong Silver: `{len(sp['baseline_routes_missing_direction'])}` tuyến (`{sp['baseline_routes_missing_direction']}`).",
            "",
            r"- **Gold `eta_feature_store` — Rò rỉ thời gian train $\ge$ test:** " + f"`{fs['temporal_leakage_train_ge_test']}`.",
            "",
            "| Split | Số dòng | Tuyến | Ngày `dt` | `actual_eta <= 0` | `> 3600s` | `NaN` | P01 / P50 / P95 / P99 / Max (s) |",
            "| :--- | ---: | :---: | :--- | ---: | ---: | ---: | :--- |",
        ]
    )
    for sp_name, sv in fs["splits"].items():
        lines.append(
            f"| `{sp_name}` | `{sv['rows']:,}` | `{sv['distinct_routes']}` | `{sv['min_dt']}..{sv['max_dt']}` | `{sv['eta_le_0']}` | `{sv['eta_gt_3600']}` | `{sv['eta_nan']}` | `{sv['p01']} / {sv['p50']} / {sv['p95']} / {sv['p99']} / {sv['max_eta']}` |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## D3. Bản đồ Neo TimBus (`timbus_hanoi.sqlite` vs `hanoi_bus_system.db`)",
            f"- Sai lệch giữa `timbus_route_anchors` và `timbus_verified_anchors`: `{d3['anchors_vs_verified_diff_count']}` dòng.",
            f"- Tổng số dòng anchor: `{d3['total_anchor_rows']}` | Đang bật (`timbus_enabled=1`): `{d3['enabled_anchor_rows']}` chiều trên `{d3['enabled_distinct_routes']}` tuyến.",
            f"- Thiếu `primary_anchor_sid` trong `stations`: `{d3['missing_primary_sid_count']}` | Thiếu `backup_anchor_sid`: `{d3['missing_backup_sid_count']}`.",
            f"- Anchor cách trạm cùng chiều `> 100m`: **`{d3['far_anchors_gt_100m_count']}`** | Nghi ngờ lệch chiều (gần chiều ngược hơn > 30m): **`{d3['wrong_direction_candidates_count']}`**.",
            "",
            "**Top 10 anchor có khoảng cách tới trạm cùng chiều lớn nhất:**",
            "",
            "| Tuyến | Chiều | `primary_sid` | Trạm TimBus | Khoảng cách cùng chiều (m) | Khoảng cách chiều ngược (m) |",
            "| :--- | :---: | ---: | :--- | ---: | ---: |",
        ]
    )
    for a in d3["top10_furthest_anchors"]:
        lines.append(
            f"| `{a['route_code']}` | `{a['direction']}` | `{a['primary_anchor_sid']}` | {a['tb_station_name']} | `{a['same_dir_min_dist_m']}` | `{a['opp_dir_min_dist_m']}` |"
        )

    br = d4["bronze_incidents"]
    si = d4["silver_incidents_parquet"]
    sqi = d4["sqlite_fact_route_tomtom_incidents"]
    lines.extend(
        [
            "",
            "---",
            "",
            "## D4. Sự cố TomTom (`bronze/tomtom_incidents_raw` vs `silver/fact_route_tomtom_incidents`)",
            f"- **Bronze Parquet:** `{br['rows']:,}` dòng (`{br['distinct_dt']}` ngày: `{br['min_dt']}..{br['max_dt']}`), `delay <= 0`: `{br['delay_le_0']}`, `length <= 0`: `{br['length_le_0']}`, `bad_coords`: `{br['bad_coordinates_json']}`.",
            f"- **Silver Parquet:** `{si['rows']:,}` dòng (`{si['distinct_routes']}` tuyến, `{si['min_start_hn']}` → `{si['max_end_hn']}`).",
            f"- **SQLite `fact_route_tomtom_incidents`:** `{sqi['rows']:,}` dòng (`{sqi['distinct_routes']}` tuyến, `{sqi['min_start_hn']}` → `{sqi['max_end_hn']}`).",
            f"- Silver bất thường: `delay <= 0` = `{si['delay_le_0']}`, `s_max < s_min` = `{si['s_max_lt_s_min']}`, `overlap <= 0` = `{si['overlap_le_0']}`, `t_end < t_start` = `{si['t_end_lt_t_start']}`, `d_perp > 35m` = `{si['d_perp_gt_35']}`.",
            f"- **Bidirectional bleed (cùng episode chiếu sang cả 2 chiều `go` & `re` trên cùng tuyến):** `{si['both_dir_bleed_episodes']:,} / {si['total_route_episodes']:,}` (**`{si['both_dir_bleed_pct']}%`**).",
            "",
            "---",
            "",
            "## D5. Ma trận Baseline Gold (`agg_segment_travel_times`: Parquet vs SQLite)",
            f"- Số dòng: Parquet `{d5['parquet_rows']:,}` vs SQLite `{d5['sqlite_rows']:,}` (Khóa trùng khớp: `{d5['key_overlap_count']:,}`, chỉ Parquet: `{d5['parquet_only_keys']}`, chỉ SQLite: `{d5['sqlite_only_keys']}`).",
            f"- Sai lệch tuyệt đối lớn nhất `|tt_p50_sec|`: **`{d5['max_abs_diff_tt_p50_sec']}s`**.",
            f"- Bất thường định lượng: `p10 > p50 or p50 > p90` = `{d5['non_monotonic_quantiles']}`, `p50 <= 0` = `{d5['p50_le_0']}`, `p50 > 1800` = `{d5['p50_gt_1800']}`, `seg_len <= 0` = `{d5['seg_len_le_0']}`, `std < 0` = `{d5['std_lt_0']}`.",
            f"- Phân bố `quality_tier`: `{d5['quality_tier_distribution']}`.",
            "",
            "**10 tuyến có tỷ lệ `quality_tier = 0` thấp nhất:**",
            "",
            "| Tuyến | Tổng cell | Tier 0 cell | Tỷ lệ Tier 0 (%) |",
            "| :--- | ---: | ---: | ---: |",
        ]
    )
    for r in d5["lowest_tier0_routes_top10"]:
        lines.append(f"| `{r['route_code']}` | `{r['total_cells']:,}` | `{r['tier0_cells']:,}` | `{r['tier0_pct']}%` |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    main_con = ro_connect(MAIN_DB)
    tb_con = ro_connect(TIMBUS_DB)
    ddb = duckdb.connect(":memory:")

    try:
        res: dict[str, Any] = {
            "generated_at": datetime.now(TZ_HANOI).strftime("%Y-%m-%d %H:%M:%S%z"),
            "D1": audit_d1_geometry(main_con),
            "D2": audit_d2_telemetry_and_features(main_con, ddb),
            "D3": audit_d3_timbus_anchors(main_con, tb_con),
            "D4": audit_d4_tomtom(main_con, ddb),
            "D5": audit_d5_gold_baseline(main_con, ddb),
        }
    finally:
        ddb.close()
        tb_con.close()
        main_con.close()

    json_path = OUT_DIR / "00_data_correctness.json"
    md_path = OUT_DIR / "00_data_correctness.md"
    json_path.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(res), encoding="utf-8")
    print(f"Wrote {json_path} and {md_path}")


if __name__ == "__main__":
    main()
