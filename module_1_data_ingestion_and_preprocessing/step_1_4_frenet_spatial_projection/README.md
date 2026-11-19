# Step 1.4: Chiếu Không gian 1D Frenet (`step_1_4_frenet_spatial_projection`)

- **Vai trò:** Chiếu tọa độ GPS `(lat, lon)` lên hình học tuyến 1D Frenet (`s_bus_m`, `cross_track_m`) bằng `RouteHMM` (`horizon=300.0s` cho Batch Layer tại `multi_route_projector.py` / `projection_boundary.py`), và cung cấp `ShapeProjectionModel` + `RouteHMM` cho Speed Layer (`step_3_4`).
- **Đầu vào:** `raw_bus_pings`, `canonical_shapes`, `canonical_routes` từ SQLite và TomTom Incidents JSONL.
- **Đầu ra:** `route_projected_telemetry`, `fact_route_tomtom_incidents` trong `data/hanoi_bus_system.db` và đối tượng `Match` cho tầng serving.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `route_matcher.py` (`ShapeProjectionModel`, `RouteHMM`, `Match`) | Hình học 1D Frenet (`ShapeProjectionModel`) và bộ lọc `RouteHMM` dùng chung cho Batch (`horizon=300.0s`) & Speed Layer | `(lat, lon, epoch)` -> `Match(s_m, cross_track_m, ...)` |
| `multi_route_projector.py` (`run_parallel_projection`, `project_points_to_shape`) | Chiếu song song đa nhân toàn bộ ping hợp lệ (`HANOI_BBOX` 4 biên) vào `route_projected_telemetry` | `raw_bus_pings` -> `route_projected_telemetry` |
| `projection_boundary.py` (`project_route_events`, `ProjectableEvent`, `ProjectedEvent`) | Ranh giới chiếu độc lập với tầng lưu trữ (dùng cho pipeline Spark/HDFS) | `ProjectableEvent` -> `ProjectedEvent` |
| `tomtom_incident_projector.py` (`project_linestring_to_route_grid`, `main`) | Chiếu chuỗi tọa độ sự cố TomTom lên lưới đoạn 100m của từng tuyến | Incidents JSONL -> `fact_route_tomtom_incidents` |

## Tham số SSOT (`config/system_config.py`)

- `MAX_CORRIDOR_CROSS_TRACK_M = 35.0`, `BATCH_HMM_HORIZON_SEC = 300.0`
- `GPS_DRIFT_MAX_SPEED_KMPH = 80.0`, `MAX_GPS_BACKWARD_JITTER_M = 20.0`

## Cách chạy & Kiểm thử

```bash
python -m module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector
python -m pytest tests/module_1/test_installed_route_matcher.py --basetemp=runtime/pytest_tmp -q
```
