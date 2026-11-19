# Module 1: Thu thập & Tiền xử lý Dữ liệu (`module_1_data_ingestion_and_preprocessing`)

- **Vai trò:** Thu thập dữ liệu GPS xe buýt + sự cố giao thông TomTom, làm sạch động học, phân đoạn chuyến và chiếu không gian 1D Frenet.
- **Đầu vào:** BusMap API, TomTom Incidents API, Hugging Face Dataset (`Toibinguz/hust-bus-data`), `data/ground_truth/busmap_canonical/`.
- **Đầu ra:** Batch JSONL lên Hugging Face (`Toibinguz/hust-bus-data`) / HDFS Bronze spool, dữ liệu đã làm sạch động học & chiếu 1D Frenet, cùng metadata GTFS chuẩn (`canonical_*`) trong SQLite.

## Sơ đồ luồng

```mermaid
flowchart TD
    BM["BusMap & TomTom Incidents API"] --> S11["step_1_1: Crawler & HF Sync\n(cloud_crawler_runner.py, socket_client.py, incident_client.py)"]
    S11 -->|"Raw JSONL (HF / HDFS Bronze)"| S13["step_1_3: Sanitizer & Trip Segmenter\n(HANOI_BBOX, Drift >100km/h, Idle <50m, Gap >900s)"]
    GTFS["data/ground_truth/busmap_canonical/"] --> S15["step_1_5: Canonical GTFS Migration\n(canonical_routes, canonical_shapes, canonical_stations)"]
    S13 -->|"Cleaned Pings & Trips"| S14["step_1_4: Chiếu 1D Frenet thuần\n(multi_route_projector.py, tomtom_incident_projector.py)"]
    S15 -->|"Shapes & Stations"| S14
    S14 -->|"Silver Telemetry (cross_track <= 35m) & Incidents"| M2["Module 2: HDFS & Parquet Lakehouse"]
```

## Các Sub-module

| Sub-module | Nhiệm vụ | Tài liệu |
| --- | --- | --- |
| `step_1_1_busmap_crawler_and_relay` | Cloud/Local crawler, TomTom Incidents, Hugging Face sync, catalog refresh | [README.md](step_1_1_busmap_crawler_and_relay/README.md) |
| `step_1_3_telemetry_kinematic_sanitizer` | Lọc ngoại lệ `HANOI_BBOX`, phân loại `IDLE_DEPOT`/`GPS_DRIFT_JUMP`, phân chuyến, nạp SQLite | [README.md](step_1_3_telemetry_kinematic_sanitizer/README.md) |
| `step_1_4_frenet_spatial_projection` | Chiếu tọa độ 2D sang 1D Frenet (`s_bus_m`, `cross_track_m`) cho Batch Layer | [README.md](step_1_4_frenet_spatial_projection/README.md) |
| `step_1_5_busmap_canonical_migration` | Nạp dữ liệu chuẩn tuyến/hình học/trạm từ `busmap_canonical/` vào SQLite | [README.md](step_1_5_busmap_canonical_migration/README.md) |
