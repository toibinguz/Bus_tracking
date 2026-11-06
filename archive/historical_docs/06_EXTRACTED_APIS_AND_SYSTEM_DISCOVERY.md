# 06. KHAI THÁC CÁC API KHÔNG CẦN PROOF/EPOCH & THÔNG TIN HỆ THỐNG (SYSTEM CONFIG & HIDDEN APIS)

Tài liệu này tổng hợp và phân tích toàn diện 4 API không cần chữ ký (`proof` và `epoch`) vừa phát hiện, cùng các thông tin nghiệp vụ và kỹ thuật vô giá được trích xuất phục vụ trực tiếp cho bài toán dự đoán ETA.

---

## 1. Bảng Tổng Hợp 4 API Mới Không Cần Chữ Ký

| File mẫu | Endpoint API | Phương thức | Tham số chính | Giá trị trích xuất được |
| :--- | :--- | :---: | :--- | :--- |
| **`timeline_raw.txt`** | `/v2/route/public/timeline/list` | `GET` | `regionCode=hn`, `routeId`, `time` | Danh sách trạm dừng theo thứ tự + **Biểu đồ giờ xuất bến từng chuyến trong ngày (`timeTableOut`)** |
| **`list_route_raw.txt`** | `/v2/route/public/list` | `GET` | `regionCode=hn` | **100% toàn bộ 230 tuyến xe buýt** tại Hà Nội (mã số, tên tuyến, loại tuyến, giá vé) |
| **`list_vehicle_raw.txt`** | `/v2/public/busmap/search_vehicle_v2` | `GET` | `regionCode=hn`, `vehicleId=29`, `page`, `limit` | **Danh bạ tất cả xe buýt Hà Nội** (biển số, mã xe ID nội bộ, tuyến phân công) |
| **`map_raw.txt`** | `/v2/route/public/region/get` | `GET` | `regionCode=hn_official` | **Cấu hình hệ thống**: BBox chuẩn Hà Nội, Vận tốc cơ sở từng loại tuyến, và **API ước tính ETA gốc của BusMap** |

---

## 2. Phân Tích Chuyên Sâu Từng Nguồn Dữ Liệu

### 2.1. API Lịch Trình & Giờ Xuất Bến: `timeline/list`
Endpoint: `GET /v2/route/public/timeline/list?regionCode=hn&routeId={routeId}&time={timestamp}`

#### Cấu trúc dữ liệu thu được:
- Trả về hai mảng trạm dừng: `forWardStationList` (chiều đi) và `backWardStationList` (chiều về).
- Mỗi trạm gồm: `stationOrder` (thứ tự 0, 1, 2, ...), `stationId` (ID trạm duy nhất), `stationName` (Tên trạm).
- **Trường dữ liệu đột phá: `timeTableOut` tại trạm đầu tuyến (`stationOrder: 0`)**:
  ```
  "timeTableOut": "18180,18900,19680,20460,21240,22020,22800,...,75900"
  ```
  Đây là **chuỗi thời gian xuất bến tính bằng giây từ nửa đêm (00:00:00)**:
  - Chuyến 1: $18.180\text{s} \equiv 05:03:00$ sáng.
  - Chuyến 2: $18.900\text{s} \equiv 05:15:00$ sáng ($\Delta t = 12$ phút).
  - Chuyến cuối: $75.900\text{s} \equiv 21:05:00$ tối.
  - Tổng cộng: **72 lượt xuất bến/ngày**. Khoảng giãn cách kế hoạch trung bình (**Planned Headway**) $h^* = 13.5$ phút (dao động $12 - 15$ phút).

#### Ứng dụng thực tiễn cho thuật toán ETA:
1. Giải quyết triệt để **bài toán xe đỗ ở đầu bến (Terminus Holding)** trong tài liệu 03: Bạn đã có giờ xuất bến theo kế hoạch ($T_{scheduled}$) chính xác tới từng giây.
2. Cho phép tính toán độ lệch xuất bến thực tế so với kế hoạch:
   $$\Delta T_{dispatch\_delay} = T_{actual\_departure} - T_{scheduled}$$

---

### 2.2. API Danh Sách Toàn Bộ Tuyến: `route/public/list`
Endpoint: `GET /v2/route/public/list?regionCode=hn`

#### Khẳng định về tỷ lệ sót tuyến:
- API này trả về **chính xác 230 tuyến xe buýt** tại Hà Nội:
  - **117 tuyến số thuần:** Tuyến 01 đến Tuyến 163.
  - **113 tuyến đặc thù:**
    - Các nhánh chữ cái: Tuyến 03A, 03B; 06A $\to$ 06E; 08A, 08B; 09A, 09B; 10A, 10B...
    - Các tuyến xe buýt điện VinBus (E01 $\to$ E10), BRT01, CNG01 $\to$ CNG07...
- **Ý nghĩa:** Bạn đã có **bảng Master Catalog 100% của toàn bộ mạng lưới**. Không bao giờ phải lo lắng về việc đoán mò hay sót tuyến nữa!

---

### 2.3. API Danh Bạ Xe Toàn Thành Phố: `search_vehicle_v2`
Endpoint: `GET /v2/public/busmap/search_vehicle_v2?regionCode=hn&limit=100&vehicleId=29&page=0`

- Biển số xe buýt Hà Nội đều bắt đầu bằng đầu số `29` (ví dụ `29B`, `29F`, `29E`, `29H`).
- Bằng cách phân trang (`page=0, 1, 2...`) với `vehicleId=29`, bạn có thể tải về **toàn bộ danh mục tất cả xe buýt được đăng ký hoạt động tại Hà Nội**, kể cả những xe đang nằm trong bãi sửa chữa hoặc đang nghỉ đêm.
- Mỗi bản ghi cung cấp cặp liên kết:
  $$\text{Vehicle ID (id: 8788668)} \longleftrightarrow \text{Biển số (title: 29B-002.10)} \longleftrightarrow \text{Mã tuyến (routeId: 47)}$$
  $\implies$ Dùng các ID này gọi thẳng vào `vehicle_hn/get?id={id}` để lấy GPS tức thời mà không cần chữ ký.

---

### 2.4. File Cấu Hình Hệ Thống `region/get`: Các "Kho Báu" Ẩn Giấu
Endpoint: `GET /v2/route/public/region/get?regionCode=hn_official`

1. **Bounding Box Chuẩn của Hà Nội (`region`):**
   ```
   "105.703949,20.933177,106.011921,21.252462"
   ```
   Tọa độ hình chữ nhật bao quanh toàn bộ hệ thống giao thông Hà Nội do chính BusMap định nghĩa. Bạn có thể dùng trực tiếp 4 giá trị này làm tham số `bbox` cho TomTom API tầng 1 (thay vì tự căn chỉnh).

2. **Vận Tốc Cơ Sở Mặc Định Theo Loại Tuyến (`avg_speeds`):**
   Hệ thống BusMap định nghĩa sẵn vận tốc trung bình thiết kế cho từng loại phương tiện:
   - `route_type: 1` (Xe buýt nội đô thông thường): **$21\text{ km/h}$**
   - `route_type: 2` (Xe buýt liên tỉnh / cao tốc): **$50\text{ km/h}$**
   - `route_type: 3` (Xe buýt ngoại thành): **$45\text{ km/h}$**
   - `route_type: 4` (Xe buýt kế cận): **$35\text{ km/h}$**
   - `route_type: 101` (Đường sắt đô thị / Trục BRT đông đúc): **$17\text{ km/h}$**
   $\implies$ Đây là thông số khởi tạo ma trận vận tốc ($Speed\ Profile\ Prior$) cực kỳ chính xác cho tầng Batch của nhóm!

3. **API Ước Tính ETA Gốc của BusMap (`api_goto2` & `api_goto_multi`):**
   - `https://api.busmap.city/v2/public/busmap/estimate_bus_to_station`
   - `https://api.busmap.city/v2/public/busmap/estimate_bus_to_station_multi`
   $\implies$ **Điểm tựa vàng cho đồ án:** Bạn có thể gọi API này để lấy chỉ số ETA của chính BusMap làm **chuẩn đối sánh (Ground Truth Benchmark)**. Trong báo cáo đồ án, bạn có thể lập bảng so sánh sai số:
     * *Mô hình của nhóm (Lambda + TomTom + Bunching Control)* vs *ETA của BusMap gốc*.

4. **Các File Static Dump Dữ Liệu Tĩnh:**
   - Tuyến đường: `https://files.busmap.vn/hn.routes.xyz`
   - Trạm dừng: `https://files.busmap.vn/hn.stations.xyz`
   - Thông tin hành trình: `https://files.busmap.vn/hn.routeinfo.xyz`
   - Bản đồ Vector Tile Server Việt Nam: `https://bmap-tiles-a.golabs.vn/data/vietnam.json?lang=vi`

