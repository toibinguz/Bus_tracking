# ARCHIVE CATALOG (LƯU TRỮ VẬT PHẨM VÀ MÃ NGUỒN CŨ)

Thư mục này lưu trữ các bản ghi lịch sử, mã nguồn thử nghiệm ban đầu (POC), các script kiểm thử không còn sử dụng trực tiếp trong luồng vận hành sản xuất (production) nhưng được bảo lưu để phục vụ đối chiếu, kiểm toán và báo cáo học thuật.

---

## Cấu Trúc Lưu Trữ

### 1. `archive/deprecated_scripts/`
Chứa các script phiên bản đầu tiên trước khi hệ thống được chuyển đổi sang kiến trúc Micro-batching và Modular:
- `crawler_bus.py`: Phiên bản crawler xe buýt ban đầu.
- `crawler_tomtom.py`: Phiên bản crawler TomTom độc lập ban đầu.
- `benchmark_multilevel_congestion.py`: Thử nghiệm đo lường thuật toán phân cấp tắc đường.
- `experiment_tomtom_interpolation.py`: Thử nghiệm nội suy luồng giao thông TomTom.
- `init_master_metadata.py`: Script khởi tạo cấu hình danh bạ đời đầu.
- `test_osm_route.py`: Thử nghiệm truy vấn quan hệ OSM ban đầu.

### 2. `archive/legacy_dumps/`
Chứa các dữ liệu thô, text dump và kết quả benchmark mẫu từ giai đoạn thăm dò API BusMap:
- `list_route_raw.txt`, `list_vehicle_raw.txt`, `map_raw.txt`, `timeline_raw.txt`: Các mẫu phản hồi thô từ ứng dụng Android.
- `benchmark_multilevel_results.json`, `discovered_vehicles.json`, `experiment_tomtom_validation.json`.
- `parse_raw.py`, `quick_scan_routes.py`, `test.py`, `test02.py`: Script quét nhanh mẫu dữ liệu.

### 3. `archive/research_apis/`
Chứa các nghiên cứu và đánh giá tính khả thi đối với các API bản đồ/giao thông bên thứ 3:
- `vietmap_*.txt`, `check_vietmap_docs.py`, `check_traffic_layer.py`: Đánh giá API VietMap Traffic.
- `here_traffic_client.py`: Đánh giá API HERE Traffic Freemium.
- `hf_space_deployment/`: Mã nguồn mẫu demo triển khai ban đầu trên Hugging Face Spaces (Streamlit).

### 4. `archive/legacy_tests/`
- `Test_tomtom/`: Chứa các script dựng bản đồ Leaflet thử nghiệm ban đầu (`map_traffic.py`, `map_traffic_hybrid.py`, `map_traffic_offline.py`), bộ đệm ảnh tile OSM ngoại tuyến (`osm_tiles/`), và các file JSON kiểm thử giao thông TomTom.

