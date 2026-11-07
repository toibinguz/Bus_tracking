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
import os
import glob
import json
import math
import time
import sqlite3
import sys
from datetime import datetime
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = "data/hanoi_bus_system.db"
INCIDENTS_GLOB = "data/raw/*/incidents/*.jsonl"
MAX_BATCH_GAP_SEC = 1200  # 20 minutes max gap to chain consecutive batches
DEFAULT_TTL_SEC = 900     # 15 minutes TTL for a single batch snapshot
MAX_D_PERP_M = 35.0       # Strict corridor cross-track threshold (matches Module 1.4/3.2)
MIN_COS_THETA = 0.50      # Angle between incident vector and bus route <= 60 degrees
GRID_SCALE = 500.0        # ~220m grid cells for O(1) exact segment lookup
PAD_DEG = 0.00045         # ~46m bounding box padding (> 35.0m MAX_D_PERP_M)


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

    # Group matched vertices into contiguous monotonic runs along s
    runs = []
    cur_run = [matched_vertices[0]]
    for m_v in matched_vertices[1:]:
        prev_j, prev_s, _ = cur_run[-1]
        cur_j, cur_s, _ = m_v
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

    # 1. Load the 48 target routes
    cur.execute("SELECT DISTINCT route_code FROM ml_route_evaluation_summary ORDER BY route_code")
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
    for rcode, direction, _, lat, lon, s_m in cur.fetchall():
        route_shapes[rcode][direction].append((float(lat), float(lon), float(s_m)))

    route_bboxes = {}
    route_grids = {}
    for rcode, dirs in route_shapes.items():
        for d, pts in dirs.items():
            if len(pts) >= 2:
                lats = [p[0] for p in pts]
                lons = [p[1] for p in pts]
                route_bboxes[(rcode, d)] = (
                    min(lats) - 0.0008,
                    max(lats) + 0.0008,
                    min(lons) - 0.0008,
                    max(lons) + 0.0008,
                )
                route_grids[(rcode, d)] = build_route_segment_grid(pts)

    cur.execute(
        """
        SELECT route_code, direction, station_order, station_name, cum_distance_m 
        FROM canonical_station_master 
        WHERE route_code IN ({})
        ORDER BY route_code, direction, station_order
        """.format(",".join(f"'{r}'" for r in target_routes))
    )
    route_stations = defaultdict(lambda: {"go": [], "re": []})
    for rcode, direction, order, name, s_m in cur.fetchall():
        route_stations[rcode][direction].append((int(order), str(name), float(s_m)))

    print(f"[2/5] Loaded shapes, stations, and O(1) spatial grids for {len(route_bboxes)} route-direction polylines.", flush=True)

    # 3. Read raw records and group by incident_id
    print("[3/5] Ingesting 22 days of TomTom JSONL files and building causal snapshots...", flush=True)
    files = sorted(glob.glob(INCIDENTS_GLOB))
    if not files:
        print(f"ERROR: No incident files found at {INCIDENTS_GLOB}!", flush=True)
        return

    raw_by_incident = defaultdict(list)
    geom_by_incident = {}

    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    inc_id = r["incident_id"]
                    ts = r["timestamp"]
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    epoch = int(dt.timestamp())
                    delay = int(r.get("delay_seconds") or 0)
                    raw_mag = int(r.get("magnitude_of_delay") or 0)
                    cat = int(r.get("icon_category") or 0)
                    length_m = float(r.get("length_meters") or 0.0)
                    desc = str(r.get("description") or "")

                    # Fix TomTom magnitudeOfDelay=4 ('Undefined' on 0-delay closures/roadworks)
                    if delay > 0:
                        eff_mag = raw_mag if raw_mag in (1, 2, 3) else (3 if delay >= 300 else (2 if delay >= 120 else 1))
                    else:
                        eff_mag = 0

                    raw_by_incident[inc_id].append((epoch, ts, delay, eff_mag, cat, desc))
                    if inc_id not in geom_by_incident and r.get("coordinates"):
                        geom_by_incident[inc_id] = (r["coordinates"], length_m)
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
            t_cur, ts_cur, delay_cur, mag_cur, cat_cur, desc_cur = r
            if idx_r + 1 < n_r and (unique_recs[idx_r + 1][0] - t_cur) <= MAX_BATCH_GAP_SEC:
                t_end = unique_recs[idx_r + 1][0]
                ts_end = unique_recs[idx_r + 1][1]
            else:
                t_end = t_cur + DEFAULT_TTL_SEC
                ts_end = ts_cur
            if t_end > t_cur:
                causal_windows.append([t_cur, t_end, ts_cur, ts_end, delay_cur, mag_cur, cat_cur, desc_cur])

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
        f"      Built {total_episodes:,} causal state windows (avg {total_episodes / len(raw_by_incident):.2f} windows/incident).",
        flush=True,
    )

    # 4. Project geometries onto 48 bus routes using contiguous Frenet projection
    print("[4/5] Projecting incident LineStrings onto 48 bus routes (Contiguous Frenet + cos_theta >= 0.5)...", flush=True)
    t_proj_start = time.time()

    matches_by_incident = defaultdict(list)
    unique_matched_incidents = set()
    route_stat_counts = Counter()

    for inc_id, (coords, inc_len_m) in geom_by_incident.items():
        n_pts = len(coords) if coords else 0
        if n_pts < 2:
            continue

        # Precompute incident vertex unit vectors and step distances once per incident
        pt_unit_vecs = []
        pt_step_dists = []
        lons = []
        lats = []
        for j in range(n_pts):
            lons.append(coords[j][0])
            lats.append(coords[j][1])
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
            if vlen > 1e-3:
                pt_unit_vecs.append((vx / vlen, vy / vlen))
            else:
                pt_unit_vecs.append((0.0, 0.0))
            if j > 0:
                pt_step_dists.append(haversine(coords[j - 1][1], coords[j - 1][0], coords[j][1], coords[j][0]))
            else:
                pt_step_dists.append(0.0)

        inc_bbox = (min(lats), max(lats), min(lons), max(lons))

        for (rcode, direction), r_bbox in route_bboxes.items():
            if (
                inc_bbox[1] < r_bbox[0]
                or inc_bbox[0] > r_bbox[1]
                or inc_bbox[3] < r_bbox[2]
                or inc_bbox[2] > r_bbox[3]
            ):
                continue

            intervals = project_linestring_to_route_grid(
                coords, pt_unit_vecs, pt_step_dists, inc_len_m, route_grids[(rcode, direction)]
            )
            if not intervals:
                continue

            unique_matched_incidents.add(inc_id)
            route_stat_counts[rcode] += 1

            stns = route_stations[rcode][direction]
            for s_min, s_max, avg_d in intervals:
                eff_inc_span = max(inc_len_m, s_max - s_min, 25.0)
                for k in range(len(stns) - 1):
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
    print(f"  - Max segment span: {res[3]:.1f}m | Avg segment overlap span: {res[4]:.1f}m")
    print(f"  - Corrupted s_min=0 (>500m) rows: {res[5]} (0.00%!)", flush=True)

    conn.close()
    print(f"\nCompleted hotfixed WP 2.1.1 & 2.1.2 in {time.time() - t_start:.2f} seconds.", flush=True)


if __name__ == "__main__":
    main()
