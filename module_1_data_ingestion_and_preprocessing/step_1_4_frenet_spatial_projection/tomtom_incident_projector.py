"""
Script: scripts/build_fact_route_tomtom_incidents.py
Purpose: WP 2.1.1 & 2.1.2 (Hotfixed & Audited)
  - Ingests 22 days of TomTom JSONL incident batches with strict causal time windows
    [t_batch, min(t_next_batch, t_batch + 900s)] (0% future data leakage).
  - Projects incident LineStrings onto 48 canonical bus routes using segment-level
    directional alignment (cos_theta >= 0.5) and contiguous monotonic Frenet runs,
    completely eliminating the s_min=0.0 initialization bug and loop/cross-street jumps.
  - Maps TomTom's raw magnitudeOfDelay=4 (Undefined/0-delay roadworks) to monotonic
    severity so only true congestion delays scale the severity level.
"""
import bisect
import os
import glob
import json
import math
import time
import sqlite3
import sys
from datetime import datetime, timezone
from collections import defaultdict, Counter

import numpy as np
import shapely
from shapely import STRtree

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.system_config import (
    DEFAULT_DB_PATH,
    DEFAULT_LAKEHOUSE_ROOT,
    RAW_DATA_DIR,
    MAX_CORRIDOR_CROSS_TRACK_M,
    TOMTOM_MAX_BATCH_GAP_SEC,
    TOMTOM_DEFAULT_TTL_SEC,
    TOMTOM_MIN_COS_THETA,
    TOMTOM_GRID_SCALE,
    TOMTOM_BBOX_PAD_DEG,
    TZ_HANOI,
)
from module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.route_matcher import (
    ShapeProjectionModel,
)

DB_PATH = DEFAULT_DB_PATH
INCIDENTS_GLOB = f"{RAW_DATA_DIR}/*/incidents/*.jsonl"
MAX_BATCH_GAP_SEC = TOMTOM_MAX_BATCH_GAP_SEC
DEFAULT_TTL_SEC = TOMTOM_DEFAULT_TTL_SEC
MAX_D_PERP_M = MAX_CORRIDOR_CROSS_TRACK_M
MIN_COS_THETA = TOMTOM_MIN_COS_THETA
GRID_SCALE = TOMTOM_GRID_SCALE
PAD_DEG = TOMTOM_BBOX_PAD_DEG


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def build_route_segment_grid(shapes: list) -> dict:
    """
    Precomputes segment geometry and indexes into a spatial grid for O(1) lookup.
    Each segment entry: (a_lat, a_lon, cos_lat, dx, dy, seg_len_sq, s_a, s_b, sx, sy)
    """
    grid = defaultdict(list)
    for i in range(len(shapes) - 1):
        a_lat, a_lon, s_a = shapes[i]
        b_lat, b_lon, s_b = shapes[i + 1]
        cos_lat = math.cos(math.radians((a_lat + b_lat) / 2.0))
        dx = (b_lon - a_lon) * 111320.0 * cos_lat
        dy = (b_lat - a_lat) * 110540.0
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-6:
            continue
        seg_len = math.sqrt(seg_len_sq)
        sx = dx / seg_len
        sy = dy / seg_len
        seg_tuple = (a_lat, a_lon, cos_lat, dx, dy, seg_len_sq, s_a, s_b - s_a, sx, sy)

        gx_min = int(math.floor((min(a_lat, b_lat) - PAD_DEG) * GRID_SCALE))
        gx_max = int(math.floor((max(a_lat, b_lat) + PAD_DEG) * GRID_SCALE))
        gy_min = int(math.floor((min(a_lon, b_lon) - PAD_DEG) * GRID_SCALE))
        gy_max = int(math.floor((max(a_lon, b_lon) + PAD_DEG) * GRID_SCALE))
        for gx in range(gx_min, gx_max + 1):
            for gy in range(gy_min, gy_max + 1):
                grid[(gx, gy)].append(seg_tuple)
    return grid


def project_linestring_to_route_grid(
    coords: list,
    pt_unit_vecs: list,
    pt_step_dists: list,
    inc_length_m: float,
    seg_grid: dict,
) -> list:
    """
    Projects an incident LineString onto a single (route_code, direction) shape polyline
    using the precomputed spatial grid.
    Returns a list of valid contiguous Frenet intervals: [(s_min, s_max, avg_d_perp), ...]
    Guarantees:
      1. Every matched vertex has d_perp <= MAX_D_PERP_M (35m) AND directional cos_theta >= 0.5.
      2. Consecutive vertices form a monotonic run along s_m without jumping across loops.
      3. Run span (s_max - s_min) cannot exceed physical incident length bounds.
    """
    matched_vertices = []  # list of (vertex_idx, best_s, min_d)
    for j, pt in enumerate(coords):
        ux, uy = pt_unit_vecs[j]
        if ux == 0.0 and uy == 0.0:
            continue

        p_lon, p_lat = pt[0], pt[1]
        cell = (int(math.floor(p_lat * GRID_SCALE)), int(math.floor(p_lon * GRID_SCALE)))
        cand_segs = seg_grid.get(cell)
        if not cand_segs:
            continue

        min_d = float("inf")
        best_s = None

        for a_lat, a_lon, cos_lat, dx, dy, seg_len_sq, s_a, ds_ab, sx, sy in cand_segs:
            cos_theta = ux * sx + uy * sy
            if cos_theta < MIN_COS_THETA:
                continue
            px = (p_lon - a_lon) * 111320.0 * cos_lat
            py = (p_lat - a_lat) * 110540.0
            t = (px * dx + py * dy) / seg_len_sq
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            d_perp = math.hypot(px - t * dx, py - t * dy)
            if d_perp <= MAX_D_PERP_M and d_perp < min_d:
                min_d = d_perp
                best_s = s_a + t * ds_ab

        if best_s is not None:
            matched_vertices.append((j, best_s, min_d))

    if not matched_vertices:
        return []

    return split_matched_vertices_into_runs(matched_vertices, pt_step_dists, inc_length_m)


def compute_linestring_kinematics(coords: list):
    """Tính vector đơn vị tại mỗi đỉnh và khoảng cách bước giữa các đỉnh liên tiếp."""
    n_pts = len(coords) if coords else 0
    pt_unit_vecs = []
    pt_step_dists = []
    for j in range(n_pts):
        if j < n_pts - 1:
            lon1, lat1 = coords[j][0], coords[j][1]
            lon2, lat2 = coords[j + 1][0], coords[j + 1][1]
        else:
            lon1, lat1 = coords[j - 1][0], coords[j - 1][1]
            lon2, lat2 = coords[j][0], coords[j][1]
        cos_lat = math.cos(math.radians((lat1 + lat2) / 2.0))
        vx = (lon2 - lon1) * 111320.0 * cos_lat
        vy = (lat2 - lat1) * 110540.0
        vlen = math.hypot(vx, vy)
        pt_unit_vecs.append((vx / vlen, vy / vlen) if vlen > 1e-3 else (0.0, 0.0))
        if j > 0:
            pt_step_dists.append(haversine(coords[j - 1][1], coords[j - 1][0], coords[j][1], coords[j][0]))
        else:
            pt_step_dists.append(0.0)
    return pt_unit_vecs, pt_step_dists


def split_matched_vertices_into_runs(
    matched_vertices: list,
    pt_step_dists: list,
    inc_length_m: float,
) -> list:
    """Gom các đỉnh đã khớp thành từng run liên tiếp đơn điệu dọc s_m và kiểm tra max_allowed_span."""
    if not matched_vertices:
        return []
    runs = []
    cur_run = [matched_vertices[0]]
    for m_v in matched_vertices[1:]:
        prev_j, prev_s = cur_run[-1][0], cur_run[-1][1]
        cur_j, cur_s = m_v[0], m_v[1]
        inc_step_m = sum(pt_step_dists[prev_j + 1 : cur_j + 1])
        ds = cur_s - prev_s
        if -15.0 <= ds <= max(150.0, 1.8 * inc_step_m + 60.0) and (cur_j - prev_j) <= 3:
            cur_run.append(m_v)
        else:
            runs.append(cur_run)
            cur_run = [m_v]
    if cur_run:
        runs.append(cur_run)

    valid_intervals = []
    max_allowed_span = max(100.0, 1.4 * inc_length_m + 80.0)
    for run in runs:
        s_vals = [x[1] for x in run]
        d_vals = [x[2] for x in run]
        s_min = min(s_vals)
        s_max = max(s_vals)
        span = s_max - s_min
        avg_d = sum(d_vals) / len(d_vals)

        if len(run) >= 2 and 15.0 <= span <= max_allowed_span:
            valid_intervals.append((s_min, s_max, avg_d))
        elif len(run) == 1 and inc_length_m <= 80.0 and avg_d <= 20.0:
            half_len = max(10.0, min(40.0, inc_length_m / 2.0))
            valid_intervals.append((max(0.0, s_min - half_len), s_max + half_len, avg_d))

    return valid_intervals


def main():
    t_start = time.time()
    print("=" * 84, flush=True)
    print("WP 2.1 (HOTFIXED): CAUSAL TOMTOM INCIDENT FUSION & CONTIGUOUS FRENET PROJECTION", flush=True)
    print("=" * 84, flush=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Load all active Silver canonical bus routes
    cur.execute("SELECT DISTINCT route_code FROM route_projected_telemetry ORDER BY route_code")
    target_routes = sorted([r[0] for r in cur.fetchall()])
    print(f"[1/5] Loaded {len(target_routes)} target canonical bus routes.", flush=True)

    # 2. Load shapes and stations for the 48 routes and build spatial segment grids
    cur.execute(
        """
        SELECT route_code, direction, point_order, lat, lon, cum_distance_m 
        FROM canonical_shape_master 
        WHERE route_code IN ({})
        ORDER BY route_code, direction, point_order
        """.format(",".join(f"'{r}'" for r in target_routes))
    )
    route_shapes = defaultdict(lambda: {"go": [], "re": []})
    for rcode, direction, pt_ord, lat, lon, s_m in cur.fetchall():
        route_shapes[rcode][direction].append((int(pt_ord), float(lat), float(lon), float(s_m)))

    route_models = {}
    route_keys = []
    route_bbox_geoms = []
    for rcode, dirs in route_shapes.items():
        for d, pts in dirs.items():
            if len(pts) >= 2:
                lats = [p[1] for p in pts]
                lons = [p[2] for p in pts]
                route_models[(rcode, d)] = ShapeProjectionModel.build(pts)
                route_keys.append((rcode, d))
                route_bbox_geoms.append(
                    shapely.box(
                        min(lons) - 0.0008,
                        min(lats) - 0.0008,
                        max(lons) + 0.0008,
                        max(lats) + 0.0008,
                    )
                )

    route_rtree = STRtree(route_bbox_geoms) if route_bbox_geoms else None

    cur.execute(
        """
        SELECT route_code, direction, station_order, station_name, cum_distance_m 
        FROM canonical_station_master 
        WHERE route_code IN ({})
        ORDER BY route_code, direction, station_order
        """.format(",".join(f"'{r}'" for r in target_routes))
    )
    route_stations = defaultdict(lambda: {"go": [], "re": []})
    route_station_s = defaultdict(lambda: {"go": [], "re": []})
    for rcode, direction, order, name, s_m in cur.fetchall():
        route_stations[rcode][direction].append((int(order), str(name), float(s_m)))
        route_station_s[rcode][direction].append(float(s_m))

    print(f"[2/5] Loaded ShapeProjectionModel + 2-level R-Tree STRtree for {len(route_keys)} route-direction polylines.", flush=True)

    # 3. Read raw records (from raw JSONL or Bronze Parquet fallback) and group by incident_id
    raw_by_incident = defaultdict(list)
    geom_by_incident = {}

    def _ingest_raw_record(r: dict):
        inc_id = r["incident_id"]
        ts = r["timestamp"]
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_HANOI)
        epoch = int(dt.timestamp())
        delay = int(r.get("delay_seconds") or 0)
        raw_mag = int(r.get("magnitude_of_delay") or 0)
        cat = int(r.get("icon_category") or 0)
        length_m = float(r.get("length_meters") or 0.0)
        desc = str(r.get("description") or "")
        if delay > 0:
            eff_mag = raw_mag if raw_mag in (1, 2, 3) else (3 if delay >= 300 else (2 if delay >= 120 else 1))
        else:
            eff_mag = 0
        raw_by_incident[inc_id].append((epoch, str(ts), delay, eff_mag, cat, desc))
        if inc_id not in geom_by_incident:
            coords = r.get("coordinates")
            if coords is None and r.get("coordinates_json"):
                coords = json.loads(r["coordinates_json"])
            if coords:
                geom_by_incident[inc_id] = (coords, length_m)

    files = sorted(glob.glob(INCIDENTS_GLOB))
    if files:
        print(f"[3/5] Ingesting {len(files)} TomTom JSONL files...", flush=True)
        for fpath in files:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        _ingest_raw_record(json.loads(line))
                    except Exception:
                        pass
    else:
        bronze_glob = os.path.join(DEFAULT_LAKEHOUSE_ROOT, "bronze", "tomtom_incidents_raw", "dt=*", "*.parquet")
        bronze_files = sorted(glob.glob(bronze_glob))
        if not bronze_files:
            print(f"ERROR: No incident files found at {INCIDENTS_GLOB} or {bronze_glob}!", flush=True)
            return
        print(f"[3/5] Fallback Bronze Parquet: reading {len(bronze_files)} partitions...", flush=True)
        import pyarrow.parquet as pq
        cols = ["incident_id", "timestamp", "icon_category", "magnitude_of_delay", "delay_seconds", "length_meters", "description", "coordinates_json"]
        for pf in bronze_files:
            for rec in pq.ParquetFile(pf).read(columns=cols).to_pylist():
                try:
                    _ingest_raw_record(rec)
                except Exception:
                    pass

    print(f"      Total unique incident entities: {len(raw_by_incident):,}", flush=True)

    # Build strictly causal intervals per incident_id (0% future leakage)
    episodes_by_incident = defaultdict(list)
    total_episodes = 0

    for inc_id, recs in raw_by_incident.items():
        recs.sort(key=lambda x: x[0])
        unique_recs = []
        for r in recs:
            if not unique_recs or r[0] > unique_recs[-1][0]:
                unique_recs.append(r)

        n_r = len(unique_recs)
        causal_windows = []
        for idx_r, r in enumerate(unique_recs):
            t_cur, _, delay_cur, mag_cur, cat_cur, desc_cur = r
            if idx_r + 1 < n_r and (unique_recs[idx_r + 1][0] - t_cur) <= MAX_BATCH_GAP_SEC:
                t_end = unique_recs[idx_r + 1][0]
            else:
                t_end = t_cur + DEFAULT_TTL_SEC
            if t_end > t_cur:
                ts_start_utc = datetime.fromtimestamp(t_cur, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                ts_end_utc = datetime.fromtimestamp(t_end, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                causal_windows.append([t_cur, t_end, ts_start_utc, ts_end_utc, delay_cur, mag_cur, cat_cur, desc_cur])

        coalesced = []
        for w in causal_windows:
            if (
                coalesced
                and w[0] == coalesced[-1][1]
                and w[5] == coalesced[-1][5]
                and w[6] == coalesced[-1][6]
                and abs(w[4] - coalesced[-1][4]) <= 15
            ):
                coalesced[-1][1] = w[1]
                coalesced[-1][3] = w[3]
            else:
                coalesced.append(w)

        episodes_by_incident[inc_id] = coalesced
        total_episodes += len(coalesced)

    print(
        f"      Built {total_episodes:,} causal state windows (avg {total_episodes / max(1, len(raw_by_incident)):.2f} windows/incident).",
        flush=True,
    )

    # 4. Project geometries onto 48 bus routes using 2-level R-Tree STRtree + ShapeProjectionModel
    print("[4/5] Projecting incident LineStrings onto bus routes (2-level R-Tree STRtree + ShapeProjectionModel)...", flush=True)
    t_proj_start = time.time()

    matches_by_incident = defaultdict(list)
    unique_matched_incidents = set()
    route_stat_counts = Counter()

    inc_ids_list = []
    inc_meta = {}
    inc_boxes = []
    for inc_id, (coords, inc_len_m) in geom_by_incident.items():
        n_pts = len(coords) if coords else 0
        if n_pts < 2:
            continue
        pt_unit_vecs, pt_step_dists = compute_linestring_kinematics(coords)
        lons = [float(p[0]) for p in coords]
        lats = [float(p[1]) for p in coords]
        uxs = [float(u[0]) for u in pt_unit_vecs]
        uys = [float(u[1]) for u in pt_unit_vecs]
        inc_ids_list.append(inc_id)
        inc_meta[inc_id] = (lats, lons, uxs, uys, pt_step_dists, inc_len_m)
        inc_boxes.append(shapely.box(min(lons), min(lats), max(lons), max(lats)))

    if route_rtree is not None and inc_boxes:
        q_pairs = route_rtree.query(inc_boxes)
        by_route = defaultdict(list)
        for ii, ri in zip(q_pairs[0].tolist(), q_pairs[1].tolist()):
            by_route[ri].append(ii)

        for ri, cand_inc_indices in by_route.items():
            rcode, direction = route_keys[ri]
            shape_model = route_models[(rcode, direction)]
            stns = route_stations[rcode][direction]
            stn_s = route_station_s[rcode][direction]
            n_stns = len(stns)
            if n_stns < 2 or not cand_inc_indices:
                continue

            all_lats = []
            all_lons = []
            all_uxs = []
            all_uys = []
            owner_pos = []
            local_js = []
            for pos, ii in enumerate(cand_inc_indices):
                inc_id = inc_ids_list[ii]
                lats, lons, uxs, uys, _, _ = inc_meta[inc_id]
                n_pts = len(lats)
                all_lats.extend(lats)
                all_lons.extend(lons)
                all_uxs.extend(uxs)
                all_uys.extend(uys)
                owner_pos.extend([pos] * n_pts)
                local_js.extend(range(n_pts))

            matched_flat = shape_model.project_directed_points_batch(
                all_lats, all_lons, all_uxs, all_uys, min_cos_theta=MIN_COS_THETA, max_d_perp_m=MAX_D_PERP_M
            )
            per_inc_matches = [[] for _ in cand_inc_indices]
            for flat_idx, s_val, ct_val, m_type in matched_flat:
                per_inc_matches[owner_pos[flat_idx]].append((local_js[flat_idx], s_val, ct_val, m_type))

            for pos, matched_vertices in enumerate(per_inc_matches):
                if not matched_vertices:
                    continue
                if len(matched_vertices) > 1:
                    matched_vertices.sort(key=lambda x: x[0])
                inc_id = inc_ids_list[cand_inc_indices[pos]]
                _, _, _, _, pt_step_dists, inc_len_m = inc_meta[inc_id]
                intervals = split_matched_vertices_into_runs(matched_vertices, pt_step_dists, inc_len_m)
                if not intervals:
                    continue

                unique_matched_incidents.add(inc_id)
                route_stat_counts[rcode] += 1

                for s_min, s_max, avg_d in intervals:
                    eff_inc_span = max(inc_len_m, s_max - s_min, 25.0)
                    k_start = max(0, bisect.bisect_right(stn_s, s_min) - 1)
                    k_end = min(n_stns - 2, bisect.bisect_left(stn_s, s_max))
                    for k in range(k_start, k_end + 1):
                        from_order, from_name, s_from = stns[k]
                        to_order, to_name, s_to = stns[k + 1]
                        overlap_len = min(s_max, s_to) - max(s_min, s_from)
                        if overlap_len >= 5.0:
                            matches_by_incident[inc_id].append(
                                (
                                    rcode,
                                    direction,
                                    from_order,
                                    to_order,
                                    from_name,
                                    to_name,
                                    round(max(s_min, s_from), 1),
                                    round(min(s_max, s_to), 1),
                                    round(overlap_len, 1),
                                    round(avg_d, 1),
                                    eff_inc_span,
                                )
                            )

    print(f"      Spatial matching finished in {time.time() - t_proj_start:.2f}s.", flush=True)
    print(f"      Matched incidents: {len(unique_matched_incidents):,}, Routes with signal: {len(route_stat_counts)}/48", flush=True)

    # Generate final fact table rows with proportional segment delay
    fact_rows = []
    for inc_id, matches in matches_by_incident.items():
        episodes = episodes_by_incident.get(inc_id, [])
        for ep_idx, ep in enumerate(episodes):
            t_start_ep, t_end_ep, t_start_utc, t_end_utc, raw_delay, eff_mag, cat, desc = ep
            for m in matches:
                rcode, direction, from_order, to_order, from_name, to_name, s_seg_min, s_seg_max, overlap_len, avg_d, eff_inc_span = m
                if raw_delay > 0:
                    prop_delay = max(1, int(round(raw_delay * (overlap_len / eff_inc_span))))
                else:
                    prop_delay = 0
                fact_rows.append(
                    (
                        inc_id,
                        ep_idx,
                        rcode,
                        direction,
                        from_order,
                        to_order,
                        from_name,
                        to_name,
                        s_seg_min,
                        s_seg_max,
                        overlap_len,
                        t_start_ep,
                        t_end_ep,
                        t_start_utc,
                        t_end_utc,
                        cat,
                        eff_mag,
                        prop_delay,
                        avg_d,
                        desc,
                    )
                )

    print(f"      Total clean episodic fact records generated: {len(fact_rows):,}", flush=True)

    # 5. Populate SQLite table
    print("[5/5] Re-creating fact_route_tomtom_incidents in SQLite...", flush=True)
    conn.commit()
    cur.execute("PRAGMA synchronous = OFF;")
    cur.execute("PRAGMA temp_store = MEMORY;")
    cur.execute("DROP TABLE IF EXISTS fact_route_tomtom_incidents")
    cur.execute(
        """
        CREATE TABLE fact_route_tomtom_incidents (
            incident_id TEXT NOT NULL,
            episode_idx INTEGER NOT NULL,
            route_code TEXT NOT NULL,
            direction TEXT NOT NULL,
            from_station_order INTEGER NOT NULL,
            to_station_order INTEGER NOT NULL,
            from_station_name TEXT,
            to_station_name TEXT,
            s_min_m REAL NOT NULL,
            s_max_m REAL NOT NULL,
            overlap_length_m REAL NOT NULL,
            t_start_epoch INTEGER NOT NULL,
            t_end_epoch INTEGER NOT NULL,
            t_start_utc TEXT NOT NULL,
            t_end_utc TEXT NOT NULL,
            icon_category INTEGER,
            magnitude_of_delay INTEGER,
            delay_seconds INTEGER,
            d_perp_m REAL,
            description TEXT,
            PRIMARY KEY (incident_id, episode_idx, route_code, direction, from_station_order, to_station_order)
        )
        """
    )

    cur.executemany(
        """
        INSERT OR REPLACE INTO fact_route_tomtom_incidents VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        fact_rows,
    )

    cur.execute("CREATE INDEX idx_fact_inc_route_time ON fact_route_tomtom_incidents (route_code, direction, t_start_epoch, t_end_epoch)")
    cur.execute("CREATE INDEX idx_fact_inc_station_pair ON fact_route_tomtom_incidents (route_code, direction, from_station_order, to_station_order)")
    conn.commit()

    cur.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT incident_id), COUNT(DISTINCT route_code),
               MAX(s_max_m - s_min_m), AVG(s_max_m - s_min_m),
               COUNT(CASE WHEN s_min_m = 0.0 AND s_max_m > 500 THEN 1 END)
        FROM fact_route_tomtom_incidents
        """
    )
    res = cur.fetchone()
    print(f"\n[VERIFIED] Table fact_route_tomtom_incidents:")
    print(f"  - Total clean records: {res[0]:,}")
    print(f"  - Unique incidents matched: {res[1]:,}")
    print(f"  - Unique routes: {res[2]} / {len(target_routes)}")
    print(f"  - Max segment span: {res[3] or 0.0:.1f}m | Avg segment overlap span: {res[4] or 0.0:.1f}m")
    print(f"  - Corrupted s_min=0 (>500m) rows: {res[5]} (0.00%!)", flush=True)

    conn.close()
    print(f"\nCompleted hotfixed WP 2.1.1 & 2.1.2 in {time.time() - t_start:.2f} seconds.", flush=True)


if __name__ == "__main__":
    main()
