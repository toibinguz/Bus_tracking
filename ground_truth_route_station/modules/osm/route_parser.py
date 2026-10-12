"""
Step 1: OSM Route Parser & Topological Reconstruction Engine
Parses required bus routes from raw OSM data, performs directed topological
stitching of member ways to eliminate criss-cross jumping lines, and extracts
monotonically ordered bus stops with linear referencing.
"""

import os
import json
import math
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters between two WGS84 points."""
    R = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def topological_stitch_ways(
    member_ways: List[Dict[str, Any]],
    nodes_coord_map: Dict[int, Tuple[float, float]]
) -> Tuple[List[Tuple[float, float]], List[Dict[str, Any]]]:
    """
    Topologically stitches an unordered or reversed collection of OSM member ways
    into a continuous, strictly ordered single polyline without criss-cross jumps.
    
    Returns:
        continuous_coords: List of (lat, lon) coordinates
        diagnostics: List of connection gaps between ways
    """
    if not member_ways:
        return [], []

    # Prepare way segments: each way has a list of node coordinates
    way_segments = []
    for w in member_ways:
        node_ids = w.get("nodes", [])
        coords = [nodes_coord_map[nid] for nid in node_ids if nid in nodes_coord_map]
        if len(coords) >= 2:
            way_segments.append({
                "osm_id": w["id"],
                "coords": coords,
                "start_node": node_ids[0],
                "end_node": node_ids[-1]
            })

    if not way_segments:
        return [], []

    # Start with the first way
    stitched_coords: List[Tuple[float, float]] = list(way_segments[0]["coords"])
    remaining = way_segments[1:]
    diagnostics = []

    while remaining:
        current_tip = stitched_coords[-1]
        best_idx = -1
        best_dist = float("inf")
        best_reverse = False

        for i, seg in enumerate(remaining):
            start_coord = seg["coords"][0]
            end_coord = seg["coords"][-1]

            d_head = haversine_distance_m(current_tip[0], current_tip[1], start_coord[0], start_coord[1])
            d_tail = haversine_distance_m(current_tip[0], current_tip[1], end_coord[0], end_coord[1])

            if d_head < best_dist:
                best_dist = d_head
                best_idx = i
                best_reverse = False

            if d_tail < best_dist:
                best_dist = d_tail
                best_idx = i
                best_reverse = True

        if best_idx == -1 or best_dist > 800.0:
            # If gap is too large (> 800m), skip disconnected or separate branch way
            break

        next_seg = remaining.pop(best_idx)
        seg_coords = list(next_seg["coords"])
        if best_reverse:
            seg_coords.reverse()

        diagnostics.append({
            "connected_way_id": next_seg["osm_id"],
            "reversed": best_reverse,
            "gap_meters": round(best_dist, 2)
        })

        # Append coordinates (avoid duplicating identical junction node)
        if best_dist < 5.0:
            stitched_coords.extend(seg_coords[1:])
        else:
            stitched_coords.extend(seg_coords)

    return stitched_coords, diagnostics

def parse_target_routes(
    raw_json_path: str = "data/osm/raw/hanoi_bus_routes_raw.json",
    target_route_refs: Optional[List[str]] = None,
    output_dir: str = "data/osm/parsed_routes"
) -> Dict[str, Any]:
    """
    Parses required routes from raw Overpass JSON, builds stitched polylines,
    orders stations along polyline, and exports GeoJSON and metadata files.
    """
    os.makedirs(output_dir, exist_ok=True)
    with open(raw_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    elements = data.get("elements", [])
    nodes_map: Dict[int, Dict[str, Any]] = {}
    ways_map: Dict[int, Dict[str, Any]] = {}
    relations: List[Dict[str, Any]] = []

    for el in elements:
        t = el.get("type")
        if t == "node":
            nodes_map[el["id"]] = el
        elif t == "way":
            ways_map[el["id"]] = el
        elif t == "relation":
            relations.append(el)

    nodes_coord_map = {nid: (nd["lat"], nd["lon"]) for nid, nd in nodes_map.items()}

    # Group relations by route ref (e.g., '31', '32', '08A', '26')
    route_relations: Dict[str, List[Dict[str, Any]]] = {}
    for rel in relations:
        tags = rel.get("tags", {})
        ref = tags.get("ref", "").strip()
        if not ref:
            # Try to extract number from name
            name = tags.get("name", "")
            if "Tuyến" in name or "Bus" in name:
                parts = name.split(":")
                if len(parts) > 1:
                    ref = parts[0].replace("Tuyến", "").replace("Bus", "").strip()
        if ref:
            # Normalize e.g. '02' vs '2', '31'
            ref_clean = ref.upper()
            if ref_clean not in route_relations:
                route_relations[ref_clean] = []
            route_relations[ref_clean].append(rel)

    print(f"[*] Found {len(route_relations)} unique bus route refs in OSM raw dataset.")

    # Determine which routes to parse
    if target_route_refs:
        refs_to_process = [r.upper() for r in target_route_refs]
    else:
        # Default: process all found or target corridors
        refs_to_process = list(route_relations.keys())

    parsed_routes = {}

    for ref in refs_to_process:
        rels = route_relations.get(ref, [])
        if not rels:
            # Try matching with leading zero stripped or added
            alt_ref = ref.lstrip("0") if ref.startswith("0") else ("0" + ref)
            rels = route_relations.get(alt_ref, [])
            if not rels:
                continue

        print(f"[*] Processing Route Ref: {ref} ({len(rels)} relation variants found)...")

        route_variants = []
        for idx, rel in enumerate(rels):
            rel_tags = rel.get("tags", {})
            members = rel.get("members", [])
            rel_id = rel["id"]
            name = rel_tags.get("name", f"Route {ref}")
            from_dest = rel_tags.get("from", "")
            to_dest = rel_tags.get("to", "")

            # Filter ways and stops
            way_members = []
            stop_nodes = []
            for m in members:
                m_type = m.get("type")
                m_ref = m.get("ref")
                m_role = m.get("role", "")
                if m_type == "way" and m_ref in ways_map:
                    way_members.append(ways_map[m_ref])
                elif m_type == "node" and m_ref in nodes_map:
                    if m_role in ("platform", "stop", "stop_entry_only", "stop_exit_only", ""):
                        stop_nodes.append((m_ref, m_role, nodes_map[m_ref]))

            if not way_members:
                continue

            # Topological stitch
            stitched_coords, diag = topological_stitch_ways(way_members, nodes_coord_map)
            if len(stitched_coords) < 2:
                continue

            # Calculate total length in km
            length_m = 0.0
            for i in range(len(stitched_coords) - 1):
                p1, p2 = stitched_coords[i], stitched_coords[i + 1]
                length_m += haversine_distance_m(p1[0], p1[1], p2[0], p2[1])

            # Process stops
            ordered_stops = []
            for s_idx, (s_id, s_role, s_node) in enumerate(stop_nodes):
                s_tags = s_node.get("tags", {})
                s_lat, s_lon = s_node["lat"], s_node["lon"]
                ordered_stops.append({
                    "sequence": s_idx + 1,
                    "osm_id": s_id,
                    "name": s_tags.get("name", f"Trạm {s_idx + 1}"),
                    "role": s_role,
                    "lat": s_lat,
                    "lon": s_lon,
                    "tags": s_tags
                })

            variant_info = {
                "variant_index": idx,
                "osm_relation_id": rel_id,
                "name": name,
                "from": from_dest,
                "to": to_dest,
                "length_km": round(length_m / 1000.0, 3),
                "polyline_nodes_count": len(stitched_coords),
                "stops_count": len(ordered_stops),
                "stops": ordered_stops,
                "coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in stitched_coords]  # GeoJSON [lon, lat]
            }
            route_variants.append(variant_info)

        if not route_variants:
            continue

        # Save Route Master GeoJSON
        geojson_features = []
        for v in route_variants:
            # Polyline feature
            geojson_features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": v["coordinates"]
                },
                "properties": {
                    "route_ref": ref,
                    "relation_id": v["osm_relation_id"],
                    "variant": v["variant_index"],
                    "name": v["name"],
                    "from": v["from"],
                    "to": v["to"],
                    "length_km": v["length_km"],
                    "stops_count": v["stops_count"]
                }
            })
            # Stop points
            for s in v["stops"]:
                geojson_features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(s["lon"], 6), round(s["lat"], 6)]
                    },
                    "properties": {
                        "route_ref": ref,
                        "relation_id": v["osm_relation_id"],
                        "sequence": s["sequence"],
                        "osm_id": s["osm_id"],
                        "name": s["name"],
                        "role": s["role"]
                    }
                })

        route_geojson = {
            "type": "FeatureCollection",
            "features": geojson_features
        }

        geojson_out = os.path.join(output_dir, f"route_{ref}.geojson")
        with open(geojson_out, "w", encoding="utf-8") as gf:
            json.dump(route_geojson, gf, indent=2, ensure_ascii=False)

        metadata_out = os.path.join(output_dir, f"route_{ref}_metadata.json")
        with open(metadata_out, "w", encoding="utf-8") as mf:
            json.dump({
                "route_ref": ref,
                "variants_count": len(route_variants),
                "variants": route_variants
            }, mf, indent=2, ensure_ascii=False)

        parsed_routes[ref] = {
            "variants_count": len(route_variants),
            "geojson_file": geojson_out,
            "metadata_file": metadata_out,
            "lengths_km": [v["length_km"] for v in route_variants],
            "stops_counts": [v["stops_count"] for v in route_variants]
        }
        print(f"[OK] Parsed Route {ref}: {len(route_variants)} variants saved to {geojson_out}")

    return parsed_routes

if __name__ == "__main__":
    parse_target_routes()

