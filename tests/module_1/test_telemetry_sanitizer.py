"""Unit tests for telemetry_sanitizer: OOB cache isolation & GPS drift min-distance guard."""

from module_1_data_ingestion_and_preprocessing.step_1_3_telemetry_kinematic_sanitizer.telemetry_sanitizer import (
    sanitize_and_validate_telemetry,
)


def _raw(lat, lon, ts, route_id=2, direction=1, speed=20.0):
    # BusMap swaps Lat/Lng: raw["Lat"] = lon, raw["Lng"] = lat
    return {
        "Lng": lat,
        "Lat": lon,
        "Speed": speed,
        "direction": direction,
        "RouteId": route_id,
        "lastUpdateTime": ts,
        "VehicleNumber": "29A00001",
    }


def test_out_of_bounds_does_not_poison_kinematic_cache():
    cache = {}
    targets = {2}
    r1 = sanitize_and_validate_telemetry(_raw(21.0285, 105.8542, "2026-11-05T08:00:00+07:00"), 1, targets, cache)
    assert r1["quality_status"] == "ACTIVE_VALID"

    # (0.0, 0.0) is OUT_OF_BOUNDS and must NOT overwrite cache[1]
    r_oob = sanitize_and_validate_telemetry(_raw(0.0, 0.0, "2026-11-05T08:01:15+07:00"), 1, targets, cache)
    assert r_oob["quality_status"] == "OUT_OF_BOUNDS"

    # Next valid ping ~300m away in 150s (~7.2 km/h) must stay ACTIVE_VALID, not GPS_DRIFT_JUMP
    r2 = sanitize_and_validate_telemetry(_raw(21.0312, 105.8542, "2026-11-05T08:02:30+07:00"), 1, targets, cache)
    assert r2["quality_status"] == "ACTIVE_VALID"


def test_small_dt_gps_jitter_below_250m_not_flagged_drift():
    cache = {}
    targets = {2}
    r1 = sanitize_and_validate_telemetry(_raw(21.0285, 105.8542, "2026-11-05T08:00:00+07:00"), 1, targets, cache)
    assert r1["quality_status"] == "ACTIVE_VALID"

    # ~111m in 2s -> 200 km/h apparent speed, but dist < 250m -> not GPS_DRIFT_JUMP
    r2 = sanitize_and_validate_telemetry(_raw(21.0295, 105.8542, "2026-11-05T08:00:02+07:00"), 1, targets, cache)
    assert r2["quality_status"] == "ACTIVE_VALID"


def test_genuine_large_jump_flagged_drift_and_preserves_cache():
    cache = {}
    targets = {2}
    r1 = sanitize_and_validate_telemetry(_raw(21.0285, 105.8542, "2026-11-05T08:00:00+07:00"), 1, targets, cache)
    assert r1["quality_status"] == "ACTIVE_VALID"

    # ~2.2 km in 10s -> ~800 km/h & dist >= 250m -> GPS_DRIFT_JUMP
    r_jump = sanitize_and_validate_telemetry(_raw(21.0485, 105.8542, "2026-11-05T08:00:10+07:00"), 1, targets, cache)
    assert r_jump["quality_status"] == "GPS_DRIFT_JUMP"

    # Following valid ping near original position remains ACTIVE_VALID
    r2 = sanitize_and_validate_telemetry(_raw(21.0295, 105.8542, "2026-11-05T08:01:15+07:00"), 1, targets, cache)
    assert r2["quality_status"] == "ACTIVE_VALID"
