# Step 3.1: Mô hình Baseline Lịch sử (`step_3_1_historical_baseline_model`)

- **Vai trò:** Trích xuất thời điểm xe qua từng trạm từ Silver Parquet, tính ma trận phân vị thời gian di chuyển (`p10`, `p50`, `p90`, `mean`, `var`) theo `(route_id, direction, segment_idx, day_type, hour_slot)` và đánh giá trên tập test chia theo ngày.
- **Đầu vào:** `data/lakehouse/silver/route_projected_telemetry/`, `data/splits/train_test_split_v1.json`, `data/hanoi_bus_system.db`.
- **Đầu ra:** Bảng `agg_segment_travel_times` (`data/lakehouse/gold/agg_segment_travel_times/part-00000.snappy.parquet`) và bảng `baseline_segment_travel_times` trong SQLite.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `baseline_matrix_builder.py` (`build_and_evaluate_baseline_matrix`, `extract_bracketed_station_arrivals`, `get_active_corridor_stations`) | Nội suy thời điểm qua trạm (bracketed crossing), tổng hợp phân vị baseline và kiểm chứng độ chính xác baseline | Silver Parquet + Split -> Gold Parquet + SQLite |

## Tham số SSOT (`config/system_config.py`)

- `DEFAULT_SPLIT_MANIFEST = "data/splits/train_test_split_v1.json"`
- `MIN_SAMPLES_FOR_BASELINE = 5`, `MAX_SEGMENT_TRAVEL_TIME_SEC = 1800.0`

## Cách chạy

```bash
python -m module_3_bus_eta_prediction.step_3_1_historical_baseline_model.baseline_matrix_builder
```
