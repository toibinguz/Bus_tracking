"""
Module 1 - Step 1.4: Causal TomTom Incident Spatial Projection -> Silver Parquet.
- Reads static canonical shapes/stations from SQLite (strictly read-only).
- Reads raw TomTom observations from HDFS Silver (`--hdfs-snapshot`), JSONL glob, or Bronze Parquet.
- Projects onto 1D Frenet corridors and writes directly to Silver Parquet (`fact_route_tomtom_incidents`).
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
from datetime import datetime, timezone
import glob
import io
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from urllib.parse import quote
from uuid import uuid4

import shapely
from shapely import STRtree

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from config.system_config import (
    DEFAULT_DB_PATH,
    MAX_CORRIDOR_CROSS_TRACK_M,
    RAW_DATA_DIR,
    TOMTOM_BBOX_PAD_DEG,
    TOMTOM_DEFAULT_TTL_SEC,
    TOMTOM_GRID_SCALE,
    TOMTOM_MAX_BATCH_GAP_SEC,
    TOMTOM_MIN_COS_THETA,
    TZ_HANOI,
)
from modules.ingestion.projection.route_matcher import (
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

SILVER_INCIDENT_COLUMNS = (
    "incident_id",
    "episode_idx",
    "route_code",
    "direction",
    "from_station_order",
    "to_station_order",
    "from_station_name",
    "to_station_name",
    "s_min_m",
    "s_max_m",
    "overlap_length_m",
    "t_start_epoch",
    "t_end_epoch",
    "t_start_utc",
    "t_end_utc",
    "icon_category",
    "magnitude_of_delay",
    "delay_seconds",
    "d_perp_m",
    "description",
)

def _silver_incident_arrow_schema():
    import pyarrow as pa

    return pa.schema(
        [
            ("incident_id", pa.string()),
            ("episode_idx", pa.int64()),
            ("route_code", pa.string()),
            ("direction", pa.string()),
            ("from_station_order", pa.int64()),
            ("to_station_order", pa.int64()),
            ("from_station_name", pa.string()),
            ("to_station_name", pa.string()),
            ("s_min_m", pa.float64()),
            ("s_max_m", pa.float64()),
            ("overlap_length_m", pa.float64()),
            ("t_start_epoch", pa.int64()),
            ("t_end_epoch", pa.int64()),
            ("t_start_utc", pa.string()),
            ("t_end_utc", pa.string()),
            ("icon_category", pa.int64()),
            ("magnitude_of_delay", pa.int64()),
            ("delay_seconds", pa.int64()),
            ("d_perp_m", pa.float64()),
            ("description", pa.string()),
        ]
    )


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


def project_incidents_to_route_facts(raw_records, route_shapes, route_stations):
    """Pure SSOT causal TomTom episode construction + 2-level STRtree Frenet projection."""
    route_models = {}
    route_keys = []
    route_bbox_geoms = []
    route_station_s = defaultdict(lambda: {"go": [], "re": []})

    for rcode in sorted(route_shapes):
        for direction in ("go", "re"):
            pts = route_shapes[rcode].get(direction, [])
            if len(pts) >= 2:
                lats = [p[1] for p in pts]
                lons = [p[2] for p in pts]
                route_models[(rcode, direction)] = ShapeProjectionModel.build(pts)
                route_keys.append((rcode, direction))
                route_bbox_geoms.append(
                    shapely.box(
                        min(lons) - 0.0008,
                        min(lats) - 0.0008,
                        max(lons) + 0.0008,
                        max(lats) + 0.0008,
                    )
                )
            route_station_s[rcode][direction] = [
                float(st[2]) for st in route_stations.get(rcode, {}).get(direction, [])
            ]

    route_rtree = STRtree(route_bbox_geoms) if route_bbox_geoms else None

    parsed_records = []
    for r in raw_records:
        try:
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
            coords = r.get("coordinates")
            if coords is None and r.get("coordinates_json"):
                coords = json.loads(r["coordinates_json"])
        except (KeyError, TypeError, ValueError):
            continue
        parsed_records.append((epoch, str(inc_id), delay, length_m, raw_mag, cat, str(ts), desc, coords))

    # Deterministic order guarantees identical geometry & episodes regardless of JSONL vs HDFS Parquet read order.
    parsed_records.sort(key=lambda item: (item[0], item[1], item[2], item[3], json.dumps(item[4:], sort_keys=True)))

    raw_by_incident = defaultdict(list)
    geom_by_incident = {}
    for epoch, inc_id, delay, length_m, raw_mag, cat, ts_str, desc, coords in parsed_records:
        if delay > 0:
            eff_mag = raw_mag if raw_mag in (1, 2, 3) else (3 if delay >= 300 else (2 if delay >= 120 else 1))
        else:
            eff_mag = 0
        raw_by_incident[inc_id].append((epoch, ts_str, delay, eff_mag, cat, desc))
        if inc_id not in geom_by_incident and coords:
            geom_by_incident[inc_id] = (coords, length_m)

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

    matches_by_incident = defaultdict(list)
    unique_matched_incidents = set()
    route_stat_counts = Counter()

    inc_ids_list = []
    inc_meta = {}
    inc_boxes = []
    for inc_id in sorted(geom_by_incident):
        coords, inc_len_m = geom_by_incident[inc_id]
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

        for ri in sorted(by_route):
            cand_inc_indices = sorted(by_route[ri])
            rcode, direction = route_keys[ri]
            shape_model = route_models[(rcode, direction)]
            stns = route_stations.get(rcode, {}).get(direction, [])
            stn_s = route_station_s[rcode][direction]
            n_stns = len(stns)
            if n_stns < 2 or not cand_inc_indices:
                continue

            all_lats, all_lons, all_uxs, all_uys, owner_pos, local_js = [], [], [], [], [], []
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

    deduped = {}
    for inc_id, matches in matches_by_incident.items():
        for ep_idx, ep in enumerate(episodes_by_incident.get(inc_id, [])):
            t_start_ep, t_end_ep, t_start_utc, t_end_utc, raw_delay, eff_mag, cat, desc = ep
            for m in matches:
                rcode, direction, from_order, to_order, from_name, to_name, s_seg_min, s_seg_max, overlap_len, avg_d, eff_inc_span = m
                prop_delay = max(1, int(round(raw_delay * (overlap_len / eff_inc_span)))) if raw_delay > 0 else 0
                pk = (inc_id, ep_idx, rcode, direction, from_order, to_order)
                deduped[pk] = (
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

    fact_rows = sorted(
        deduped.values(),
        key=lambda r: (r[2], r[3], r[11], r[0], r[1], r[4], r[5]),
    )
    stats = {
        "unique_entities": len(raw_by_incident),
        "total_episodes": total_episodes,
        "matched_incidents": len(unique_matched_incidents),
        "routes_with_signal": len(route_stat_counts),
        "fact_rows": len(fact_rows),
    }
    return fact_rows, stats


def write_silver_incidents_parquet(fact_rows, output_dir, *, clean: bool = True):
    """Write projected TomTom incidents directly to Hive-partitioned Snappy Parquet."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    by_route = defaultdict(list)
    for row in fact_rows:
        by_route[row[2]].append(row)

    if clean:
        for existing in out_root.glob("route_code=*"):
            if existing.is_dir() and existing.name.removeprefix("route_code=") not in by_route:
                shutil.rmtree(existing)

    schema = _silver_incident_arrow_schema()
    written_routes = 0
    for rcode, rows in sorted(by_route.items()):
        part_dir = out_root / f"route_code={rcode}"
        part_dir.mkdir(parents=True, exist_ok=True)
        out_file = part_dir / "part-00000.snappy.parquet"
        tmp_file = part_dir / f"part-00000.{uuid4()}.tmp"
        cols = {
            col_name: [r[idx] for r in rows]
            for idx, col_name in enumerate(SILVER_INCIDENT_COLUMNS)
        }
        table = pa.table(cols, schema=schema)
        pq.write_table(table, tmp_file, compression="snappy")
        os.replace(tmp_file, out_file)
        written_routes += 1

    return {"output_dir": str(out_root), "routes_written": written_routes, "rows_written": len(fact_rows)}


def _read_raw_incidents_from_hdfs(snapshot_id: str, compose_file: Path):
    import pyarrow.parquet as pq
    from modules.lakehouse.hdfs.hf_bronze import DockerHdfs

    if len(snapshot_id) != 64 or any(c not in "0123456789abcdef" for c in snapshot_id):
        raise ValueError("invalid snapshot ID")
    hdfs = DockerHdfs(compose_file)
    pub = json.loads(hdfs.read(f"/bus-eta/v1/_published/history_snapshots/{snapshot_id}.json"))
    if not pub.get("incident_observations"):
        return []
    inc_path = pub["snapshot_path"].rstrip("/") + "/incident_observations"
    listing = hdfs.call("-ls", "-R", inc_path).decode("utf-8", errors="replace")
    parts = sorted(
        line.split()[-1]
        for line in listing.splitlines()
        if line.split() and line.split()[-1].endswith(".parquet")
    )
    records = []
    for part in parts:
        table = pq.read_table(io.BytesIO(hdfs.read(part)), columns=["raw_json"])
        for raw_str in table["raw_json"].to_pylist():
            records.append(json.loads(raw_str))
    return records


def _load_canonical_geometry(db_path: Path, silver_tel_dir: Path | None):
    uri = "file:" + quote(str(db_path.resolve()).replace("\\", "/"), safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.cursor()
        target_routes = []
        if silver_tel_dir and silver_tel_dir.is_dir():
            target_routes = sorted(
                d.name.removeprefix("route_code=")
                for d in silver_tel_dir.glob("route_code=*")
                if d.is_dir()
            )
        if not target_routes:
            target_routes = sorted(
                {str(r[0]) for r in cur.execute("SELECT DISTINCT route_code FROM canonical_route_master").fetchall()}
            )
        if not target_routes:
            raise ValueError("no canonical routes found in DB")

        placeholders = ",".join("?" for _ in target_routes)
        route_shapes = defaultdict(lambda: {"go": [], "re": []})
        for rcode, direction, pt_ord, lat, lon, s_m in cur.execute(
            f"SELECT route_code, direction, point_order, lat, lon, cum_distance_m "
            f"FROM canonical_shape_master WHERE route_code IN ({placeholders}) "
            f"ORDER BY route_code, direction, point_order",
            target_routes,
        ):
            route_shapes[str(rcode)][str(direction)].append((int(pt_ord), float(lat), float(lon), float(s_m)))

        route_stations = defaultdict(lambda: {"go": [], "re": []})
        for rcode, direction, order, name, s_m in cur.execute(
            f"SELECT route_code, direction, station_order, station_name, cum_distance_m "
            f"FROM canonical_station_master WHERE route_code IN ({placeholders}) "
            f"ORDER BY route_code, direction, station_order",
            target_routes,
        ):
            route_stations[str(rcode)][str(direction)].append((int(order), str(name), float(s_m)))
    finally:
        conn.close()
    return target_routes, route_shapes, route_stations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=Path(DB_PATH))
    parser.add_argument("--silver-tel-dir", type=Path, default=None)
    parser.add_argument("--incidents-glob", default=INCIDENTS_GLOB)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--hdfs-snapshot", help="64-hex HDFS snapshot ID to pull incident_observations from")
    args = parser.parse_args(argv)

    t_start = time.time()
    print("=" * 84, flush=True)
    print("TOMTOM INCIDENT FRENET PROJECTION -> SILVER PARQUET (NO SQLITE WRITES)", flush=True)
    print("=" * 84, flush=True)

    target_routes, route_shapes, route_stations = _load_canonical_geometry(args.db_path, args.silver_tel_dir)
    print(f"[1/3] Loaded canonical shapes/stations (RO) for {len(target_routes)} routes.", flush=True)

    raw_records = []
    if args.hdfs_snapshot:
        print(f"[2/3] Reading incident_observations from HDFS snapshot {args.hdfs_snapshot[:12]}...", flush=True)
        raw_records = _read_raw_incidents_from_hdfs(args.hdfs_snapshot, ROOT / "docker-compose.hdfs.yml")
    else:
        files = sorted(glob.glob(str(args.incidents_glob)))
        if not files:
            raise FileNotFoundError(f"No incident files found at {args.incidents_glob}")
        print(f"[2/3] Reading {len(files)} TomTom JSONL files...", flush=True)
        for fpath in files:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw_records.append(json.loads(line))
                    except Exception:
                        pass

    fact_rows, stats = project_incidents_to_route_facts(raw_records, route_shapes, route_stations)
    write_info = write_silver_incidents_parquet(fact_rows, args.output_dir, clean=True)
    print(
        f"[3/3] Projected {stats['matched_incidents']:,}/{stats['unique_entities']:,} incidents "
        f"({stats['total_episodes']:,} episodes) -> {write_info['rows_written']:,} Silver Parquet rows "
        f"across {write_info['routes_written']} routes in {time.time() - t_start:.2f}s.",
        flush=True,
    )
    return {**stats, **write_info}


if __name__ == "__main__":
    main()
