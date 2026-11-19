# Step 1.3: Làm sạch Động học, Phân đoạn Chuyến & Nạp SQLite

- **Vai trò:** Kiểm tra tính hợp lệ không gian-thời gian của ping GPS, phân loại trạng thái xe, tách chuỗi ping thành các chuyến đi liên tục và nạp hàng loạt vào SQLite.
- **Đầu vào:** Batch JSONL từ `data/raw/YYYY-MM-DD/bus/*.jsonl`.
- **Đầu ra:** Bản ghi đã gắn `quality_status` (`ACTIVE_VALID`, `IDLE_DEPOT`, `STALE_PING`, `GPS_DRIFT_JUMP`, `OUT_OF_BOUNDS`) và bảng `raw_bus_pings` trong `data/hanoi_bus_system.db`.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `telemetry_sanitizer.py` (`sanitize_and_validate_telemetry`) | Lọc `HANOI_BBOX`, phát hiện drift jump (>100 km/h, không cập nhật cache khi drift), phân biệt `IDLE_DEPOT` bằng `TERMINAL_STATIONARY_TOL_M` | Raw dict + `kinematic_cache` -> Sanitized record |
| `kinematic_engine.py` (`haversine_distance`) | Tính khoảng cách trắc địa (mét) giữa 2 tọa độ WGS84 | `(lat1, lon1, lat2, lon2)` -> `meters` |
| `trip_segmenter.py` (`segment_trajectory_into_trips`, `trim_terminal_stationary_ends`) | Tách quỹ đạo thành các chuyến dựa trên gap thời gian (`900s`), đổi hướng (`direction`), và reset đầu cuối (`is_terminal_reset` kèm `s < prev_s - MAX_BACKWARD_JITTER_M`) | Chuỗi ping -> Danh sách chuyến |
| `bulk_ping_ingester.py` (`main`) | Đọc toàn bộ JSONL `data/raw/`, kiểm tra đầy đủ 4 biên `HANOI_BBOX`, nạp `raw_bus_pings` vào SQLite | `data/raw/*/bus/*.jsonl` -> SQLite `raw_bus_pings` |

## Tham số SSOT (`config/system_config.py`)

- `HANOI_BBOX`: `min_lat=19.50`, `max_lat=22.50`, `min_lon=104.50`, `max_lon=107.50`
- `MAX_BUS_SPEED_KMPH = 100.0`, `TERMINAL_STATIONARY_TOL_M = 50.0`
- `TRIP_MAX_TIME_GAP_SEC = 900`, `MAX_BACKWARD_JITTER_M = 120.0`

## Cách chạy

```bash
python -m module_1_data_ingestion_and_preprocessing.step_1_3_telemetry_kinematic_sanitizer.bulk_ping_ingester
```
