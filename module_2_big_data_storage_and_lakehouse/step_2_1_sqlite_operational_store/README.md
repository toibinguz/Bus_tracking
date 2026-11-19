# Step 2.1: Kho lưu trữ Vận hành SQLite (`step_2_1_sqlite_operational_store`)

- **Vai trò:** Quản lý schema chuẩn (`canonical_routes`, `canonical_stations`, `canonical_shapes`, `raw_bus_pings`, `route_projected_telemetry`, `fact_route_tomtom_incidents`, `bus_trip_segments`) và phiên làm việc SQLite (`data/hanoi_bus_system.db`).
- **Đầu vào:** `get_database_path()` từ `config/system_config.py`.
- **Đầu ra:** Kết nối SQLite đã bật WAL/index cho Module 1 (ingest/projection) và Module 3 (serving metadata/baseline).

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `db_manager.py` (`OperationalDatabaseManager`) | Khởi tạo bảng, index và cung cấp context/connection tới SQLite | `db_path` -> SQLite schema & connection |

## Tham số SSOT (`config/system_config.py`)

- `DEFAULT_DB_PATH = "data/hanoi_bus_system.db"`, `LEGACY_AUDIT_DB_PATH = "data/bus_tracking.db"`
- `get_database_path()`: ưu tiên `DEFAULT_DB_PATH`, fallback sang legacy chỉ khi file tồn tại.
