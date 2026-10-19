# BƯỚC 1.2: THU THẬP & QUẢN TRỊ MASTER GROUND TRUTH (TIMBUS / TRAMOC)
> **Thư mục**: `module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/`  
> **Cơ quan thẩm quyền**: Trung tâm Quản lý Giao thông công cộng TP Hà Nội (TRAMOC) / Sở GTVT Hà Nội  
> **Cơ sở dữ liệu gốc**: [TimBus.vn](http://timbus.vn)

---

## 1. MỤC TIÊU & NHIỆM VỤ CỦA BƯỚC

Xây dựng hạ tầng dữ liệu không gian mặt đất chuẩn mực (Master Ground Truth) cho toàn bộ hệ thống xe buýt Hà Nội:
1. **Kết nối API chính thức TimBus**: Thu thập danh bạ tuyến, danh mục trạm dừng WGS84 có thẩm quyền và hình học tim đường (Centerline Polyline).
2. **Khắc phục triệt để lỗi của dữ liệu cũ (OSM/BusMap)**: Triệt tiêu các lỗi trôi tọa độ, mất trạm, vẽ lệch tim đường, hoặc nối chéo ngã tư.
3. **Tính sẵn khoảng cách tích lũy (Cumulative Distance)**: Tính toán tọa độ 1D dọc tim đường ($s$) cho từng trạm và từng đỉnh polyline để phục vụ chiếu Frenet và tính ETA.

---

## 2. CÁC THÀNH PHẦN MÃ NGUỒN

| Tệp Mã Nguồn | Chức Năng Chính |
| :--- | :--- |
| [`timbus_client.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/timbus_client.py) | Client HTTP kết nối dịch vụ API của TimBus (`action.ashx`) để tải danh sách tuyến, trạm và hình học tim đường. |
| [`timbus_pipeline.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/timbus_pipeline.py) | Pipeline xử lý dữ liệu cho từng tuyến: kiểm tra hợp lệ, tính khoảng cách tích lũy $s$ và lưu trữ vào SQLite. |
| [`ingest_all_active_routes.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/ingest_all_active_routes.py) | Trình thực thi hàng loạt cho toàn bộ **48 tuyến** hoạt động tại Hà Nội. |

---

## 3. CÁCH CHẠY & KIỂM THỬ

### Chạy thu thập toàn bộ 48 tuyến:
```bash
python module_1_data_ingestion_and_preprocessing/step_1_2_timbus_master_ground_truth/ingest_all_active_routes.py
```

### Chạy thu thập một tuyến cụ thể qua CLI:
```bash
python scripts/ingest_official_timbus_routes.py --fid 2
```

### Kết quả đầu ra:
- **Bảng `timbus_route_master`**: 48 tuyến.
- **Bảng `timbus_station_master`**: 3.646 trạm dừng.
- **Bảng `timbus_shape_master`**: 17.631 điểm tim đường.
- **Bảng `dim_station_crosswalk`**: 3.646 trạm dừng đã gán khoảng cách tích lũy $s_{\text{station}}$ (mét).
- **Tệp thô sao lưu**: `data/ground_truth/timbus_official/raw/` (phục vụ audit & lineage).

