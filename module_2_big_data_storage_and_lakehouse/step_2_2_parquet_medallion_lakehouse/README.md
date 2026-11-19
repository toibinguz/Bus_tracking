# Step 2.2: Medallion Lakehouse Parquet Cục bộ (`step_2_2_parquet_medallion_lakehouse`)

- **Vai trò:** Xuất dữ liệu từ `data/raw/` và `data/hanoi_bus_system.db` sang Apache Parquet nén Snappy theo mô hình Medallion (`bronze/`, `silver/`, `gold/`) và kiểm toán chất lượng phân vùng Silver.
- **Đầu vào:** `data/raw/*/incidents/*.jsonl` (Bronze) và SQLite (`route_projected_telemetry`, `fact_route_tomtom_incidents`).
- **Đầu ra:** `data/lakehouse/bronze/tomtom_incidents_raw/`, `data/lakehouse/silver/route_projected_telemetry/`, `data/lakehouse/silver/fact_route_tomtom_incidents/`.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `lakehouse_exporter.py` (`export_bronze_tomtom_incidents`, `export_to_parquet_lakehouse`) | Xuất Bronze & Silver Parquet tăng dần (atomic `.tmp` + `os.replace`, lọc `cross_track_m <= MAX_CORRIDOR_CROSS_TRACK_M`) | JSONL + SQLite -> Snappy Parquet |
| `silver_lakehouse_auditor.py` (`audit_silver`) | Quét kiểm toán độ tinh khiết corridor và phân vùng Silver Parquet | `data/lakehouse/silver/` -> Báo cáo audit |

## Tham số SSOT (`config/system_config.py`)

- `DEFAULT_LAKEHOUSE_ROOT = "data/lakehouse"`, `RAW_DATA_DIR = "data/raw"`
- `MAX_CORRIDOR_CROSS_TRACK_M = 35.0`

## Cách chạy

```bash
python -m module_2_big_data_storage_and_lakehouse.step_2_2_parquet_medallion_lakehouse.lakehouse_exporter
python -m module_2_big_data_storage_and_lakehouse.step_2_2_parquet_medallion_lakehouse.silver_lakehouse_auditor
```
