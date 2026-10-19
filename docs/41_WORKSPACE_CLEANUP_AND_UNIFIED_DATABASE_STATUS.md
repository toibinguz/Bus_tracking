# 41. TÁI TỔ CHỨC KHÔNG GIAN LÀM VIỆC & QUẢN TRỊ CƠ SỞ DỮ LIỆU THỐNG NHẤT (.DB)
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Ngày thực hiện**: 19/10/2026  
> **Quyết định kỹ thuật**: Tạm thời bỏ qua tầng Lakehouse phức tạp, hợp nhất toàn bộ dữ liệu sạch vào tệp cơ sở dữ liệu duy nhất (`.db`) phục vụ trực tiếp bài toán dự báo ETA.

---

## 1. KẾT QUẢ TÁI CẤU TRÚC WORKSPACE (CLEANLINESS & MODULARITY)

Không gian làm việc đã được thu dọn sạch sẽ theo đúng tinh thần của [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md):

1. **Thư mục gốc (`/`)**:
   - Chỉ giữ lại các tệp cấu hình, tài liệu cốt lõi và bản đồ trực quan kiểm tra:
     * `AGENTS.md` & `GEMINI.md`: Hiến chương quản trị AI.
     * `route_02_ground_truth_comparison.html`: Bản đồ tương tác đối soát trạm và tuyến.
     * `README.md` & `.gitignore`.
2. **Thư mục `experiments/`**:
   - Được phân chia thành 2 tiểu mục chuyên biệt, không để script nháp rải rác:
     * [`experiments/telemetry_audit_and_hardware_probe/`](file:///z:/Desktop/Bus_tracking/experiments/telemetry_audit_and_hardware_probe/): Chứa các kiểm thử nhịp xung phần cứng GPS (chu kỳ 30s Transerco và 20s VinBus).
     * [`experiments/timbus_ground_truth_and_frenet_eval/`](file:///z:/Desktop/Bus_tracking/experiments/timbus_ground_truth_and_frenet_eval/): Chứa các script phân tích gói tin TimBus, đối soát trạm và kiểm định vi sai tâm đường.
3. **Thư mục `scripts/`**:
   - Chỉ chứa các Façade CLI hoàn chỉnh, có kiểm thử sạch:
     * `build_timbus_busmap_crosswalk.py`: Xây dựng bảng ánh xạ Master Crosswalk.
     * `ingest_official_timbus_routes.py`: Tải và lưu vết dữ liệu trạm chính thức từ Sở GTVT.

---

## 2. HIỆN TRẠNG CƠ SỞ DỮ LIỆU DUY NHẤT (`data/telemetry_audit_2026_10_17_18.db`)

Tất cả các nguồn dữ liệu cần thiết cho bài toán ETA đã được nạp trọn vẹn vào tệp SQLite duy nhất (kích thước ~480 MB, tối ưu chỉ mục index):

| Nhóm Dữ Liệu | Bảng Cơ Sở Dữ Liệu | Số Bản Ghi | Ý Nghĩa Sử Dụng |
| :--- | :--- | :---: | :--- |
| **Master Reference** | `dim_route_crosswalk` | **165** | Bảng ánh xạ 100% mạng lưới tuyến Hà Nội (khớp $98,8\%$ với BusMap) |
| | `dim_station_crosswalk` | **76** | Danh bạ 40 trạm đi + 36 trạm về Tuyến 02 kèm tọa độ WGS84 và mét lũy kế $s_k$ |
| | `timbus_route_master` | **1** | Thông số vận hành chính thức Tuyến 02 (tần suất, 17 xe, biểu đồ giờ) |
| | `timbus_shape_master` | **350** | Tọa độ tim đường WGS84 chính thức ($17,42\text{km}$ chiều đi, $16,48\text{km}$ chiều về) |
| **Telemetry & Projection** | `raw_telemetry` | **863.428** | Dữ liệu GPS thô ban đầu |
| | `vehicle_unique_pings` | **663.342** | Bản tin GPS độc nhất đã khử trùng lặp |
| | `route_02_projected_telemetry` | **23.258** | **Bảng dữ liệu cốt lõi cho ETA**: Đã chiếu hóa $(s_{bus}, d_\perp)$, vận tốc dẫn xuất $\bar{v}$ và hướng chạy `go`/`re` |
| **Audit & Governance** | `pipeline_data_lineage_audit` | **1** | Nhật ký kiểm toán lưu vết mã băm `SHA256` và thời điểm trích xuất |

---

## 3. SẴN SÀNG CHO BÀI TOÁN DỰ BÁO ETA

Với việc dữ liệu đã được chiếu hóa và làm sạch trong `route_02_projected_telemetry`, hệ thống đã sẵn sàng 100% để bước sang giai đoạn tính toán ETA:
1. **Historical Segment Average (Baseline)**: Tính thời gian di chuyển trung bình giữa các cặp trạm ($T_{station\_i \to station\_j}$) theo từng khung giờ (Cao điểm sáng, thấp điểm trưa, cao điểm chiều, tối).
2. **Real-time Dynamic ETA**:
   $$\widehat{T}_{ETA}(bus, station_k) = \frac{s_k - s_{bus}(t)}{\bar{v}_{segment}} + \sum \text{DwellTime}_{intermediate}$$
3. **Machine Learning Model (LightGBM)**: Huấn luyện mô hình hồi quy đặc trưng không gian - thời gian dự báo thời gian đến trạm với nhãn thực tế $Y = t_{actual\_arrival} - t_{current}$.

