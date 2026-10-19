# 40. BẢN ĐỒ TƯƠNG TÁC ĐỐI SOÁT ĐA NGUỒN TUYẾN 02 (TIMBUS vs BUSMAP vs OSM)
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Tệp trực quan hóa**: [`route_02_ground_truth_comparison.html`](file:///z:/Desktop/Bus_tracking/route_02_ground_truth_comparison.html)  
> **Thư viện nền tảng**: Leaflet.js v1.9.4  
> **Ngày tạo**: 19/10/2026  

---

## 1. MỤC TIÊU CỦA CÔNG CỤ TRỰC QUAN HÓA

Để người dùng và đội ngũ phát triển có thể kiểm tra trực quan lần cuối trước khi chuyển sang xây dựng Big Data Lakehouse và huấn luyện mô hình ETA, tệp bản đồ tương tác độc lập đã được tạo ra nhằm chồng lớp (Overlay) và đối soát trực tiếp 4 nguồn dữ liệu:
1. 🟩 **TimBus Official Master (Sở GTVT Hà Nội)**:
   - Đường tim đường chính thức (Polyline 178 điểm tọa độ, chiều dài $17,42\text{ km}$).
   - 40 nhà chờ/trạm dừng chính thức với mã định danh `ObjectID`.
2. 🟦 **OpenStreetMap Ground Truth (OSM Relation 12851968)**:
   - Các đoạn tim đường Ways từ cộng đồng OpenStreetMap.
   - 38 điểm dừng xe buýt chuẩn platform.
3. 🟧 **Luồng Telemetry GPS Thực Tế (Xe buýt đang vận hành)**:
   - Hành trình GPS thực tế của xe chạy trên tuyến kèm tọa độ chiếu hóa $s_{bus}$, vi sai tâm đường $d_\perp$, và vận tốc dẫn xuất $\bar{v} = \Delta s / \Delta t$.
4. 🟪 **Điểm Vi Sai Nổi Bật Giữa TimBus & BusMap**:
   - Vị trí các trạm mới (`774`, `5770`) và trạm được cập nhật di dời (`6422`, `6895`).

---

## 2. HƯỚNG DẪN TRUY CẬP VÀ SỬ DỤNG

### Cách mở tệp:
Người dùng có thể nhấp đúp trực tiếp vào tệp trong thư mục gốc của dự án:
```
z:\Desktop\Bus_tracking\route_02_ground_truth_comparison.html
```
Hoặc mở bằng bất kỳ trình duyệt web nào (Google Chrome, Microsoft Edge, Firefox).

### Các tính năng tương tác trên giao diện:
1. **Bảng điều khiển góc trên bên phải (Layer Controls)**:
   - Cho phép bật/tắt độc lập từng lớp dữ liệu để so sánh độ lệch trực quan (ví dụ: tắt OSM để chỉ nhìn TimBus và GPS xe, hoặc bật ảnh vệ tinh để soi nhà chờ xe buýt thực tế trên vỉa hè).
2. **Chuyển đổi bản đồ nền (Basemap Switcher)**:
   - *CartoDB Voyager*: Bản đồ giao thông sáng, tối ưu hiển thị các tuyến xe buýt.
   - *OpenStreetMap Chuẩn*: Xem chi tiết tên đường phố và số nhà.
   - *Vệ tinh Esri (World Imagery)*: Xem hình ảnh vệ tinh độ phân giải cao để kiểm tra vị trí trạm đỗ so với vỉa hè thực địa.
3. **Popup thông tin chi tiết**:
   - Nhấp vào bất kỳ trạm dừng hoặc điểm GPS nào để xem: Tên trạm, Mã định danh `ObjectID`, Tọa độ WGS84, Khoảng cách lũy kế từ đầu bến ($s_k$), và Vận tốc tức thời.

