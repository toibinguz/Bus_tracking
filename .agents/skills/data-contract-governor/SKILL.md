---
name: data-contract-governor
description: Enforces strict data contracts, schemas, and verification rules across the Ingestion, Big Data Lakehouse, and ETA modeling layers to prevent pipeline regressions and enable parallel decoupled development.
---

# Data Contract & Pipeline Governance

## 1. Core Philosophy: Empirical Ground Truth & Single Source of Truth

- **Single Master Ground Truth**: TimBus (TRAMOC / Sở GTVT Hà Nội) is the ONLY authoritative source for route codes, station coordinates WGS84, and centerline geometry.
- **Empirical Reality Over Synthetic Assumptions**: Never use synthetic or mocked fixtures that fabricate transit patterns. When data is sparse ($N = 0$), enforce "Selective Ignorance" (tag as unobserved / route fallback) rather than inventing artificial data.
- **Derived Kinematics**: Speed is always derived ($\bar{v} = \Delta s / \Delta t$). Raw GPS speed is never trusted.

---

## 2. Standard Data Contracts

### Contract 1: Ingestion Output (Bronze Contract)
Each JSONL record emitted by crawler or lake sync must contain:
```json
{
  "vehicle_id": 231968,
  "plate": "29B20547",
  "route_id": 2,
  "lat": 20.950193,
  "lon": 105.747849,
  "speed": 18.5,
  "direction": 1,
  "heading_deg": 233.8,
  "device_update_time": "2026-10-18T14:48:28+07:00",
  "crawled_at": "2026-10-18T14:48:58.123456+07:00"
}
```

### Contract 2: Silver 1D Trajectory Contract (`route_projected_telemetry`)
```
Columns:
  - ping_id            : int64 (Primary Key)
  - route_code         : string (e.g. '01', '02', 'BRT01')
  - route_id           : int32
  - vehicle_id         : int64
  - plate              : string
  - device_update_time : string (ISO 8601)
  - device_epoch       : int64 (Unix timestamp)
  - direction          : string ('go' | 'return')
  - lat                : float64
  - lon                : float64
  - s_bus_m            : float64 (1D Frenet station distance along centerline)
  - cross_track_m      : float64 (Orthogonal distance d_perp to centerline)
  - derived_speed_kmh  : float64 (Delta s / Delta t * 3.6)
  - is_dwell           : int (0 | 1)
```

### Contract 3: Gold Segment Travel Time Matrix Contract (`agg_segment_travel_times`)
```
Primary Key: (route_code, direction, from_station_order, to_station_order, time_window, day_type)
Columns:
  - segment_distance_m   : float64
  - sample_count         : int32
  - median_transit_sec   : float64 (P50 anchor)
  - mean_transit_sec     : float64
  - std_transit_sec      : float64
  - p10_transit_sec      : float64 (free-flow)
  - p90_transit_sec      : float64 (congested)
  - commercial_speed_kmh : float64
  - is_interpolated      : int (0: observed, 1: all-day fallback, 2: route fallback)
```

---

## 3. Enforcement Checklist

Before any code is merged from `experiments/` to production modules:
1. `validate_schema(df, expected_contract)` must pass with 0 schema mismatch errors.
2. Coordinate bounds must be strictly within Hanoi BBOX: Lat $\in [20.80, 21.30]$, Lon $\in [105.65, 106.05]$.
3. Speed values must satisfy physical bounds: $0.0 \le \bar{v} \le 80.0\text{ km/h}$.
4. Cross-track error $d_\perp$ sanity threshold must be tracked ($d_\perp > 50\text{m}$ flagged for geometry review).
