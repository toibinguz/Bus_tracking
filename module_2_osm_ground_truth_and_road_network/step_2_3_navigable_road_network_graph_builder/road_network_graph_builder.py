"""
Step 2: Road Network Map Reconstruction Module
Queries and caches navigable road network graph for the Hanoi metropolitan region.
Serves both immediate route verification and future general map-matching & routing expansion.
"""

import os
import json
import time
import logging
from typing import Dict, Any, List, Tuple, Optional
import requests
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from module_2_osm_ground_truth_and_road_network.step_2_1_overpass_route_and_station_extractor import query_overpass_with_fallback, OVERPASS_MIRRORS

logger = logging.getLogger(__name__)

# Bounding box for Greater Hanoi Urban Transit Core (covering all 19 HUST corridors and extensions)
HANOI_URBAN_BBOX = {
    "south": 20.93,
    "west": 105.70,
    "north": 21.12,
    "east": 105.93
}

NAVIGABLE_HIGHWAY_FILTER = "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|unclassified"

def download_road_network_overpass(
    bbox: Optional[Dict[str, float]] = None,
    output_raw_json: str = "data/osm/raw/hanoi_road_network_raw.json",
    output_geojson: str = "data/osm/road_network/hanoi_road_network.geojson",
    force_download: bool = False
) -> Dict[str, Any]:
    """
    Downloads navigable road network (motorway, trunk, primary, secondary, tertiary, residential)
    for the urban core using Overpass API.
    """
    os.makedirs(os.path.dirname(output_raw_json), exist_ok=True)
    os.makedirs(os.path.dirname(output_geojson), exist_ok=True)

    if not force_download and os.path.exists(output_geojson) and os.path.exists(output_raw_json):
        print(f"[*] Found cached road network at {output_geojson}")
        with open(output_geojson, "r", encoding="utf-8") as f:
            cached_data = json.load(f)
        return {
            "status": "CACHED",
            "features_count": len(cached_data.get("features", [])),
            "geojson_path": output_geojson
        }

    b = bbox or HANOI_URBAN_BBOX
    bbox_str = f"{b['south']},{b['west']},{b['north']},{b['east']}"

    # Query ways with navigable highway tag and their nodes
    query = f"""
    [out:json][timeout:300];
    (
      way["highway"~"^({NAVIGABLE_HIGHWAY_FILTER})$"]({bbox_str});
    );
    out body;
    >;
    out skel qt;
    """

    print(f"[*] Querying Overpass for Hanoi road network in bounding box: {bbox_str} ...")
    raw_osm = query_overpass_with_fallback(query, timeout=300)

    print(f"[*] Saving raw road network JSON to {output_raw_json}...")
    with open(output_raw_json, "w", encoding="utf-8") as f:
        json.dump(raw_osm, f, ensure_ascii=False)

    print("[*] Reconstructing road network topological graph & GeoJSON...")
    elements = raw_osm.get("elements", [])
    nodes_map: Dict[int, Tuple[float, float]] = {}
    ways_list: List[Dict[str, Any]] = []

    for el in elements:
        t = el.get("type")
        if t == "node":
            nodes_map[el["id"]] = (el["lat"], el["lon"])
        elif t == "way":
            ways_list.append(el)

    features = []
    edges_meta = []

    for w in ways_list:
        w_nodes = w.get("nodes", [])
        w_tags = w.get("tags", {})
        coords = [
            [round(nodes_map[nid][1], 6), round(nodes_map[nid][0], 6)]  # GeoJSON [lon, lat]
            for nid in w_nodes if nid in nodes_map
        ]
        if len(coords) >= 2:
            feat = {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords
                },
                "properties": {
                    "osm_id": w["id"],
                    "highway": w_tags.get("highway", ""),
                    "name": w_tags.get("name", ""),
                    "oneway": w_tags.get("oneway", "no"),
                    "maxspeed": w_tags.get("maxspeed", ""),
                    "lanes": w_tags.get("lanes", ""),
                    "nodes_count": len(coords)
                }
            }
            features.append(feat)
            edges_meta.append({
                "osm_id": w["id"],
                "start_node": w_nodes[0],
                "end_node": w_nodes[-1],
                "highway": w_tags.get("highway", ""),
                "name": w_tags.get("name", ""),
                "oneway": w_tags.get("oneway", "no")
            })

    network_geojson = {
        "type": "FeatureCollection",
        "bbox": [b["west"], b["south"], b["east"], b["north"]],
        "features": features,
        "metadata": {
            "total_ways": len(features),
            "total_nodes": len(nodes_map),
            "highway_types": list(set(f["properties"]["highway"] for f in features))
        }
    }

    with open(output_geojson, "w", encoding="utf-8") as out_f:
        json.dump(network_geojson, out_f, ensure_ascii=False)

    print(f"[OK] Reconstructed road network: {len(features)} road links cached to {output_geojson}")
    return {
        "status": "DOWNLOADED",
        "features_count": len(features),
        "geojson_path": output_geojson,
        "metadata": network_geojson["metadata"]
    }

class RoadNetworkSpatialIndex:
    """
    High-performance spatial index for fast nearest road search and map matching.
    """
    def __init__(self, geojson_path: str = "data/osm/road_network/hanoi_road_network.geojson"):
        self.geojson_path = geojson_path
        self.geometries = []
        self.properties = []
        self.tree = None
        self._load()

    def _load(self):
        if not os.path.exists(self.geojson_path):
            raise FileNotFoundError(f"Road network GeoJSON not found at {self.geojson_path}")
        with open(self.geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for feat in data.get("features", []):
            coords = feat["geometry"]["coordinates"]
            if len(coords) >= 2:
                ls = LineString(coords)
                self.geometries.append(ls)
                self.properties.append(feat["properties"])
        if self.geometries:
            self.tree = STRtree(self.geometries)
            print(f"[OK] Initialized Spatial Index with {len(self.geometries)} road segments.")

    def find_nearest_roads(self, lon: float, lat: float, max_distance_deg: float = 0.001) -> List[Dict[str, Any]]:
        """Queries nearest roads to a given coordinate."""
        pt = Point(lon, lat)
        if not self.tree:
            return []
        indices = self.tree.query(pt.buffer(max_distance_deg))
        results = []
        for idx in indices:
            geom = self.geometries[idx]
            dist_deg = geom.distance(pt)
            results.append({
                "osm_id": self.properties[idx].get("osm_id"),
                "name": self.properties[idx].get("name"),
                "highway": self.properties[idx].get("highway"),
                "distance_deg": dist_deg
            })
        results.sort(key=lambda x: x["distance_deg"])
        return results

if __name__ == "__main__":
    download_road_network_overpass()

