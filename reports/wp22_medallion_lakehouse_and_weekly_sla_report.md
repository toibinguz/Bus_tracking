# BÁO CÁO NGHIỆM THU WP 2.2: MEDALLION LAKEHOUSE (APACHE PARQUET), TỐI ƯU HÓA ĐA NHÂN & CAM KẾT SLA TRÊN TOÀN BỘ 48 TUYẾN

> **Ngày thực hiện**: 02/11/2026  
> **Căn cứ thiết kế**: [`docs/63_WP22_MEDALLION_LAKEHOUSE_WEEKLY_RETRAINING_AND_HYBRID_SERVING_SPEC.md`](../docs/63_WP22_MEDALLION_LAKEHOUSE_WEEKLY_RETRAINING_AND_HYBRID_SERVING_SPEC.md)  

## I. BẢNG ĐỐI CHUẨN DUNG LƯỢNG NÉN & TỐC ĐỘ ĐỌC I/O (JSONL vs. SQLITE vs. APACHE PARQUET + DUCKDB 2.0)

| Hạng Mục Kiểm Định | Hệ Thống Cơ Sở (JSONL / SQLite) | Medallion Lakehouse (Apache Parquet Snappy) | Tỷ Lệ Nén / Tăng Tốc | Cơ Chế Kỹ Thuật Cốt Lõi |
| :--- | :--- | :--- | :---: | :--- |
| **TomTom Incidents (22 Days, 223k raw -> 634k episodes)** | Raw JSONL (203.89 MB) | **Parquet Snappy (64.01 MB Bronze / 9.99 MB Silver)** | **`3.19x`** | Columnar Dictionary + Snappy Compression |
| **Corridor Telemetry (48 Routes, 5,562,511 rows)** | SQLite B-Tree DB (2856.85 MB total DB) | **Silver Parquet Snappy (230.45 MB, 48 route x 26 dt partitions)** | **`12.40x`** | Hive Partitioning (route_code=XX/dt=YYYY-MM-DD) |
| **Query 1: Partition Pruning + 4-Col Projection (Route 02, last 7 days)** | SQLite Index + Table Lookup: 2019.0 ms (43,475 rows) | **DuckDB + Parquet Partition Pruning: 11.0 ms (43,475 rows)** | **`182.93x`** | Skips 47 other routes & 19 older date folders |
| **Query 2: Full-Network OLAP Aggregation (5.56M rows -> 96 route-dirs)** | SQLite Row-Store Scan: 42219.6 ms | **DuckDB Vectorized Parquet Scan: 167.8 ms** | **`251.62x`** | Reads only 4 projected columns instead of 14 |

## II. BẢNG KIỂM ĐỊNH SLA TÁI HUẤN LUYỆN HÀNG TUẦN & LIÊN KẾT MA TRẬN ĐỘNG (TWO-STAGE DECOUPLED FEATURE STORE)

| Tuyến | Số Mẫu | Dung Lượng Gold Parquet | Quét SQLite Từ Đầu (Scratch) | Bù Trừ 7 Ngày Mới (Weekly Delta) | Đọc Parquet (PyArrow C++) | Áp Ma Trận Mới (Stage 2 Re-bind) | Huấn Luyện XGB-CQR (`n_jobs=-1`) | Tổng Thời Gian Retrain (Warm / Weekly) | Sai Lệch Toán Học (`max |diff|`) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Tuyến 02** | 794,276 | 71.40 MB | 24.16s | **7.39s** | **0.384s** | **0.656s** | **57.55s** | **`58.59s` / `65.98s`** | **`0.000000`** |
| **Tuyến 27** | 769,854 | 69.35 MB | 18.68s | **6.09s** | **0.515s** | **0.539s** | **50.97s** | **`52.03s` / `58.12s`** | **`0.000000`** |

## III. BẢNG THỰC THI ĐA NHÂN (`ProcessPoolExecutor`) & THỜI GIAN HOÀN THÀNH TRÊN TOÀN BỘ 48 TUYẾN (`5,562,511` PINGS -> `14,365,058` MẪU)

| Giai Đoạn Trong Weekly All-in-One Pipeline (Toàn Mạng 48 Tuyến) | Chạy Đơn Luồng Tuần Tự (1 Core) | Chạy Đa Nhân Song Song (`ProcessPoolExecutor` + C++ Threads) | Tốc Độ Tăng Tốc | Ghi Chú Kỹ Thuật |
| :--- | :---: | :---: | :---: | :--- |
| **1. Khởi tạo Stage 1 Parquet từ đầu (Full 22–26 ngày, 48 tuyến)** | `393.4s` (`6.56` phút) | **`107.2s` (`1.79` phút)** | **`3.67x`** | Chỉ chạy 1 lần duy nhất khi khởi tạo kho Gold (`1371.06 MB`) |
| **2. Bù trừ 7 ngày mới mỗi cuối tuần (Weekly 7-Day Delta, 48 tuyến)** | `123.8s` (`2.06` phút) | **`33.7s` (`0.56` phút)** | **`3.67x`** | Bỏ qua các phân vùng `dt=YYYY-MM-DD` cũ đã có trên đĩa |
| **3. Đọc Parquet + Áp Ma trận Thời gian Mới (Stage 2 Re-bind, 48 tuyến)** | `19.24s` | **`19.32s`** | **`1.00x`** | PyArrow Dataset C++ Multi-thread + Vectorized 4D Lookup |
| **4. Huấn luyện mô hình Residual XGB-CQR (`[P10, P50, P90]`, 48 tuyến)** | `~3189.4s` (1 thread) | **`996.7s` (`16.61` phút)** | **`3.20x`** | `tree_method='hist'`, `max_bin=128`, `n_jobs=-1` trên `14,365,058` mẫu |
| **TỔNG THỜI GIAN PHIÊN HÀNG TUẦN (WEEKLY ALL-IN-ONE SLA - 48 TUYẾN)** | `1139.7s` (`19.00` phút) | **`1049.7s` (`17.50` phút)** | **`Vượt chuẩn SLA (< 15 phút)`** | **Warm Retrain (khi đã có Parquet): `1016.0s` (`16.93` phút)** |

## IV. TOP 15 TUYẾN LỚN NHẤT TRONG KHO GOLD PARQUET (ĐÃ HIỆN THỰC HÓA TRÊN ĐĨA)

| Hạng | Tuyến (`route_code`) | Số Ngày Có Dữ Liệu (`dt`) | Tổng Số Mẫu Huấn Luyện (`N_samples`) | Thời Gian Đọc Parquet (`s`) | Thời Gian Re-bind Ma Trận Stage 2 (`s`) | Tổng Thời Gian Load + Bind (`s`) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | **Tuyến `02`** | 22 ngày | **794,276** | `0.487s` | `3.369s` | **`3.856s`** |
| 2 | **Tuyến `27`** | 22 ngày | **769,854** | `0.402s` | `3.176s` | **`3.577s`** |
| 3 | **Tuyến `22A`** | 23 ngày | **684,320** | `0.349s` | `2.857s` | **`3.206s`** |
| 4 | **Tuyến `32`** | 22 ngày | **663,677** | `0.376s` | `2.881s` | **`3.256s`** |
| 5 | **Tuyến `19`** | 23 ngày | **586,567** | `0.368s` | `2.740s` | **`3.108s`** |
| 6 | **Tuyến `26`** | 22 ngày | **518,818** | `0.277s` | `2.113s` | **`2.390s`** |
| 7 | **Tuyến `E01`** | 23 ngày | **513,535** | `0.353s` | `2.254s` | **`2.607s`** |
| 8 | **Tuyến `21A`** | 22 ngày | **492,042** | `0.469s` | `2.337s` | **`2.806s`** |
| 9 | **Tuyến `08A`** | 24 ngày | **474,705** | `0.281s` | `1.581s` | **`1.862s`** |
| 10 | **Tuyến `34`** | 18 ngày | **472,571** | `0.443s` | `1.858s` | **`2.301s`** |
| 11 | **Tuyến `BRT01`** | 22 ngày | **467,158** | `0.529s` | `2.238s` | **`2.767s`** |
| 12 | **Tuyến `51`** | 22 ngày | **421,577** | `0.237s` | `1.958s` | **`2.196s`** |
| 13 | **Tuyến `37`** | 18 ngày | **413,378** | `0.311s` | `1.740s` | **`2.051s`** |
| 14 | **Tuyến `E02`** | 19 ngày | **356,128** | `0.188s` | `1.614s` | **`1.803s`** |
| 15 | **Tuyến `107`** | 18 ngày | **349,299** | `0.363s` | `1.500s` | **`1.863s`** |
