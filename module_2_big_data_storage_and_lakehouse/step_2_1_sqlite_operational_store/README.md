# Step 2.1: Nền nhẹ SQLite cho Web App (`step_2_1_sqlite_operational_store`)

- **Vai trò:**
  - **Giai đoạn thử nghiệm ban đầu:** SQLite (`data/hanoi_bus_system.db`) từng đóng vai trò kho dữ liệu duy nhất (`raw_bus_pings`, `route_projected_telemetry`, `fact_route_tomtom_incidents`).
  - **Kiến trúc sản phẩm hoàn thiện:** Nhường toàn bộ vai trò lưu trữ `raw` & `silver` cho **HDFS / Lakehouse**, chỉ còn làm **nền nhẹ cho Web App** (`canonical_routes`, `canonical_stations`, `canonical_shapes`) và **nơi hứng kết quả tổng hợp từ HDFS Gold** (bảng baseline ETA phục vụ tra cứu nhanh).
- **Đầu vào:** `get_database_path()` từ `config/system_config.py`, dữ liệu GTFS chuẩn (`step_1_5`) và kết quả tổng hợp từ HDFS Gold.
- **Đầu ra:** Kết nối SQLite phục vụ Web Demo (`step_3_4`, `step_3_5`) với độ trễ thấp.

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `db_manager.py` (`OperationalDatabaseManager`) | Khởi tạo schema và cung cấp kết nối tới SQLite | `db_path` -> SQLite schema & connection |

## Tham số SSOT (`config/system_config.py`)

- `DEFAULT_DB_PATH = "data/hanoi_bus_system.db"`, `LEGACY_AUDIT_DB_PATH = "data/bus_tracking.db"`
- `get_database_path()`: ưu tiên `DEFAULT_DB_PATH`, fallback sang legacy chỉ khi file tồn tại.
