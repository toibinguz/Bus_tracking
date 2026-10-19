---
name: big-data-lakehouse
description: Architecture guide and runbook for processing massive bus telemetry streams into a high-performance columnar Lakehouse (Bronze, Silver, Gold) using Parquet, DuckDB, and PySpark with spatial-temporal partitioning.
---

# Big Data Lakehouse Architecture Guide for Hanoi Bus Telemetry

## 1. Architectural Overview (Medallion Pattern)

To satisfy academic Big Data requirements and support millisecond-latency analytical queries, raw telemetry is processed through a 3-tier Lakehouse pattern:

```
[Cloud / Hugging Face JSONL]
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ 🥉 BRONZE TIER: Immutable Raw Ingestion Lake           │
│ Path: data/lakehouse/bronze/year=YYYY/month=MM/day=DD/  │
│ Format: Compressed Raw JSONL / Parquet (Lossless)      │
│ Schema: Raw socket dump, crawled_at, device_update_time│
└────────────────────────────────────────────────────────┘
            │  (Deduplication, Kinematic Validation, Null Imputation)
            ▼
┌────────────────────────────────────────────────────────┐
│ 🥈 SILVER TIER: Cleaned & Segmented Trajectory Lake    │
│ Path: data/lakehouse/silver/date=YYYY-MM-DD/route_id=X/ │
│ Format: Snappy Parquet (Columnar, Dictionary Encoded)  │
│ Schema: trajectory_id, vehicle_id, route_id, epoch_sec,│
│         lat, lon, speed_kmh, heading, is_moving,       │
│         current_stop_id, next_stop_id, dist_to_next_m  │
└────────────────────────────────────────────────────────┘
            │  (Corridor Aggregation, Spatial Join with OSM, Feature Extraction)
            ▼
┌────────────────────────────────────────────────────────┐
│ 🥇 GOLD TIER: Analytical Mart & ML Feature Store       │
│ Path: data/lakehouse/gold/                             │
│ Tables:                                                │
│  - corridor_speed_profiles (hourly 15-min speed stats) │
│  - stop_to_stop_travel_times (historical transit times)│
│  - eta_training_features (ready-to-train ML matrices)  │
└────────────────────────────────────────────────────────┘
```

---

## 2. Partitioning Strategy

- **Temporal Partitioning**: Partition by `date` (e.g. `date=2026-10-18`) to ensure queries scanning specific days prune 97%+ of unnecessary files.
- **Topological Partitioning**: Partition by `route_id` (e.g. `route_id=2`) to allow route-specific ETA training without reading the entire 504-bus network.
- **File Sizing Target**: Target 128 MB – 256 MB per Parquet chunk with row-group size of 100,000 rows.

---

## 3. Technology Stack & Execution Protocol

- **Local Fast Analytics**: `DuckDB` (embedded C++ engine capable of scanning 10M rows/sec on local laptop without JVM overhead).
- **Distributed Big Data Engine**: `PySpark` for batch transformations and distributed feature engineering across clusters.
- **Columnar Format**: Apache Parquet with Snappy compression for 85%+ storage footprint reduction compared to JSONL.

---

## 4. Definition of Done (DoD) for Lakehouse Pipeline

1. Ingestion of 24h of telemetry (430k+ records) completes in $< 60$ seconds on local CPU.
2. DuckDB / PySpark queries for average corridor speeds return in $< 200$ ms.
3. Zero data loss during Silver transition: every valid GPS point is accounted for with an audit log.

