# MODULE 1: THU THẬP VÀ TIỀN XỬ LÝ DỮ LIỆU (DATA INGESTION & PREPROCESSING)
> **Snapshot note (2026-11-10):** This README describes module topology; operational counts and commands are snapshot-dependent. Treat public entry points as authoritative over exhaustive support-module listings.
> **Phần 1 - Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Mục tiêu**: Tự động hóa toàn bộ luồng thu thập Telemetry 24/7, quản trị Master Ground Truth từ BusMap Canonical (`hanoi_bus_data`), làm sạch động học xe và chiếu hóa 1D Frenet cho toàn mạng lưới xe buýt.

---

## 1. CẤU TRÚC SUBCOMPONENTS & PIPELINES

```
module_1_data_ingestion_and_preprocessing/
├── step_1_1_busmap_crawler_and_relay/        # Tầng thu thập Telemetry 24/7
│   ├── cloud_crawler_runner.py                # Entrypoint chạy trên GitHub Actions (9 phút/phiên)
│   ├── local_production_crawler.py            # Crawler chạy trên máy trạm / VPS Windows / Linux
│   └── hf_lake_sync.py                        # Đồng bộ dữ liệu batch từ Hugging Face về Local
├── step_1_3_telemetry_kinematic_sanitizer/    # Tầng làm sạch động học, nạp lô & tách chuyến
│   ├── bulk_ping_ingester.py                  # Nạp và khử trùng lặp pings thô vào vehicle_unique_pings
│   ├── kinematic_engine.py                    # Tính khoảng cách Haversine & động học vi phân
│   ├── telemetry_sanitizer.py                 # Chuẩn hóa WGS84, lọc tọa độ ngoại lai
│   └── trip_segmenter.py                      # Tách chuyến có nối lỗ thủng detour & cắt đuôi bến đỗ
├── step_1_4_frenet_spatial_projection/        # Tầng chiếu hóa hình học 1D (Frenet Frame)
│   ├── multi_route_projector.py               # Vectorized projector chiếu pings lên tim đường (48 tuyến)
│   └── tomtom_incident_projector.py           # Chiếu sự cố giao thông TomTom khớp đoạn trạm
└── step_1_5_busmap_canonical_migration/       # Tầng nạp Ground Truth BusMap Canonical
    └── ingest_busmap_canonical.py             # Script nạp 176 tuyến, 13.301 trạm, 118.563 shape points
```

---

## 2. HƯỚNG DẪN THỰC THI CHO THÀNH VIÊN NHÓM

### Bước 1.1: Đồng bộ dữ liệu mới nhất từ Hugging Face
Khi cần kéo các batch dữ liệu mới nhất từ Cloud Lake về local:
```powershell
python module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py
```

### Bước 1.2: Cập nhật Master Ground Truth Canonical
Nạp danh bạ trạm dừng WGS84 chính thức và tim đường của toàn bộ mạng lưới vào cơ sở dữ liệu:
```powershell
python scripts/ingest_canonical_busmap_master.py
```
*Kết quả đầu ra*:
- Bảng `canonical_route_master`: 176 tuyến (cự ly, giờ chạy, tần suất, bến đầu, bến cuối).
- Bảng `canonical_station_master`: 13.301 trạm dừng WGS84 đồng bộ 1:1 với mã trạm telemetry (`station_id`).
- Bảng `canonical_shape_master`: 118.563 điểm tim đường có lý trình tích lũy mét `cum_distance_m`.

### Bước 1.3: Chiếu hóa hình học 1D Frenet cho toàn mạng lưới
Chiếu hóa toàn bộ tọa độ GPS của xe buýt lên tim đường, tính độ lệch ngang $d_\perp$, lý trình $s$ và vận tốc dẫn xuất $\bar{v}$:
```powershell
python scripts/parallel_multi_route_projector.py
```
*Kết quả đầu ra*:
- Bảng `route_projected_telemetry` và View phân tích `v_bus_to_next_station`.
