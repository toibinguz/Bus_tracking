# ĐẶC TẢ KIẾN TRÚC: HỆ THỐNG THEO DÕI XE BUÝT GIẬT CỤC RỜI RẠC CHỈ DÙNG DỮ LIỆU BUSMAP
> **Implementation note (2026-11-10):** The browser animation ban remains authoritative. Server-side physical projection under [SPEC-15](15_PHYSICAL_KINEMATICS_AND_SERVING_SPEC.md) is allowed and does not authorize browser interpolation. The eventual public facade, not the current monolith, is the intended integration boundary.
## Document ID: `04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC`
**Tác giả:** @architect  
**Phiên bản:** 1.0.0 (Simplicity First)  
**Trạng thái:** APPROVED / READY FOR IMPLEMENTATION  
**Mục tiêu áp dụng:** `step_3_4_eta_serving_and_evaluation` & `step_3_5_web_demo`

---

## 1. BỐI CẢNH & NGUYÊN TẮC THIẾT KẾ (SIMPLICITY FIRST)

### 1.1. Lý do thay đổi kiến trúc (Post-Mortem of Prior Approach)
Kiến trúc cũ cố gắng tích hợp đa nguồn dữ liệu (TimBus qua TCP cổng 9149 với XOR cipher + binary decoding kết hợp BusMap HTTPS) và cố gắng mô phỏng chuyển động mượt mà 60 FPS (Linear Tweening, Hermite Spline, Dead Reckoning, Heading Unwrapping). Kết quả thực tế:
- **Quá phức tạp và dễ vỡ:** TimBus phụ thuộc vào socket nhị phân, FSM bất đồng bộ, luồng phụ, dễ đứt kết nối và sai lệch protocol.
- **Nội suy sinh ảo giác:** Nội suy 60 FPS giữa các mốc GPS cách nhau 15s - 30s gây hiện tượng xe "trôi dạt", "teleport", đâm xuyên công trình khi xe rẽ cua hoặc đứng chờ đèn đỏ.
- **Tốn tài nguyên trình duyệt:** Vòng lặp `requestAnimationFrame` 60 FPS liên tục tính toán ma trận xoay và nội suy tọa độ gây ngốn CPU/pin trên thiết bị người dùng mà không mang lại giá trị thực tế cho việc bắt xe buýt.

### 1.2. Triết lý mới: "Kiến trúc Giật cục Rời rạc" (Discrete / Stepped Updates)
- Chuẩn UX kinh điển của Google Maps, BusMap và transit apps toàn cầu: Vị trí xe buýt bản chất là các mốc tọa độ định kỳ (sampled GPS snapshots).
- **Không nội suy liên tục 60 FPS:** Khi có bản tin GPS mới (mỗi 15 giây), Leaflet Marker cập nhật trực tiếp tọa độ mới (`marker.setLatLng([newLat, newLng])`).
- **Nguồn dữ liệu độc nhất:** 100% sử dụng API chính thức `route_bus_gps` từ BusMap qua HTTPS an toàn.
- **Độ tin cậy tuyệt đối:** Đúng tuyến, đúng chiều hành trình (lượt đi/lượt về), 0 xe lặp, tọa độ đã được BusMap map-match và gắn góc quay (`Deg`).

---

## 2. BÃI BỎ TRIỆT ĐỂ (COMPLETE DEPRECATION LIST)

Mọi thành phần dưới đây bị **CẤM TRIỆT ĐỂ** và phải được loại bỏ 100% khỏi codebase `step_3_4` và `step_3_5`:

| Thành phần bãi bỏ | Lý do | Trạng thái |
| :--- | :--- | :--- |
| **TimBus TCP Client (Cổng 9149)** | Socket TCP nhị phân không ổn định, tốn tài nguyên bảo trì | **LOẠI BỎ 100%** |
| **XOR Cipher & Binary Codec** | Giải mã byte nhị phân phức tạp, dễ vỡ khi server đổi spec | **LOẠI BỎ 100%** |
| **Dead Reckoning Algorithm** | Ngoại suy quán tính gây lỗi đâm xuyên ngã tư, trôi dạt tọa độ | **LOẠI BỎ 100%** |
| **60 FPS Tweening / Hermite Spline** | Vòng lặp nội suy rườm rà, tốn CPU browser vô ích | **LOẠI BỎ 100%** |
| **Dual-Source Reconciliation** | Logic so sánh/ghép TimBus + BusMap gây overhead không cần thiết | **LOẠI BỎ 100%** |

---

## 3. NGUỒN DỮ LIỆU ĐỘC NHẤT: BUSMAP `route_bus_gps`

### 3.1. Điểm kết nối (Upstream Endpoint)
- **Hàm tái sử dụng:** `fetch_route_buses_live(route_id: int, direction: int = 0)`  
  Tại module: `module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py`
- **Giao thức:** HTTPS GET
- **URL mẫu:**
  ```text
  https://api.busmap.city/v2/public/busmap/route_bus_gps?regionCode=hn&routeId={route_id}&direction={direction}
  ```
  - `direction = 0`: Chiều về (B $\to$ A)
  - `direction = 1`: Chiều đi (A $\to$ B)
- **Cơ chế xác thực:** Tự động sinh Header `epoch` (epoch ms) và `proof` (MD5 hash kèm salt `:Bus2019M@p_`), kèm định danh thiết bị hợp lệ.

### 3.2. Cấu trúc Payload trả về từ BusMap Upstream
```json
[
  {
    "Id": 8823349,
    "VehicleNumber": "29B-400.44",
    "RouteId": 27,
    "Lat": 21.001087,
    "Lng": 105.817024,
    "Deg": 238.69349,
    "Speed": 13,
    "lastUpdateTime": "2026-11-08T21:58:04+07:00",
    "currentStationId": 145,
    "nextStationId": 533
  }
]
```

### 3.3. Quy tắc Lọc và Làm sạch Dữ liệu (Data Hygiene)
Bản tin chỉ được chấp nhận vào DTO khi thỏa mãn:
1. `Id` nguyên dương hợp lệ (`Id > 0`).
2. `RouteId == requested_route_id`.
3. Tọa độ nằm trong hộp giới hạn khu vực Hà Nội mở rộng:
   $$\text{Lat} \in [20.50, 21.50], \quad \text{Lng} \in [105.50, 106.30]$$
4. Không lặp biển số hoặc ID trong cùng một phản hồi (deduplication theo `Id`).

---

## 4. ĐẶC TẢ GIAO DIỆN & CẤU TRÚC CODE (TỐI GIẢN)

```
module_3_bus_eta_prediction/
├── step_3_4_eta_serving_and_evaluation/
│   ├── __init__.py
│   └── busmap_service.py       # Client truy vấn & chuẩn hóa dữ liệu BusMap
└── step_3_5_web_demo/
    ├── __init__.py
    ├── app.py                  # FastAPI server tối giản (API + Static serving)
    └── static/
        ├── index.html          # HTML + CSS layout tinh gọn
        ├── app.js              # Leaflet logic giật cục (polling 15s)
        └── bus_icon.svg        # Vector biểu tượng xe buýt kèm mũi tên hướng
```

---

### 4.1. Đặc tả Backend Service: `step_3_4_eta_serving_and_evaluation/busmap_service.py`

#### 4.1.1. Data Transfer Object (Pydantic Model / TypedDict)
```python
from pydantic import BaseModel, Field
from typing import Optional, List

class BusVehicleDTO(BaseModel):
    id: int = Field(..., description="ID xe duy nhất từ BusMap")
    plate: str = Field(..., description="Biển số xe (ví dụ: 29B-400.44)")
    route_id: int = Field(..., description="Mã tuyến xe buýt")
    direction: int = Field(..., description="0: Chiều về, 1: Chiều đi")
    lat: float = Field(..., description="Vĩ độ WGS84")
    lng: float = Field(..., description="Kinh độ WGS84")
    deg: float = Field(..., description="Góc xoay theo hướng di chuyển (0 - 360 độ)")
    speed_kmh: float = Field(..., description="Vận tốc hiện tại (km/h)")
    updated_at: str = Field(..., description="Mốc thời gian cập nhật của xe (ISO 8601)")
    current_station_id: Optional[int] = None
    next_station_id: Optional[int] = None

class RouteLiveResponse(BaseModel):
    route_id: int
    direction: int
    count: int
    timestamp: str
    vehicles: List[BusVehicleDTO]
```

#### 4.1.2. Public API Function
```python
def fetch_live_vehicles_for_route(route_id: int, direction: int = 0) -> RouteLiveResponse:
    """
    Truy vấn xe đang chạy trực tiếp từ BusMap API qua catalog_refresher.fetch_route_buses_live.
    Lọc các bản ghi không hợp lệ hoặc ngoài phạm vi địa lý Hà Nội.
    Trả về RouteLiveResponse chứa danh sách BusVehicleDTO.
    """
```

---

### 4.2. Đặc tả API Server: `step_3_5_web_demo/app.py`

Sử dụng FastAPI phục vụ 3 endpoint REST duy nhất:

#### Endpoint 1: `GET /api/routes`
- **Mục đích:** Cung cấp danh mục các tuyến xe buýt hỗ trợ cho dropdown trên giao diện.
- **Nguồn dữ liệu:** Đọc từ `data/metadata/hust_cluster_config.json`.
- **Response Format:**
```json
[
  {
    "route_id": 27,
    "route_no": "27",
    "name": "Bến xe Yên Nghĩa - Nam Thăng Long"
  },
  {
    "route_id": 32,
    "route_no": "32",
    "name": "Bến xe Giáp Bát - Nhổn"
  }
]
```

#### Endpoint 2: `GET /api/live-vehicles`
- **Tham số truy vấn (Query Params):**
  - `route_id: int` (Bắt buộc, ví dụ: `27`)
  - `direction: int = 0` (Mặc định `0`, nhận `0` hoặc `1`)
- **Response Format:** (HTTP 200)
```json
{
  "route_id": 27,
  "direction": 0,
  "count": 14,
  "timestamp": "2026-11-08T22:00:00+07:00",
  "vehicles": [
    {
      "id": 8823349,
      "plate": "29B-400.44",
      "route_id": 27,
      "direction": 0,
      "lat": 21.001087,
      "lng": 105.817024,
      "deg": 238.69,
      "speed_kmh": 13.0,
      "updated_at": "2026-11-08T21:58:04+07:00",
      "current_station_id": 145,
      "next_station_id": 533
    }
  ]
}
```

#### Endpoint 3: `GET /api/health`
- **Mục đích:** Health check cho tester và monitor.
- **Response Format:**
```json
{
  "status": "healthy",
  "mode": "busmap_discrete_only",
  "upstream": "https://api.busmap.city/v2/public/busmap/route_bus_gps"
}
```

---

### 4.3. Đặc tả Frontend: `step_3_5_web_demo/static/`

#### 4.3.1. Giao diện Người dùng (`index.html`)
- Thanh điều khiển trên cùng (Control Bar):
  - **Dropdown chọn tuyến:** Danh sách tuyến tải từ `/api/routes` (mặc định chọn Tuyến 27).
  - **Nút chuyển chiều:** Nút gạt hoặc 2 tab: `Chiều đi (A -> B)` và `Chiều về (B -> A)`.
  - **Badge thông tin:** Số lượng xe đang chạy (`X xe đang hoạt động`) và đồng hồ đếm ngược chu kỳ cập nhật kế tiếp (`Làm mới sau: 15s`).
- Khung bản đồ toàn màn hình (Map View):
  - Khởi tạo Leaflet.js với nền OpenStreetMap tile.
  - Tọa độ trung tâm: `[21.0285, 105.8542]` (Hà Nội), zoom 13.

#### 4.3.2. Cơ chế Giật cục Rời rạc (`app.js`)
- **Chu kỳ Polling:** Định kỳ 15 giây (`setInterval(pollLiveVehicles, 15000)`).
- **Bộ lưu trữ Marker:** `const activeMarkers = new Map(); // id -> L.marker`
- **Thuật toán cập nhật (Discrete Update Algorithm):**
  1. Khi nhận danh sách xe mới từ `/api/live-vehicles`:
  2. Tạo một tập hợp `currentIds = new Set()`.
  3. Duyệt từng xe `v` trong danh sách:
     - Thêm `v.id` vào `currentIds`.
     - Nếu xe đã có trong `activeMarkers`:
       - Gọi thẳng `marker.setLatLng([v.lat, v.lng])` (Cập nhật vị trí tức thời, **KHÔNG tweening, KHÔNG dead reckoning**).
       - Cập nhật góc xoay CSS: Xoay icon theo `v.deg` độ.
       - Cập nhật nội dung Popup: Biển số `v.plate`, Tốc độ `v.speed_kmh km/h`, Giờ cập nhật `v.updated_at`.
     - Nếu xe chưa có:
       - Tạo mới `L.marker([v.lat, v.lng], { icon: createBusIcon(v.deg) })`.
       - Gắn Popup thông tin xe.
       - Lưu vào `activeMarkers.set(v.id, marker)`.
  4. Duyệt các `id` trong `activeMarkers`:
     - Nếu `id` không còn trong `currentIds`: Gọi `marker.remove()` và xóa khỏi Map (thu hồi xe đã offline/hết ca).
- **Tương tác khi người dùng đổi Tuyến hoặc đổi Chiều:**
  - Xóa toàn bộ marker hiện có trên bản đồ (`activeMarkers.forEach(m => m.remove()); activeMarkers.clear();`).
  - Gọi poll ngay lập tức (`pollLiveVehicles()`).

---

## 5. MÔ HÌNH HỌC VÀ THUẬT TOÁN (FORMAL MATHEMATICAL SPEC)

### 5.1. Định nghĩa Không gian Trạng thái Rời rạc
Trạng thái của một xe $v$ tại thời điểm lấy mẫu $k$ được biểu diễn bởi vector hữu hạn:
$$S_k(v) = \begin{pmatrix} \phi_k \\ \lambda_k \\ \theta_k \\ \nu_k \end{pmatrix} \in \mathbb{R}^4$$
Trong đó:
- $\phi_k$: Vĩ độ (Latitude)
- $\lambda_k$: Kinh độ (Longitude)
- $\theta_k \in [0, 360)$: Góc hướng di chuyển (Heading bearing)
- $\nu_k \ge 0$: Tốc độ đo đạc (km/h)

### 5.2. Hàm chuyển trạng thái hiển thị (Discrete Step Function)
Tại chu kỳ quan sát thứ $k$, vị trí hiển thị của marker trên bản đồ Leaflet $\mathcal{M}(v)$ tuân theo toán tử gán trực tiếp:
$$\mathcal{M}_{t}(v) = \begin{cases} 
(\phi_k, \lambda_k) & \text{khi } t \in [t_k, t_{k+1}) \\
(\phi_{k+1}, \lambda_{k+1}) & \text{khi } t \ge t_{k+1}
\end{cases}$$
Toán tử này đảm bảo:
1. **Độ trung thực 100%:** Marker luôn nằm chính xác tại điểm GPS mà nhà mạng/BusMap thu nhận, không sinh ra tọa độ giả tưởng.
2. **Độ phức tạp tính toán:** $O(1)$ cho mỗi xe mỗi chu kỳ, tổng độ phức tạp $O(N)$ với $N \le 30$ xe/tuyến.
3. **Mức tiêu thụ CPU trình duyệt:** $\approx 0\%$ giữa hai chu kỳ cập nhật (không tốn tài nguyên chạy animation loop).

---

## 6. TIÊU CHÍ NGHIỆM THU CHO @blind_tester (DEFINITION OF DONE)

`@blind_tester` sẽ thực hiện bộ kiểm thử hộp đen độc lập theo các tiêu chí sau:

### TC-01: Bãi bỏ 100% TimBus và 60 FPS Engine
- **Mục tiêu:** Đảm bảo không còn bất kỳ dấu vết nào của TimBus hoặc animation loop.
- **Kiểm tra:**
  - Quét toàn bộ repository: Không có socket kết nối cổng `9149`.
  - Không có file chứa XOR cipher hoặc binary packet decoding cho TimBus.
  - File `app.js` không chứa `requestAnimationFrame`, không chứa Hermite spline, không có dead reckoning extrapolate math.

### TC-02: Endpoint Danh mục Tuyến (`GET /api/routes`)
- **Đầu vào:** Gửi request HTTP `GET http://127.0.0.1:8000/api/routes`.
- **Kỳ vọng:**
  - Mã trạng thái: `200 OK`.
  - Content-Type: `application/json`.
  - Thân phản hồi: Danh sách ít nhất 10 tuyến xe buýt phổ biến của Hà Nội (bao gồm Tuyến `27`, `32`, `22`, `34`...), mỗi phần tử có đầy đủ 3 trường: `route_id`, `route_no`, `name`.

### TC-03: Endpoint Dữ liệu Xe Trực tiếp (`GET /api/live-vehicles`)
- **Đầu vào:** Gửi request HTTP `GET http://127.0.0.1:8000/api/live-vehicles?route_id=27&direction=0`.
- **Kỳ vọng:**
  - Mã trạng thái: `200 OK`.
  - Cấu trúc JSON có các khóa: `route_id` (27), `direction` (0), `count` (số nguyên $\ge 0$), `vehicles` (mảng).
  - Mọi xe trong danh sách `vehicles` phải có:
    - `id` là số nguyên dương.
    - `plate` là chuỗi không rỗng (ví dụ: `29B-...`).
    - `lat` nằm trong khoảng $[20.5, 21.5]$.
    - `lng` nằm trong khoảng $[105.5, 106.3]$.
    - `deg` là số thực trong khoảng $[0, 360]$.
    - `speed_kmh` là số thực $\ge 0$.
  - Không có 2 xe nào trùng `id` trong cùng một phản hồi.

### TC-04: Xử lý tham số hợp lệ cho Chiều (Direction)
- **Đầu vào:**
  - `direction=0` trả về dữ liệu hợp lệ chiều về.
  - `direction=1` trả về dữ liệu hợp lệ chiều đi.
  - `direction=99` xử lý an toàn (trả về HTTP 400 hoặc HTTP 422 hoặc danh sách rỗng, không crash server).

### TC-05: Giao diện Người dùng và Phục vụ Static Files
- **Đầu vào:** Gửi request HTTP `GET http://127.0.0.1:8000/`.
- **Kỳ vọng:**
  - Mã trạng thái: `200 OK`.
  - Phục vụ HTML chứa container `#map`, dropdown selector `#routeSelect`, và nạp Leaflet CDN.
  - Thời gian phản hồi trang $< 1.0$ giây.

### TC-06: Hoạt động Cập nhật Giật cục Rời rạc (Client Discrete Stepping)
- **Đầu vào:** Kiểm tra cấu trúc Javascript trong `app.js`.
- **Kỳ vọng:**
  - Có hàm định thời chu kỳ (`setInterval(..., 15000)` hoặc cấu hình tương tự trong khoảng 15s - 30s).
  - Vị trí xe được cập nhật trực tiếp qua API `marker.setLatLng()`.
  - Các xe không còn trong danh sách phản hồi mới được tự động gỡ bỏ khỏi bản đồ (`marker.remove()`).

---

## 7. KẾ HOẠCH BÀN GIAO THỰC THI (DELEGATION HANDOFF)

Sau khi tài liệu đặc tả này được ghi nhận:
1. **@orchestrator** tiếp nhận xác nhận hoàn thành từ `@architect`.
2. **@leaf_coder** nhận bàn giao để triển khai chính xác:
   - Viết `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/busmap_service.py`.
   - Viết `module_3_bus_eta_prediction/step_3_5_web_demo/app.py` và thư mục `static/` (`index.html`, `app.js`, `bus_icon.svg`).
3. **@blind_tester** viết kiểm thử tự động (pytest + Playwright/requests) đối chứng theo Mục 6 (DoD).
