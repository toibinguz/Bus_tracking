# Step 2.1: Nền nhẹ SQLite cho Web App (`step_2_1_sqlite_operational_store`)

- **Vai trò:** Lưu trữ metadata tĩnh GTFS chuẩn (`canonical_routes`, `canonical_stations`, `canonical_shapes`) làm **nền nhẹ cho Web App** và làm **nơi hứng kết quả tổng hợp từ HDFS Gold** (bảng baseline ETA phục vụ tra cứu độ trễ thấp).
- **Đầu vào:** `get_database_path()` từ `config/system_config.py`, dữ liệu GTFS chuẩn (`step_1_5`) và kết quả tổng hợp từ HDFS Gold.
- **Đầu ra:** Kết nối SQLite phục vụ Web Demo (`step_3_4`, `step_3_5`).

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `db_manager.py` (`OperationalDatabaseManager`) | Khởi tạo schema và cung cấp kết nối tới SQLite | `db_path` -> SQLite schema & connection |

## Tham số SSOT (`config/system_config.py`)

- `DEFAULT_DB_PATH = "data/hanoi_bus_system.db"`
- `get_database_path()`: trả về đường dẫn DB chuẩn đang hoạt động.
