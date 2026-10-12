"""
Step 3: Quantitative Telemetry-Route Verification & Stop Evaluator Module
Verifies telemetry pings against OSM route polylines using perpendicular projections,
computes spatial error distributions, and validates bus stop physical ground-truth.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
import numpy as np

from .projection import RoutePolylineProjector, haversine_distance_m

logger = logging.getLogger(__name__)

ON_ROUTE_STRICT_METERS = 25.0
ON_ROUTE_TOLERANT_METERS = 40.0
STOP_DWELL_RADIUS_METERS = 35.0

def evaluate_route_telemetry(
    route_ref: str,
    route_metadata_path: str,
    telemetry_pings: List[Dict[str, Any]],
    output_dir: str = "data/verification"
) -> Dict[str, Any]:
    """
    Evaluates telemetry pings against the reconstructed OSM route geometry and stations.
    
    Args:
        route_ref: Bus route number/ref (e.g. '31', '32', '26')
        route_metadata_path: Path to route_{ref}_metadata.json
        telemetry_pings: List of preprocessed telemetry pings for this route
        output_dir: Directory to store verification results
        
    Returns:
        Structured dictionary of quantitative verification metrics.
    """
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(route_metadata_path):
        raise FileNotFoundError(f"Route metadata not found at {route_metadata_path}")

    with open(route_metadata_path, "r", encoding="utf-8") as f:
        route_meta = json.load(f)

    variants = route_meta.get("variants", [])
    if not variants:
        raise ValueError(f"No route variants found in {route_metadata_path}")

    # Build projectors for each variant (Outbound vs Inbound)
    variant_projectors = []
    for v_idx, v in enumerate(variants):
        geom_input = v.get("ways") if v.get("ways") else v.get("coordinates", [])
        if len(geom_input) >= 1:
            proj = RoutePolylineProjector(geom_input)
            variant_projectors.append({
                "variant_idx": v_idx,
                "name": v.get("name", f"Variant {v_idx}"),
                "from": v.get("from", ""),
                "to": v.get("to", ""),
                "length_km": v.get("length_km", 0.0),
                "stops": v.get("stops", []),
                "projector": proj
            })

    if not variant_projectors:
        raise ValueError("Could not create polyline projectors for route.")

    total_pings = len(telemetry_pings)
    if total_pings == 0:
        return {
            "route_ref": route_ref,
            "status": "NO_TELEMETRY",
            "message": "No telemetry pings available for verification."
        }

    # Evaluate pings
    evaluated_pings = []
    perp_errors = []
    strict_on_route_count = 0
    tolerant_on_route_count = 0
    off_route_count = 0

    moving_pings = [p for p in telemetry_pings if p["speed"] > 5.0]
    dwell_pings = [p for p in telemetry_pings if p["speed"] <= 5.0]

    for ping in telemetry_pings:
        lat = ping["lat"]
        lon = ping["lon"]

        # Check against all variants, pick closest
        best_res = None
        best_v_idx = -1
        min_perp = float("inf")

        for vp in variant_projectors:
            res = vp["projector"].project_ping(lat, lon)
            if res["perp_dist_m"] < min_perp:
                min_perp = res["perp_dist_m"]
                best_res = res
                best_v_idx = vp["variant_idx"]

        is_strict = (min_perp <= ON_ROUTE_STRICT_METERS)
        is_tolerant = (min_perp <= ON_ROUTE_TOLERANT_METERS)

        if is_strict:
            strict_on_route_count += 1
        if is_tolerant:
            tolerant_on_route_count += 1
        else:
            off_route_count += 1

        perp_errors.append(min_perp)
        evaluated_pings.append({
            "vehicle_id": ping.get("vehicle_id"),
            "lat": lat,
            "lon": lon,
            "speed": ping.get("speed"),
            "perp_dist_m": min_perp,
            "best_variant_idx": best_v_idx,
            "chainage_m": best_res["chainage_m"],
            "is_on_route": is_tolerant,
            "is_strictly_perpendicular": best_res["is_strictly_perpendicular"]
        })

    # Statistical distribution
    errors_arr = np.array(perp_errors)
    mean_error = float(np.mean(errors_arr))
    median_error = float(np.median(errors_arr))
    p90_error = float(np.percentile(errors_arr, 90))
    p95_error = float(np.percentile(errors_arr, 95))
    p99_error = float(np.percentile(errors_arr, 99))
    max_error = float(np.max(errors_arr))

    # Evaluate Bus Stops against Dwell Points
    stop_evaluations = []
    all_stops = []
    for vp in variant_projectors:
        for st in vp["stops"]:
            all_stops.append({
                "variant_idx": vp["variant_idx"],
                "sequence": st["sequence"],
                "osm_id": st["osm_id"],
                "name": st["name"],
                "lat": st["lat"],
                "lon": st["lon"]
            })

    confirmed_stops_count = 0
    passing_stops_count = 0
    unverified_stops_count = 0

    for st in all_stops:
        s_lat, s_lon = st["lat"], st["lon"]

        # Find closest dwell ping
        min_dwell_dist = float("inf")
        dwells_within_radius = 0
        for dw in dwell_pings:
            d_m = haversine_distance_m(s_lat, s_lon, dw["lat"], dw["lon"])
            if d_m < min_dwell_dist:
                min_dwell_dist = d_m
            if d_m <= STOP_DWELL_RADIUS_METERS:
                dwells_within_radius += 1

        # Find closest moving ping
        min_any_dist = float("inf")
        for p in telemetry_pings:
            d_m = haversine_distance_m(s_lat, s_lon, p["lat"], p["lon"])
            if d_m < min_any_dist:
                min_any_dist = d_m

        if dwells_within_radius >= 1:
            verdict = "CONFIRMED_ACTIVE_DWELL"
            confirmed_stops_count += 1
        elif min_any_dist <= ON_ROUTE_TOLERANT_METERS:
            verdict = "ON_ROUTE_TRANSIT_CONFIRMED"
            passing_stops_count += 1
        else:
            verdict = "UNVERIFIED_IN_SAMPLE"
            unverified_stops_count += 1

        stop_evaluations.append({
            "osm_id": st["osm_id"],
            "name": st["name"],
            "sequence": st["sequence"],
            "variant_idx": st["variant_idx"],
            "lat": st["lat"],
            "lon": st["lon"],
            "min_dwell_dist_m": round(min_dwell_dist, 1) if min_dwell_dist != float("inf") else -1,
            "dwell_pings_within_35m": dwells_within_radius,
            "min_telemetry_dist_m": round(min_any_dist, 1) if min_any_dist != float("inf") else -1,
            "status": verdict
        })

    # Summary payload
    summary = {
        "route_ref": route_ref,
        "variants_count": len(variant_projectors),
        "total_pings_evaluated": total_pings,
        "moving_pings_count": len(moving_pings),
        "dwell_pings_count": len(dwell_pings),
        "strict_on_route_pct": round(strict_on_route_count / total_pings * 100.0, 2),
        "tolerant_on_route_pct": round(tolerant_on_route_count / total_pings * 100.0, 2),
        "off_route_pct": round(off_route_count / total_pings * 100.0, 2),
        "metrics": {
            "mean_perpendicular_error_m": round(mean_error, 2),
            "median_perpendicular_error_m": round(median_error, 2),
            "p90_error_m": round(p90_error, 2),
            "p95_error_m": round(p95_error, 2),
            "p99_error_m": round(p99_error, 2),
            "max_error_m": round(max_error, 2)
        },
        "station_verification": {
            "total_osm_stops": len(all_stops),
            "confirmed_dwell_stops": confirmed_stops_count,
            "passing_transit_stops": passing_stops_count,
            "unverified_stops": unverified_stops_count,
            "effective_coverage_pct": round((confirmed_stops_count + passing_stops_count) / len(all_stops) * 100.0, 2) if all_stops else 0.0
        },
        "stops_detail": stop_evaluations
    }

    out_file = os.path.join(output_dir, f"verification_route_{route_ref}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"[OK] Route {route_ref} verified: {summary['tolerant_on_route_pct']}% pings on-route (median error: {summary['metrics']['median_perpendicular_error_m']}m). Output: {out_file}")
    return summary

if __name__ == "__main__":
    pass

