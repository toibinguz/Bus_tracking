# MODULE 2: LƯU TRỮ VÀ XỬ LÝ DỮ LIỆU LỚN (BIG DATA STORAGE & MEDALLION LAKEHOUSE)
> **HDFS:** [Architecture/status](../docs/HDFS_README.md), [runbook](../docs/HDFS_RUNBOOK.md), [contracts](../docs/specs/HDFS_DATA_CONTRACTS.md). Complete pinned raw-history Bronze import is verified; Silver/ETA/offline release verification remains bounded. Live-serving cutover is not claimed.
>
> **Status note (2026-11-10):** Step 2.3 currently contains only its package marker; it is not a PyArrow/DuckDB query engine. Lakehouse row counts below are dated data snapshots.
> **Phần 2 - Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **HDFS — cách chạy và bằng chứng**: [Chỉ mục HDFS](../docs/HDFS_README.md)

---

## 1. CẤU TRÚC SUBCOMPONENTS CHUẨN TẮC

```
module_2_big_data_storage_and_lakehouse/
├── step_2_1_sqlite_operational_store/       # Quản trị Operational Database SQLite (data/hanoi_bus_system.db)
│   └── db_manager.py                         # Khởi tạo schema, B-Tree index và Analytical Views
├── step_2_2_parquet_medallion_lakehouse/     # Hồ dữ liệu phân vùng chuẩn Medallion (Bronze & Silver)
│   ├── lakehouse_exporter.py                 # Xuất Parquet Snappy phân vùng Hive (route_code=XX/dt=YYYY-MM-DD)
│   └── silver_lakehouse_auditor.py           # Kiểm toán độc lập độ tinh khiết các phân vùng Silver Parquet
└── step_2_3_columnar_query_engine/           # Động cơ truy vấn cột tốc độ cao (PyArrow / DuckDB)
    └── __init__.py
```

---

## 2. TRẠNG THÁI DỮ LIỆU HIỆN TẠI (PURE BRONZE & SILVER STATE)

1. **Operational SQLite (`data/hanoi_bus_system.db` - 6 bảng Bronze/Silver + 1 bảng Gold Baseline)**:
   - `canonical_route_master` (176 tuyến), `canonical_station_master` (13.301 trạm), `canonical_shape_master` (118.563 điểm tim đường).
   - `vehicle_unique_pings` (7.155.601 pings thô thuộc 48 tuyến chuẩn cụm HUST từ `2026-10-08`).
   - `route_projected_telemetry` (5.565.232 pings đã chiếu Frenet tinh khiết 100%, 13 cột, $d_\perp \le 35,0\text{m}$, 0 lỗi nhảy lùi — đồng bộ 1:1 với Silver Parquet).
   - `fact_route_tomtom_incidents` (836.761 bản ghi sự cố TomTom khớp 46/48 tuyến trên 28 ngày).
   - `agg_segment_travel_times` (169.830 ô ma trận thời gian di chuyển Baseline thống kê không rò rỉ dữ liệu từ tập Train `2026-10-08..31`, đạt `85,6% Tier 0` và `93,8% Tier 0+1`).
2. **Medallion Parquet Lakehouse (`data/lakehouse/`)**:
   - `bronze/tomtom_incidents_raw/dt=YYYY-MM-DD/` (28 phân vùng; số liệu dòng thay đổi theo thời điểm — xem docs/specs/16; 84,1 MB).
   - `silver/route_projected_telemetry/route_code=XX/dt=YYYY-MM-DD/` (các phân vùng Silver; số liệu thay đổi theo thời điểm — xem docs/specs/16).
   - `silver/fact_route_tomtom_incidents/route_code=XX/` (46 phân vùng, 836.761 dòng).
   - `gold/agg_segment_travel_times/part-00000.snappy.parquet` (169.830 dòng, 48 tuyến × 2 chiều × 17 khung giờ `05..21` × 3 loại ngày `Thứ 2..6 / Thứ 7 / Chủ Nhật` trên hành lang nội tuyến `[1 .. N-1]`).

---

## 3. HƯỚNG DẪN THỰC THI

```powershell
# 1. Xuất dữ liệu Bronze & Silver ra Parquet Lakehouse
.\.venv\Scripts\python.exe module_2_big_data_storage_and_lakehouse/step_2_2_parquet_medallion_lakehouse/lakehouse_exporter.py

# 2. Kiểm toán độc lập độ tinh khiết tầng Silver
.\.venv\Scripts\python.exe scripts/audit_silver_lakehouse_purity.py
```
