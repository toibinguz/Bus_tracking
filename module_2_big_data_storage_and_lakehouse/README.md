# MODULE 2: LƯU TRỮ VÀ XỬ LÝ DỮ LIỆU LỚN (BIG DATA STORAGE & MEDALLION LAKEHOUSE)
> **Phần 2 - Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Đặc tả cấu trúc**: [docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md](../docs/02_CANONICAL_DATA_DIRECTORY_SPECIFICATION.md)

---

## 1. CẤU TRÚC SUBCOMPONENTS CHUẨN TẮC

```
module_2_big_data_storage_and_lakehouse/
├── step_2_1_sqlite_operational_store/       # Quản trị Operational Database SQLite (data/hanoi_bus_system.db)
│   └── db_manager.py                         # Khởi tạo schema, B-Tree index và Analytical Views
├── step_2_2_parquet_medallion_lakehouse/     # Hồ dữ liệu phân vùng chuẩn Medallion (Bronze & Silver)
│   ├── lakehouse_exporter.py                 # Xuất Parquet Snappy phân vùng Hive (route_code=XX/dt=YYYY-MM-DD)
│   └── silver_lakehouse_auditor.py           # Kiểm toán độc lập độ tinh khiết 1.204 phân vùng Silver Parquet
└── step_2_3_columnar_query_engine/           # Động cơ truy vấn cột tốc độ cao (PyArrow / DuckDB)
    └── __init__.py
```

---

## 2. TRẠNG THÁI DỮ LIỆU HIỆN TẠI (PURE BRONZE & SILVER STATE)

1. **Operational SQLite (`data/hanoi_bus_system.db` - 6 bảng chuẩn)**:
   - `canonical_route_master` (176 tuyến), `canonical_station_master` (13.301 trạm), `canonical_shape_master` (118.563 điểm tim đường).
   - `vehicle_unique_pings` (7.333.298 pings thô).
   - `route_projected_telemetry` (5.621.758 pings đã chiếu Frenet trong hành lang $d_\perp \le 35,0\text{m}$ — đồng bộ 1:1 với Silver Parquet).
   - `fact_route_tomtom_incidents` (919.721 bản ghi sự cố TomTom khớp tuyến trên 28 ngày).
2. **Medallion Parquet Lakehouse (`data/lakehouse/`)**:
   - `bronze/tomtom_incidents_raw/dt=YYYY-MM-DD/` (28 phân vùng, 293.842 dòng, 84,1 MB).
   - `silver/route_projected_telemetry/route_code=XX/dt=YYYY-MM-DD/` (1.204 phân vùng, 5.621.758 dòng).
   - `silver/fact_route_tomtom_incidents/route_code=XX/` (52 phân vùng, 919.721 dòng).
   - `gold/`: Đang để trống hoàn toàn (Pre-Module 3 Clean Slate).

---

## 3. HƯỚNG DẪN THỰC THI

```powershell
# 1. Xuất dữ liệu Bronze & Silver ra Parquet Lakehouse
.\.venv\Scripts\python.exe module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/lakehouse_exporter.py

# 2. Kiểm toán độc lập độ tinh khiết tầng Silver
.\.venv\Scripts\python.exe scripts/audit_silver_lakehouse_purity.py
```
