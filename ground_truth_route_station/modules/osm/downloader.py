"""
Step 1: OSM Bus Routes & Stops Ingestion Module
Downloads all bus routes and stations in Hanoi from Overpass API uncut.
Converts and saves into GeoJSON format preserving all nodes, ways, and stop points.
"""

import os
import sys
import json
import time
import logging
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)

OVERPASS_MIRRORS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter"
]

def query_overpass_with_fallback(query: str, timeout: int = 300) -> Dict[str, Any]:
    """
    Executes an Overpass QL query with automatic failover across multiple mirrors.
    """
    last_error = None
    headers = {
        "User-Agent": "HUST-Bus-Tracking-Research/1.0 (academic; transportation-eta-project)"
    }
    
    for mirror in OVERPASS_MIRRORS:
        try:
            print(f"[*] Querying Overpass mirror: {mirror} ...")
            start_t = time.time()
            resp = requests.post(
                mirror,
                data={"data": query},
                headers=headers,
                timeout=timeout
            )
            elapsed = time.time() - start_t
            if resp.status_code == 200:
                data = resp.json()
                print(f"[OK] Response received from {mirror} in {elapsed:.1f}s ({len(data.get('elements', []))} elements)")
                return data
            else:
                print(f"[!] Mirror {mirror} returned status {resp.status_code}: {resp.text[:200]}")
                last_error = f"Status {resp.status_code}"
        except Exception as e:
            print(f"[!] Mirror {mirror} failed: {e}")
            last_error = str(e)
            time.sleep(2)

    raise RuntimeError(f"All Overpass mirrors failed. Last error: {last_error}")

def osm_to_geojson_uncut(osm_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms uncut OSM raw JSON (relations, ways, nodes) into a standard GeoJSON FeatureCollection.
    Preserves all node coordinates, way line geometries, and bus stops/platforms.
    """
    elements = osm_json.get("elements", [])
    nodes = {}
    ways = {}
    relations = []

    # 1. Index all nodes
    for el in elements:
        t = el.get("type")
        if t == "node":
            nodes[el["id"]] = {
                "id": el["id"],
                "lat": el["lat"],
                "lon": el["lon"],
                "tags": el.get("tags", {})
            }
        elif t == "way":
            ways[el["id"]] = {
                "id": el["id"],
                "nodes": el.get("nodes", []),
                "tags": el.get("tags", {})
            }
        elif t == "relation":
            relations.append(el)

    features = []

    # 2. Add Bus Stops / Platforms as Point features
    for nid, nd in nodes.items():
        tags = nd["tags"]
        is_bus_stop = (
            tags.get("highway") == "bus_stop" or
            tags.get("public_transport") in ("platform", "stop_position") or
            "bus" in tags
        )
        if is_bus_stop:
            feat = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [nd["lon"], nd["lat"]]
                },
                "properties": {
                    "osm_id": nid,
                    "osm_type": "node",
                    "name": tags.get("name", ""),
                    "ref": tags.get("ref", ""),
                    "highway": tags.get("highway", ""),
                    "public_transport": tags.get("public_transport", ""),
                    "tags": tags
                }
            }
            features.append(feat)

    # 3. Add Ways as LineString features
    for wid, w in ways.items():
        coords = []
        for nid in w["nodes"]:
            if nid in nodes:
                coords.append([nodes[nid]["lon"], nodes[nid]["lat"]])
        if len(coords) >= 2:
            feat = {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords
                },
                "properties": {
                    "osm_id": wid,
                    "osm_type": "way",
                    "tags": w["tags"],
                    "node_count": len(coords)
                }
            }
            features.append(feat)

    # 4. Add Relations summary feature
    for rel in relations:
        rel_tags = rel.get("tags", {})
        members = rel.get("members", [])
        feat = {
            "type": "Feature",
            "geometry": None,
            "properties": {
                "osm_id": rel["id"],
                "osm_type": "relation",
                "route": rel_tags.get("route", ""),
                "ref": rel_tags.get("ref", ""),
                "name": rel_tags.get("name", ""),
                "from": rel_tags.get("from", ""),
                "to": rel_tags.get("to", ""),
                "operator": rel_tags.get("operator", ""),
                "members_count": len(members),
                "members": members,
                "tags": rel_tags
            }
        }
        features.append(feat)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total_elements": len(elements),
            "total_nodes": len(nodes),
            "total_ways": len(ways),
            "total_relations": len(relations),
            "extracted_features": len(features)
        }
    }

def download_all_hanoi_bus_routes_uncut(
    output_raw_json: str = "data/osm/raw/hanoi_bus_routes_raw.json",
    output_geojson: str = "data/osm/raw/hanoi_bus_routes_raw.geojson",
    route_refs: Optional[List[str]] = None,
    force_download: bool = False
) -> Dict[str, Any]:
    """
    Step 1 Main Execution:
    Queries Overpass for bus routes, uncut nodes, member ways, and platforms/stops.
    Saves raw Overpass JSON and converted GeoJSON.
    """
    os.makedirs(os.path.dirname(output_raw_json), exist_ok=True)
    os.makedirs(os.path.dirname(output_geojson), exist_ok=True)

    if not force_download and os.path.exists(output_raw_json) and os.path.exists(output_geojson):
        print(f"[*] Found cached raw OSM bus routes: {output_raw_json}")
        with open(output_raw_json, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        elems = raw_data.get("elements", [])
        if len(elems) > 0:
            return {"status": "CACHED", "elements_count": len(elems), "raw_json_path": output_raw_json, "geojson_path": output_geojson}

    # If route_refs provided, construct regex matching both padded and unpadded numbers
    if route_refs:
        ref_patterns = []
        for r in route_refs:
            r_str = str(r).strip()
            unpadded = r_str.lstrip("0")
            padded = "0" + unpadded if len(unpadded) == 1 else unpadded
            ref_patterns.extend([r_str, unpadded, padded])
        ref_pattern_str = "|".join(sorted(list(set(ref_patterns))))
        ref_filter = f'["ref"~"^({ref_pattern_str})$"]'
    else:
        # Default target corridors
        ref_filter = '["ref"~"^(0?[1-9]|0?[1-9][0-9]|BRT.*|E.*)$"]'

    query = f"""
    [out:json][timeout:180];
    (
      relation["type"="route"]["route"="bus"]{ref_filter};
    );
    out body;
    >;
    out body qt;
    """

    print(f"[*] Downloading bus routes with filter: {ref_filter} ...")
    raw_data = query_overpass_with_fallback(query, timeout=180)

    print(f"[*] Saving raw Overpass JSON to {output_raw_json}...")
    with open(output_raw_json, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False)

    print(f"[*] Converting to GeoJSON uncut and saving to {output_geojson}...")
    geojson_data = osm_to_geojson_uncut(raw_data)
    with open(output_geojson, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f, ensure_ascii=False)

    meta = geojson_data.get("metadata", {})
    print(f"[OK] Downloaded & saved: {meta.get('total_relations', 0)} relations, {meta.get('total_ways', 0)} ways, {meta.get('total_nodes', 0)} nodes.")
    return {
        "status": "DOWNLOADED",
        "raw_json_path": output_raw_json,
        "geojson_path": output_geojson,
        "metadata": meta
    }

if __name__ == "__main__":
    download_all_hanoi_bus_routes_uncut(route_refs=["31", "32", "26", "08A", "03A", "21A", "02", "19", "22A", "25", "27", "28", "35A", "41", "51", "E01"])

