---
name: big-data-lakehouse
description: Architecture guide and runbook for processing massive bus telemetry streams into a high-performance columnar Lakehouse (Bronze, Silver, Gold) using Parquet, DuckDB, and PySpark with spatial-temporal partitioning.
---

# Big Data Lakehouse Architecture Guide for Hanoi Bus Telemetry

## 1. Architectural Overview (Medallion Pattern)

To satisfy academic Big Data requirements and support millisecond-latency analytical queries, raw telemetry is processed through a 3-tier Lakehouse pattern grounded on official TimBus Ground Truth (TRAMOC / Sở GTVT):

```
[Cloud / Hugging Face JSONL Crawler Output]
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ 🥉 BRONZE TIER: Immutable Raw Ingestion Lake           │
│ Path: data/lakehouse/bronze/year=YYYY/month=MM/day=DD/  │
│ Format: Compressed Raw JSONL / Parquet (Lossless)      │
│ Schema: Raw socket dump, crawled_at, device_update_time│
└────────────────────────────────────────────────────────┘
            │  (Deduplication, 1D Frenet Projection s & d_perp, Kinematic Validation)
            ▼
┌────────────────────────────────────────────────────────┐
│ 🥈 SILVER TIER: Cleaned 1D Projected Trajectory Lake   │
│ Path: data/lakehouse/silver/route_telemetry/           │
│ Format: Snappy Parquet (Columnar, Partitioned by Route)│
│ Schema: ping_id, route_code, vehicle_id, plate, epoch, │
│         lat, lon, s_bus_m, cross_track_m, derived_speed│
└────────────────────────────────────────────────────────┘
            │  (Linear Station Crossing Interpolation, Discretized Time Windows)
            ▼
┌────────────────────────────────────────────────────────┐
│ 🥇 GOLD TIER: Serving Matrix & Bottleneck Analytics    │
│ Path: data/lakehouse/gold/segment_travel_times/        │
│ Table : agg_segment_travel_times (SQLite & Parquet)    │
│ Stats : N_samples, median_transit_sec (P50), p10, p90, │
│         mean_transit_sec, commercial_speed_kmh         │
└────────────────────────────────────────────────────────┘
```

---

## 2. Partitioning Strategy

- **Temporal Partitioning**: Partition by `day_type` and date to enable rapid time slicing without scanning full tables.
- **Topological Partitioning**: Partition by `route_code` and `direction` (`go` / `return`) to allow route-specific matrix computation and ETA lookups.
- **File Sizing Target**: Target optimal Parquet row-group sizes with Snappy compression for 85%+ storage footprint reduction.

---

## 3. Technology Stack & Execution Protocol

- **Canonical Runtime**: Python 3.14 (PEP 514 registered) with `DuckDB` and `PySpark` for columnar query acceleration.
- **Operational Serving Engine**: SQLite (`data/hanoi_bus_system.db`) for instant $O(1)$ ETA lookups.
- **Columnar Lakehouse Engine**: Apache Parquet / DuckDB for large-scale analytical scans.

---

## 4. Definition of Done (DoD) for Lakehouse Pipeline

1. Ingestion of 24h of telemetry completes in $< 60$ seconds.
2. DuckDB / SQLite queries for station segment travel times return in $< 10$ ms.
3. Every projection is audited against official TimBus shape points ($d_\perp$ tracked, sanity filtered).
