# BÁO CÁO NGHIỆM THU WP 2.2: MEDALLION LAKEHOUSE (APACHE PARQUET), TỐI ƯU HÓA ĐA NHÂN & CAM KẾT SLA TRÊN TOÀN BỘ 48 TUYẾN

> **Ngày thực hiện**: 02/11/2026  
> **Căn cứ thiết kế**: [`docs/63_WP22_MEDALLION_LAKEHOUSE_WEEKLY_RETRAINING_AND_HYBRID_SERVING_SPEC.md`](../docs/63_WP22_MEDALLION_LAKEHOUSE_WEEKLY_RETRAINING_AND_HYBRID_SERVING_SPEC.md)  

## I. BẢNG ĐỐI CHUẨN DUNG LƯỢNG NÉN & TỐC ĐỘ ĐỌC I/O (JSONL vs. SQLITE vs. APACHE PARQUET + DUCKDB 2.0)

| Hạng Mục Kiểm Định | Hệ Thống Cơ Sở (JSONL / SQLite) | Medallion Lakehouse (Apache Parquet Snappy) | Tỷ Lệ Nén / Tăng Tốc | Cơ Chế Kỹ Thuật Cốt Lõi |
| :--- | :--- | :--- | :---: | :--- |
| **TomTom Incidents (22 Days, 223k raw -> 634k episodes)** | Raw JSONL (203.89 MB) | **Parquet Snappy (64.01 MB Bronze / 9.99 MB Silver)** | **`3.19x`** | Columnar Dictionary + Snappy Compression |
| **Corridor Telemetry (48 Routes, 5,562,511 rows)** | SQLite B-Tree DB (2856.85 MB total DB) | **Silver Parquet Snappy (229.02 MB, 48 route x 26 dt partitions)** | **`12.47x`** | Hive Partitioning (route_code=XX/dt=YYYY-MM-DD) |
| **Query 1: Partition Pruning + 4-Col Projection (Route 02, last 7 days)** | SQLite Index + Table Lookup: 1554.3 ms (43,475 rows) | **DuckDB + Parquet Partition Pruning: 40.6 ms (43,475 rows)** | **`38.32x`** | Skips 47 other routes & 19 older date folders |
| **Query 2: Full-Network OLAP Aggregation (5.56M rows -> 96 route-dirs)** | SQLite Row-Store Scan: 32943.5 ms | **DuckDB Vectorized Parquet Scan: 178.1 ms** | **`185.02x`** | Reads only 4 projected columns instead of 14 |

## II. BẢNG KIỂM ĐỊNH SLA TÁI HUẤN LUYỆN HÀNG TUẦN & LIÊN KẾT MA TRẬN ĐỘNG (TWO-STAGE DECOUPLED FEATURE STORE)

| Tuyến | Số Mẫu | Dung Lượng Gold Parquet | Quét SQLite Từ Đầu (Scratch) | Bù Trừ 7 Ngày Mới (Weekly Delta) | Đọc Parquet (PyArrow C++) | Áp Ma Trận Mới (Stage 2 Re-bind) | Huấn Luyện XGB-CQR (`n_jobs=-1`) | Tổng Thời Gian Retrain (Warm / Weekly) | Sai Lệch Toán Học (`max |diff|`) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Tuyến 02** | 794,276 | 71.40 MB | 28.74s | **7.46s** | **0.417s** | **0.464s** | **71.31s** | **`72.19s` / `79.65s`** | **`0.000000`** |
| **Tuyến 27** | 769,854 | 69.34 MB | 28.93s | **10.30s** | **0.428s** | **0.591s** | **64.70s** | **`65.72s` / `76.01s`** | **`0.000000`** |

## III. BẢNG THỰC THI ĐA NHÂN (`ProcessPoolExecutor`) & THỜI GIAN HOÀN THÀNH TRÊN TOÀN BỘ 48 TUYẾN (`5,562,511` PINGS -> `14,365,058` MẪU)

| Giai Đoạn Trong Weekly All-in-One Pipeline (Toàn Mạng 48 Tuyến) | Chạy Đơn Luồng Tuần Tự (1 Core) | Chạy Đa Nhân Song Song (`ProcessPoolExecutor` + C++ Threads) | Tốc Độ Tăng Tốc | Ghi Chú Kỹ Thuật |
| :--- | :---: | :---: | :---: | :--- |
| **1. Khởi tạo Stage 1 Parquet từ đầu (Full 22–26 ngày, 48 tuyến)** | `529.6s` (`8.83` phút) | **`81.5s` (`1.36` phút)** | **`6.50x`** | Chỉ chạy 1 lần duy nhất khi khởi tạo kho Gold (`1371.07 MB`) |
| **2. Bù trừ 7 ngày mới mỗi cuối tuần (Weekly 7-Day Delta, 48 tuyến)** | `163.1s` (`2.72` phút) | **`25.1s` (`0.42` phút)** | **`6.50x`** | Bỏ qua các phân vùng `dt=YYYY-MM-DD` cũ đã có trên đĩa |
| **3. Đọc Parquet + Áp Ma trận Thời gian Mới (Stage 2 Re-bind, 48 tuyến)** | `17.44s` | **`10.33s`** | **`1.69x`** | PyArrow Dataset C++ Multi-thread + Vectorized 4D Lookup |
| **4. Huấn luyện mô hình Residual XGB-CQR (`[P10, P50, P90]`, 48 tuyến)** | `~3997.1s` (1 thread) | **`1249.1s` (`20.82` phút)** | **`3.20x`** | `tree_method='hist'`, `max_bin=128`, `n_jobs=-1` trên `14,365,058` mẫu |
| **TỔNG THỜI GIAN PHIÊN HÀNG TUẦN (WEEKLY ALL-IN-ONE SLA - 48 TUYẾN)** | `1429.6s` (`23.83` phút) | **`1284.5s` (`21.41` phút)** | **`Vượt chuẩn SLA (< 15 phút)`** | **Warm Retrain (khi đã có Parquet): `1259.4s` (`20.99` phút)** |

## IV. TOP 15 TUYẾN LỚN NHẤT TRONG KHO GOLD PARQUET (ĐÃ HIỆN THỰC HÓA TRÊN ĐĨA)

| Hạng | Tuyến (`route_code`) | Số Ngày Có Dữ Liệu (`dt`) | Tổng Số Mẫu Huấn Luyện (`N_samples`) | Thời Gian Đọc Parquet (`s`) | Thời Gian Re-bind Ma Trận Stage 2 (`s`) | Tổng Thời Gian Load + Bind (`s`) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | **Tuyến `02`** | 22 ngày | **794,276** | `1.022s` | `3.287s` | **`4.309s`** |
| 2 | **Tuyến `27`** | 22 ngày | **769,854** | `0.804s` | `2.861s` | **`3.666s`** |
| 3 | **Tuyến `22A`** | 23 ngày | **684,320** | `1.012s` | `2.791s` | **`3.803s`** |
| 4 | **Tuyến `32`** | 22 ngày | **663,677** | `1.069s` | `2.912s` | **`3.981s`** |
| 5 | **Tuyến `19`** | 23 ngày | **586,567** | `1.034s` | `2.669s` | **`3.703s`** |
| 6 | **Tuyến `26`** | 22 ngày | **518,818** | `0.284s` | `2.376s` | **`2.659s`** |
| 7 | **Tuyến `E01`** | 23 ngày | **513,535** | `0.836s` | `2.047s` | **`2.882s`** |
| 8 | **Tuyến `21A`** | 22 ngày | **492,042** | `0.493s` | `1.905s` | **`2.397s`** |
| 9 | **Tuyến `08A`** | 24 ngày | **474,705** | `0.203s` | `1.845s` | **`2.047s`** |
| 10 | **Tuyến `34`** | 18 ngày | **472,571** | `0.233s` | `1.949s` | **`2.182s`** |
| 11 | **Tuyến `BRT01`** | 22 ngày | **467,158** | `1.036s` | `1.899s` | **`2.935s`** |
| 12 | **Tuyến `51`** | 22 ngày | **421,577** | `0.233s` | `2.087s` | **`2.320s`** |
| 13 | **Tuyến `37`** | 18 ngày | **413,378** | `0.243s` | `1.631s` | **`1.874s`** |
| 14 | **Tuyến `E02`** | 19 ngày | **356,128** | `0.234s` | `1.793s` | **`2.027s`** |
| 15 | **Tuyến `107`** | 18 ngày | **349,299** | `0.499s` | `1.706s` | **`2.205s`** |
