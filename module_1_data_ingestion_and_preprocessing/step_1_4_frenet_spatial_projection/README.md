# Step 1.4: Chiếu Không gian 1D Frenet & HMM Route Matching

- **Vai trò:** Chiếu tọa độ GPS `(lat, lon)` lên hình học tuyến 1D Frenet (`s_bus_m`, `cross_track_m`) cho cả Batch View (đa tiến trình) và Speed View (`RouteHMM` nhân quả).
- **Đầu vào:** `raw_bus_pings`, `canonical_shapes`, `canonical_routes` từ SQLite và TomTom Incidents JSONL.
- **Đầu ra:** `route_projected_telemetry`, `fact_route_tomtom_incidents` trong `data/hanoi_bus_system.db` và đối tượng `Match` cho tầng serving.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `route_matcher.py` (`ShapeProjectionModel`, `RouteHMM`, `Match`) | Hình học tuyến 1D Frenet + bộ lọc HMM Viterbi nhân quả không I/O (dùng chung Batch & Speed View) | `(lat, lon, epoch)` -> `Match(s_m, cross_track_m, ...)` |
| `multi_route_projector.py` (`run_parallel_projection`, `project_points_to_shape`) | Chiếu song song đa nhân toàn bộ ping hợp lệ (`HANOI_BBOX` 4 biên) vào `route_projected_telemetry` | `raw_bus_pings` -> `route_projected_telemetry` |
| `projection_boundary.py` (`project_route_events`, `ProjectableEvent`, `ProjectedEvent`) | Ranh giới chiếu độc lập với tầng lưu trữ (dùng cho pipeline Spark/HDFS) | `ProjectableEvent` -> `ProjectedEvent` |
| `tomtom_incident_projector.py` (`project_linestring_to_route_grid`, `main`) | Chiếu chuỗi tọa độ sự cố TomTom lên lưới đoạn 100m của từng tuyến | Incidents JSONL -> `fact_route_tomtom_incidents` |

## Tham số SSOT (`config/system_config.py`)

- `MAX_CORRIDOR_CROSS_TRACK_M = 35.0`, `MAX_CORRIDOR_SPEED_KMH = 90.0`
- `MIN_DIRECTION_CHANGE_STEP_M = 5.0`

## Cách chạy & Kiểm thử

```bash
python -m module_1_data_ingestion_and_preprocessing.step_1_4_frenet_spatial_projection.multi_route_projector
python -m pytest tests/test_hmm_route_matcher.py --basetemp=runtime/pytest_tmp -q
```
