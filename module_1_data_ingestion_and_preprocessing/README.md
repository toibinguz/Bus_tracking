# MODULE 1: THU THẬP VÀ TIỀN XỬ LÝ DỮ LIỆU (DATA INGESTION & PREPROCESSING)
> **Phần 1 - Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Mục tiêu**: Tự động hóa toàn bộ luồng thu thập Telemetry 24/7, trích xuất Master Ground Truth từ TimBus (Sở GTVT Hà Nội), làm sạch động học xe và chiếu hóa 1D Frenet cho toàn bộ 48 tuyến xe buýt.

---

## 1. CẤU TRÚC SUBCOMPONENTS & PIPELINES

```
module_1_data_ingestion_and_preprocessing/
├── step_1_1_busmap_crawler_and_relay/        # Tầng thu thập Telemetry 24/7
│   ├── cloud_crawler_runner.py                # Entrypoint chạy trên GitHub Actions (9 phút/phiên)
│   ├── local_production_crawler.py            # Crawler chạy trên máy trạm / VPS Windows / Linux
│   └── hf_lake_sync.py                        # Đồng bộ dữ liệu batch từ Hugging Face về Local
├── step_1_2_timbus_master_ground_truth/       # Tầng Ground Truth chính thức từ Sở GTVT (TimBus)
│   ├── timbus_client.py                       # Client reverse-engineered API TimBus (SHA256 audit)
│   ├── timbus_pipeline.py                     # Pipeline xử lý trạm và tim đường từng tuyến
│   └── ingest_all_active_routes.py            # Script cào hàng loạt toàn bộ 48 tuyến
├── step_1_3_telemetry_kinematic_sanitizer/    # Tầng làm sạch động học & lọc trôi dạt
│   ├── kinematic_filter.py                    # Tính vận tốc dẫn xuất v = ds / dt, bỏ GPS speed thô
│   └── dwell_detector.py                      # Nhận diện dừng đỗ theo ngưỡng ds < 15m, dt >= 20s
└── step_1_4_frenet_spatial_projection/        # Tầng chiếu hóa hình học 1D (Frenet Frame)
    └── multi_route_projector.py               # Vectorized projector chiếu pings lên tim đường
```

---

## 2. HƯỚNG DẪN THỰC THI STEP-BY-STEP CHO THÀNH VIÊN NHÓM

### Bước 1.1: Đồng bộ dữ liệu mới nhất từ Hugging Face
Khi cần kéo các batch dữ liệu mới nhất từ Cloud Lake về local:
```powershell
python module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/hf_lake_sync.py
```

### Bước 1.2: Trích xuất / Cập nhật Ground Truth TimBus toàn bộ 48 tuyến
Trích xuất danh bạ trạm dừng WGS84 chính thức và tim đường của 48 tuyến vào cơ sở dữ liệu:
```powershell
python module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/ingest_all_active_routes.py
```
*Kết quả đầu ra*:
- Bảng `timbus_route_master`: 48 tuyến (cự ly, giờ chạy, tần suất, bến đầu, bến cuối).
- Bảng `timbus_station_master`: 3.646 trạm dừng WGS84 kèm mã trạm nhà nước (`station_id`).
- Bảng `timbus_shape_master`: 17.631 điểm tim đường có lý trình tích lũy mét `cum_distance_m`.
- Bảng `pipeline_data_lineage_audit`: Toàn bộ mã băm SHA256 kiểm toán nguồn gốc.

### Bước 1.3 & 1.4: Chiếu hóa hình học 1D Frenet cho toàn mạng lưới
Chiếu hóa toàn bộ tọa độ GPS của xe buýt lên tim đường, tính độ lệch ngang $d_\perp$, lý trình $s$ và vận tốc dẫn xuất $\bar{v}$:
```powershell
python module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py
```
*Kết quả đầu ra*:
- Bảng `route_projected_telemetry`: 285.621 bản ghi đã chiếu hóa, sẵn sàng cho Tầng Lưu trữ Lớn và Mô hình ETA.

---

## 3. DATA CONTRACT & SCHEMA BẢO TOÀN
Mọi thành viên nhóm khi phát triển thêm các tuyến mới bắt buộc phải tuân thủ schema:
- **`route_code`**: Mã tuyến hiển thị (ví dụ: `'01'`, `'02'`, `'32'`, `'E01'`).
- **`direction`**: `'go'` (Chiều đi) hoặc `'re'` (Chiều về).
- **`s_bus_m`**: Lý trình dọc tuyến của xe (mét tính từ đầu bến).
- **`cross_track_m`**: Khoảng cách vuông góc từ xe đến tim đường ($\le 15\text{m}$ là chuẩn làn).
- **`derived_speed_kmh`**: Vận tốc dẫn xuất không gian - thời gian $\bar{v} = \Delta s / \Delta t \times 3.6$. Tuyệt đối không dùng trường GPS `speed` thô.

