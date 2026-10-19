---
name: data-contract-governor
description: Enforces strict data contracts, schemas, and verification rules across the Ingestion, Big Data Lakehouse, and ETA modeling layers to prevent pipeline regressions and enable parallel decoupled development.
---

# Data Contract & Pipeline Governance

## 1. Core Philosophy: Decoupled Data Contracts

To eliminate the "quicksand trap" where downstream modeling waits indefinitely for upstream crawling perfection:
- **Contract-First**: Downstream modules depend only on the declared Data Contract (schema & types), NOT on how or when raw data was crawled.
- **Mock / Synthetic Fixtures**: If live data has gaps, downstream developers use synthetic or cached fixtures adhering to the contract to keep modeling progress moving forward.

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

### Contract 2: Silver Trajectory Contract (Cleaned Columnar Parquet)
```
Columns:
  - trajectory_id     : string (uuid or {vehicle_id}_{trip_date}_{trip_seq})
  - vehicle_id        : int64
  - plate             : string
  - route_id          : int32
  - timestamp_utc     : timestamp[us]
  - timestamp_vn      : timestamp[us]
  - lat               : float64
  - lon               : float64
  - speed_kmh         : float32
  - heading_deg       : float32
  - is_moving         : bool
  - delta_t_sec       : float32
  - delta_dist_m      : float32
  - current_stop_id   : int64
  - next_stop_id      : int64
  - dist_to_next_stop : float32
```

### Contract 3: Gold ML Training Matrix Contract
```
Target:
  - transit_time_to_next_stop_sec : float32
Features:
  - current_speed_kmh             : float32
  - historical_segment_speed_kmh  : float32
  - distance_to_target_m          : float32
  - hour_of_day                   : int8
  - is_peak_hour                  : bool
  - day_of_week                   : int8
  - route_congestion_index        : float32
```

---

## 3. Enforcement Checklist

Before any code is merged from `experiments/` to production modules:
1. `validate_schema(df, expected_contract)` must pass with 0 schema mismatch errors.
2. Coordinate bounds must be strictly within Hanoi BBOX: Lat $\in [20.80, 21.30]$, Lon $\in [105.65, 106.05]$.
3. Speed values must satisfy: $0 \le \text{Speed} \le 120\text{ km/h}$.

