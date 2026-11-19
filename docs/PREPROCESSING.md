# Tài liệu Tiền xử lý & Chiếu Không gian (Preprocessing)

- **Trạng thái:** Current
- **Phạm vi:** Làm sạch động học ping GPS, phân đoạn chuyến đi, nạp dữ liệu chuẩn GTFS và chiếu tọa độ 2D sang hệ tọa độ đường 1D Frenet.
- **Nguồn sự thật (Code paths):** `module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/`, `step_1_4_frenet_spatial_projection/`, `step_1_5_busmap_canonical_migration/`, `config/system_config.py`.

## 1. Sơ đồ Luồng Dữ liệu (Data Flow)

```mermaid
flowchart TD
    PING["Ping GPS thô JSONL\n(vid, lat, lon, speed, dir, device_update_time)"] --> SAN["step_1_3: telemetry_sanitizer.py"]
    GTFS["GTFS Canonical (busmap_canonical/)"] --> S15["step_1_5: ingest_busmap_canonical.py"] --> SQL["SQLite (canonical_shapes, canonical_stations)"]
    SAN --> SEG["step_1_3: trip_segmenter.py"]
    SQL --> PROJ
    SEG --> PROJ["step_1_4: RouteHMM + ShapeProjectionModel"]
    PROJ --> SIL["Silver Telemetry (route_projected_telemetry)"]
    INC["TomTom Incidents JSONL"] --> INCPROJ["tomtom_incident_projector.py"] --> SILINC["Silver Incidents (fact_route_tomtom_incidents)"]
```

## 2. Sơ đồ Luồng Logic (Logic Flow)

```mermaid
flowchart TD
    PING["Ping GPS thô"] --> BBOX{"Trong HANOI_BBOX 4 biên?\n(19.50..22.50, 104.50..107.50)"}
    BBOX -->|"Không"| OOB["Gắn OUT_OF_BOUNDS\n(KHÔNG ghi kinematic_cache)"]
    BBOX -->|"Có"| KIN{"dist >= 250.0m &\nv_calc > 80.0 km/h?"}
    KIN -->|"Có"| DRIFT["Gắn GPS_DRIFT_JUMP\n(KHÔNG cập nhật kinematic_cache)"]
    KIN -->|"Không"| DEPOT{"(dir==0 hoặc route<=0)\n& speed == 0?"}
    DEPOT -->|"Có"| IDLE["Gắn IDLE_DEPOT"]
    DEPOT -->|"Không"| VALID["Gắn ACTIVE_VALID / STALE_PING"]

    VALID --> SEG{"Ngắt chuyến?\ndt > 300s (detour 1800s) |\nlùi > 200m | terminal reset"}
    SEG -->|"Có"| NEW["Tách Trip mới + trim_terminal_stationary_ends()"]
    SEG -->|"Không"| SAME["Nối Trip hiện tại"]
    NEW & SAME --> HMM["Chiếu 1D Frenet (RouteHMM, horizon=300.0s)"]
    HMM --> CORR{"cross_track_m <= 35.0m?"}
    CORR -->|"Sai"| DROP["Loại khỏi Silver Corridor"]
    CORR -->|"Đúng"| KEEP["Giữ lại trong Silver Telemetry"]
```

## 3. Quy tắc làm sạch & Chiếu không gian (`config/system_config.py`)

| Tham số / Quy tắc | Giá trị / Logic hiện hành |
| --- | --- |
| `HANOI_BBOX` (4 biên) | `min_lat=19.50`, `max_lat=22.50`, `min_lon=104.50`, `max_lon=107.50` (bao phủ cả tuyến buýt liên tỉnh quanh Hà Nội) |
| `GPS_DRIFT_MAX_SPEED_KMPH` & `GPS_DRIFT_MIN_DIST_M` | `80.0` km/h & `250.0` m — chỉ đánh dấu `GPS_DRIFT_JUMP` khi đồng thời vượt cả 2 ngưỡng (chống jitter `dt` nhỏ), không cập nhật cache khi `OUT_OF_BOUNDS` hoặc drift |
| `TERMINAL_STATIONARY_TOL_M` | `15.0` m — ngưỡng dịch chuyển tối thiểu phân biệt đứng yên / cắt đuôi tại bến |
| `MAX_CONTINUOUS_GAP_SEC` / `MAX_BRIDGEABLE_DETOUR_GAP_SEC` | `300.0` s / `1800.0` s — nối chuyến qua detour nếu `ds > 100m` và vận tốc `2..60 km/h` |
| `MAX_BACKWARD_RESET_M` | `200.0` m — ngưỡng lùi `s` xác nhận quay đầu / ngắt chuyến (`MAX_GPS_BACKWARD_JITTER_M = 20.0` m) |
| `MAX_CORRIDOR_CROSS_TRACK_M` | `35.0` m — ngưỡng tối đa cho phép khi xuất telemetry lên Silver Lakehouse |
| `RouteHMM` (`BATCH_HMM_HORIZON_SEC = 300.0`) | Dùng chung `ShapeProjectionModel` + `RouteHMM` giữa Batch (`multi_route_projector.py`, `horizon=300.0`) và Speed Layer (`step_3_4`) |

## 4. Kiểm thử

```bash
python -m pytest tests/module_1/test_installed_route_matcher.py tests/module_1/test_projection_boundary.py --basetemp=runtime/pytest_tmp -q
```
