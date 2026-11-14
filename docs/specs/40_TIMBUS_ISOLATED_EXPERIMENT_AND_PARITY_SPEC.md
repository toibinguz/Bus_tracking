# SPEC-40: Thí nghiệm Độc lập & Đánh giá Đối chứng Viễn trắc TimBus vs. BusMap trên Tuyến 32
## Isolated Empirical Experiment and Telemetry Parity Specification (Route 32)

- **Mã định danh:** `SPEC-40-TIMBUS-PARITY`
- **Đường dẫn lưu trữ:** `docs/specs/40_TIMBUS_ISOLATED_EXPERIMENT_AND_PARITY_SPEC.md`
- **Phiên bản:** 1.0.0
- **Trạng thái:** Approved Architecture Specification (Sẵn sàng triển khai bởi `@leaf_coder`, thẩm tra bởi `@whitebox_auditor`, nghiệm thu bởi `@blind_tester`)
- **Tác giả:** `@architect`
- **Tuân thủ quy tắc:** AGENTS.md (Nguyên tắc Cô lập Tuyệt đối, Evidence-First, Cấm viết code thực thi trong spec).

---

## 1. Mục tiêu và Nguyên tắc Cô lập Tuyệt đối (Executive Summary & Isolation Boundary)

### 1.1. Mục tiêu Thí nghiệm
Thực hiện một thí nghiệm thực địa độc lập và cô lập nhằm đánh giá nguồn dữ liệu GPS thời gian thực từ ứng dụng **Tìm Buýt (TimBus / BA GPS)**, đối chứng trực tiếp với nguồn dữ liệu hiện có từ **BusMap** trên **Tuyến 32 (Bến xe Giáp Bát - Nhổn)** ở cả hai chiều di chuyển (`go` và `re`).

Thí nghiệm được thiết kế nhằm trả lời dứt khoát 2 câu hỏi kỹ thuật cốt lõi:
1. **Câu hỏi 1 (Parity & Shadowing):** Số lượng xe buýt phát hiện được giữa BusMap và TimBus có khớp nhau không? Có xảy ra hiện tượng **Shadowing** (TimBus chỉ trả về 1 xe gần trạm nhất trên đoạn $X \to X+1$, che khuất $m-1$ xe khác nếu có nhiều xe cùng phân đoạn) hay không?
2. **Câu hỏi 2 (GPS Precision & Synchronization):** Xét tại cùng một thời điểm ghi nhận gói tin, tọa độ GPS và vận tốc giữa hai hệ thống có trùng khớp hoặc sai lệch ở mức dung sai cho phép ($\le 15\text{m} - 50\text{m}$) hay không?

---

### 1.2. Ranh giới Cô lập Tuyệt đối (Absolute Isolation Boundary)

Để đảm bảo tính toàn vẹn của hệ thống lõi và tuân thủ triệt để quy định chống nhiễm bẩn mã nguồn (Anti-Code Pollution):

```
+-----------------------------------------------------------------------------------------+
|                                    HỆ THỐNG LÕI (BẢO VỆ TUYỆT ĐỐI)                      |
|  module_1_* / module_2_* / module_3_* / config/ / data/lakehouse/ / data/models/       |
|  ==> NGHIÊM CẤM TẠO, SỬA ĐỔI HOẶC XÓA BẤT KỲ FILE NÀO TRONG CÁC THƯ MỤC NÀY            |
+-----------------------------------------------------------------------------------------+
                                        | (CHỈ ĐỌC / READ-ONLY)
                                        v
+-----------------------------------------------------------------------------------------+
|  CSDL CHUẨN: data/hanoi_bus_system.db                                                   |
|  - canonical_route_master (Tuyến 32)                                                    |
|  - canonical_station_master (Danh bạ 31 trạm chiều Đi, 33 trạm chiều Về)               |
|  - canonical_shape_master (Tim tuyến Frenet)                                            |
+-----------------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------------+
|                              VÙNG CÔ LẬP THÍ NGHIỆM: experiments/timbus/                |
|  - Mã nguồn thực thi: experiments/timbus/scripts/                                       |
|  - Dữ liệu thô thu thập: experiments/timbus/data/raw_{busmap,timbus}_captures/          |
|  - Dữ liệu đối chứng: experiments/timbus/data/parity_records.csv                        |
|  - Nhật ký chạy: experiments/timbus/logs/experiment_run.log                            |
|  - Báo cáo kết quả: experiments/timbus/TIMBUS_ROUTE32_EXPERIMENT_REPORT.md              |
|  ==> NẾU SAU THÍ NGHIỆM KHÔNG TÍCH HỢP, XÓA TOÀN BỘ experiments/timbus/ MÀ KHÔNG         |
|      ĐỂ LẠI BẤT KỲ DẤU VẾT HAY HỎNG HÓC NÀO TRONG TOÀN BỘ REPOSITORY                     |
+-----------------------------------------------------------------------------------------+
```

1. **Quyền Đọc duy nhất:** Thí nghiệm chỉ được phép mở kết nối `sqlite3` ở chế độ **READ-ONLY** (`mode=ro` hoặc `sqlite3.connect('file:...data/hanoi_bus_system.db?mode=ro', uri=True)`) tới `data/hanoi_bus_system.db`.
2. **Khu vực Ghi độc quyền:** Mọi file mã nguồn mới, file cấu hình, dữ liệu thô (.json, .csv), file đồ thị, file log và báo cáo bắt buộc phải nằm 100% bên trong `experiments/timbus/`.
3. **Tính độc lập khi Dọn dẹp (Zero Residue):** Nếu người dùng hoặc kiến trúc sư quyết định loại bỏ kết quả, lệnh `Remove-Item -Recurse -Force experiments/timbus/` sẽ đưa toàn bộ codebase về trạng thái sạch sẽ tuyệt đối.

---

## 2. Quy cách Giao thức Mạng và Hợp đồng Dữ liệu (API Contracts)

### 2.1. Kiểm tra Tính đúng đắn của Tài liệu (Document Correctness Verification Step)
Trước khi khởi chạy đợt thu thập dữ liệu lớn 10 phút, kịch bản phải thực hiện **1 request kiểm chuẩn (Sanity Probe)** để xác nhận server TimBus đang trực tuyến và giải mã thành công:
- **Trạm kiểm chuẩn:** Trạm ID `157` (`ĐD Đại học Bách Khoa HN - Giải phóng`, trạm thứ 25 chiều `go` của Tuyến 32).
- **Tiêu chí phản hồi hợp lệ:**
  * HTTP Status: `200 OK`.
  * Chuỗi Base64 trả về có độ dài $> 67$ bytes.
  * Checksum Modulo 256 khớp $100\%$.
  * Giải mã XOR đối xứng với $\text{Key}_1$ trích xuất từ gói tin thành công.
  * Phân giải nhị phân trả về ít nhất 1 đối tượng xe buýt có tọa độ hợp lệ trong khu vực Hà Nội: $\text{Lat} \in [20.8, 21.3]^\circ\text{N}$, $\text{Lon} \in [105.6, 106.0]^\circ\text{E}$.

---

### 2.2. Hợp đồng TimBus API (Station Fleet Query Protocol)

- **Gateway URL:** `http://www.timbus.vn:9149/SearchBuyt/VehicleState`
- **Phương thức:** `HTTP GET`
- **Tham số URL:** `ReqParams` (Chuỗi Base64 đại diện cho frame mã hóa)
- **Headers:**
  ```http
  User-Agent: Dalvik/2.1.0 (Linux; U; Android 14; Pixel Build/UP1A.231005.007)
  Connection: Keep-Alive
  Accept-Encoding: gzip
  ```

#### Cấu trúc Đóng gói Frame Nhị phân (Binary Frame Specification)
Frame trước khi mã hóa Base64 gồm:
$$\text{Frame} = \big[ \text{Encrypted Body} \big] + \big[ \text{Key}_1 (32\text{B}) \big] + \big[ \text{len}(\text{Key}_1) (1\text{B}) \big] + \big[ \text{Key}_2 (64\text{B}) \big] + \big[ \text{len}(\text{Key}_2) (1\text{B}) \big] + \big[ \text{Checksum} (1\text{B}) \big]$$

1. **Request Body nguyên bản:**
   - `Client ID`: 4 bytes Little-Endian unsigned integer (`0x001b02f5`).
   - `Station ID`: 4 bytes Little-Endian unsigned integer.
   - `Route Parameter`: 2 bytes Little-Endian uint16 (độ dài chuỗi) + chuỗi ký tự UTF-8 mã tuyến (ví dụ: `"32"`).
   - `Vehicle Parameter`: 2 bytes Little-Endian uint16 (`0x0000` = chuỗi rỗng khi query trạm).
   - `Direction`: 1 byte uint8 (`0`: Chiều đi / `go`, `1`: Chiều về / `re`).
2. **Mã hóa:** XOR đối xứng với $\text{Key}_1$ gồm 32 ký tự ngẫu nhiên trong khoảng ASCII printable $[48, 127]$.
3. **Checksum kiểm toàn:** 1 byte cuối cùng bằng $\left( \sum_{k=0}^{M-1} \text{Byte}[k] \right) \pmod{256}$.
4. **Phân giải Response Body (sau giải mã Base64 và XOR):**
   - Byte 0: `Count` (Số lượng xe buýt $N$ trong gói tin).
   - Tiếp theo là $N$ khối dữ liệu liên tiếp, mỗi khối có các trường:
     * `Plate Len` (1B) + `Plate String` ($L_P$ Bytes) (ví dụ: `"29F05268"`)
     * `Route Len` (1B) + `Route String` ($L_R$ Bytes) (ví dụ: `"32"`)
     * `Next Station ID` (4B LE int32)
     * `Distance to Next Station` (4B LE int32, đơn vị: mét)
     * `Station Name Len` (2B LE uint16) + `Station Name String` ($L_S$ Bytes UTF-8)
     * `Speed` (1B uint8, đơn vị: km/h)
     * `Latitude` (4B Float32 Little-Endian IEEE-754)
     * `Longitude` (4B Float32 Little-Endian IEEE-754)
     * `Status` (1B uint8)
     * `Direction` (1B uint8, `0`: Đi, `1`: Về)

---

### 2.3. Hợp đồng BusMap API (Route-Level Broadcast Protocol)

- **Gateway URL:** `https://api.busmap.city/v2/public/busmap/route_bus_gps`
- **Phương thức:** `HTTP GET`
- **Tham số URL:**
  * `regionCode`: `"hn"`
  * `routeId`: `32`
  * `direction`: `0` (Chiều đi) hoặc `1` (Chiều về)
- **Cơ chế xác thực (Auth Headers):**
  * `epoch`: Timestamp thời gian thực theo milliseconds (chuỗi số).
  * `proof`: Giá trị MD5 hash của chuỗi `f"{epoch}:Bus2019M@p_"`.
  * `package-name`: `"com.t7.busmaphn"`
  * `client-version`: `"android|20600"`
  * `device-id`: `"3f8b1c4a9d2e5f70"`
  * `User-Agent`: `"okhttp/4.9.2"`
- **Response Format:** JSON Array chứa toàn bộ các xe đang vận hành trên tuyến trong 1 request duy nhất:
  ```json
  [
    {
      "Id": 1408515,
      "VehicleNumber": "29F-052.45",
      "RouteId": 32,
      "Lat": 21.035397,
      "Lng": 105.792618,
      "Deg": 108.95,
      "Speed": 0,
      "lastUpdateTime": "2026-11-12T10:33:39+07:00",
      "currentStationId": 4841,
      "nextStationId": 58
    }
  ]
  ```

---

## 3. Không gian Tuyến 32, Chiếu Frenet 1D và Bộ Lọc Vùng Bến (Spatial Architecture)

### 3.1. Cấu trúc Danh bạ Trạm Tuyến 32 (Từ `canonical_station_master`)

Tuyến 32 có lộ trình kết nối giữa 2 đầu bến: **Bến xe Giáp Bát** và **Nhổn (Đại học Công nghiệp Hà Nội)**.

| Hướng tuyến | Mã hướng | Số trạm ($N$) | Trạm đầu bến (Order 0) | Trạm thứ 2 (Order 1) | Trạm kế cuối (Order $N-2$) | Trạm cuối bến (Order $N-1$) | Chiều dài tim tuyến ($L$) |
| :---: | :---: | :---: | :--- | :--- | :--- | :--- | :---: |
| **Chiều Đi** | `go` (`0`) | **31 trạm** | `(B) Nhổn` (ID: 1778, $s = 0.0\text{m}$) | `Điểm trung chuyển Nhổn` (ID: 1043, $s = 137.8\text{m}$) | `Đối diện 807 Giải Phóng` (ID: 161, $s = 16,764.4\text{m}$) | `(A) BX Giáp Bát` (ID: 1676, $s = 17,983.6\text{m}$) | **17,983.6 m** |
| **Chiều Về** | `re` (`1`) | **33 trạm** | `(A) BX Giáp Bát` (ID: 1676, $s = 0.0\text{m}$) | `Toyota Giải Phóng` (ID: 166, $s = 635.8\text{m}$) | `Đình và Miếu Đồng Cổ` (ID: 1053, $s = 18,751.1\text{m}$) | `(B) Nhổn` (ID: 1778, $s = 19,402.6\text{m}$) | **19,402.6 m** |

---

### 3.2. Thuật toán Chiếu Trực giao Frenet 1D (Frenet 1D Projection Model)

Tim tuyến chuẩn gồm chuỗi điểm tọa độ $\mathcal{P} = \{(\text{lat}_j, \text{lon}_j, s_j)\}_{j=0}^M$ lấy từ bảng `canonical_shape_master` với `route_code = '32'`.

1. **Chuyển đổi Hệ tọa độ Phẳng Cục bộ (Local Cartesian Coordinates):**
   Với vĩ độ trung bình $\bar{\phi} = \frac{1}{M+1}\sum_{j=0}^M \text{lat}_j$:
   $$k_x = \frac{\pi}{180} R \cos(\bar{\phi}), \quad k_y = \frac{\pi}{180} R$$
   trong đó $R = 6,378,137\text{ m}$ (Bán kính Trái Đất WGS-84).
2. **Chiếu Trực giao Điểm GPS $P(\text{lat}, \text{lon})$ lên từng Đoạn tim đường $[A_j, B_j]$:**
   Đặt vector đoạn $\vec{u}_j = (x_{B_j} - x_{A_j}, y_{B_j} - y_{A_j})$ và vector khoảng cách $\vec{w}_j = (x_P - x_{A_j}, y_P - y_{A_j})$.
   Hệ số chiếu dọc $\alpha_j$:
   $$\alpha_j = \frac{\vec{w}_j \cdot \vec{u}_j}{\|\vec{u}_j\|^2} = \frac{(x_P - x_{A_j})\Delta x_j + (y_P - y_{A_j})\Delta y_j}{\Delta x_j^2 + \Delta y_j^2}$$
   Hạn định trên đoạn hữu hạn: $\hat{\alpha}_j = \max(0.0, \min(1.0, \alpha_j))$.
3. **Khoảng cách dọc $s$ và Khoảng cách ngang $d$ (Along-track & Cross-track):**
   - Điểm hình chiếu: $H_j = A_j + \hat{\alpha}_j \vec{u}_j$.
   - Khoảng cách sai lệch tim đường: $d_j = \|P - H_j\|_2$.
   - Đoạn tối ưu $j^* = \arg\min_j d_j$.
   - Tọa độ Frenet kết quả:
     $$s_{\text{frenet}} = s_{A_{j^*}} + \hat{\alpha}_{j^*} \|\vec{u}_{j^*}\|_2$$
     $$d_{\text{cross}} = d_{j^*}$$
4. **Bộ lọc Trôi dạt Ngoại lai (Cross-track Tolerance):**
   Loại bỏ mọi xe có khoảng cách vuông góc ra khỏi tim đường vượt quá ngưỡng cho phép:
   $$d_{\text{cross}} \le 50.0\text{ m}$$

---

### 3.3. Quy tắc Lọc Bỏ Vùng Bến (Terminal Boundary Filtering)

Theo yêu cầu nghiêm ngặt của người dùng nhằm loại bỏ các xe đang dừng đỗ, nghỉ chuyển ca, hoặc quay đầu tại bến đầu và bến cuối, hệ thống xác lập dải hành lang di chuyển tích cực (Active Corridor):

#### Công thức Xác định Vùng Hành lang Hợp lệ:
Với mỗi chiều di chuyển, xác định 2 ngưỡng khoảng cách Frenet biên:
- **Ngưỡng biên đầu ($s_{\text{start\_cutoff}}$):** Khoảng cách tích lũy tại **Trạm thứ 2** (Station Order 1 trong `canonical_station_master`).
- **Ngưỡng biên cuối ($s_{\text{end\_cutoff}}$):** Khoảng cách tích lũy tại **Trạm kế cuối** (Station Order $N-2$ trong `canonical_station_master`).

#### Bảng Ngưỡng Cắt Biên Chi tiết cho Tuyến 32:

| Chiều | Ngưỡng Cắt Đầu Bến ($s_{\text{start\_cutoff}}$) | Ngưỡng Cắt Cuối Bến ($s_{\text{end\_cutoff}}$) | Dải Khoảng cách Xe Hoạt động Hợp lệ |
| :---: | :---: | :---: | :---: |
| **Chiều Đi (`go`)** | **$137.8\text{ m}$** (Trạm Order 1: `Điểm trung chuyển Nhổn`) | **$16,764.4\text{ m}$** (Trạm Order 29: `Đối diện 807 Giải Phóng`) | $137.8\text{ m} \le s_{\text{bus}} \le 16,764.4\text{ m}$ |
| **Chiều Về (`re`)** | **$635.8\text{ m}$** (Trạm Order 1: `Toyota Giải Phóng`) | **$18,751.1\text{ m}$** (Trạm Order 31: `Đình và Miếu Đồng Cổ`) | $635.8\text{ m} \le s_{\text{bus}} \le 18,751.1\text{ m}$ |

#### Phân loại Trạng thái Phương tiện:
- Nếu $s_{\text{bus}} < s_{\text{start\_cutoff}}$: Gán nhãn `DEPOT_ORIGIN_ZONE` (Khu vực bến xuất phát - Loại bỏ).
- Nếu $s_{\text{bus}} > s_{\text{end\_cutoff}}$: Gán nhãn `DEPOT_DEST_ZONE` (Khu vực bến cập đích - Loại bỏ).
- Nếu $s_{\text{start\_cutoff}} \le s_{\text{bus}} \le s_{\text{end\_cutoff}}$: Gán nhãn `ACTIVE_IN_TRANSIT` (**Xe đang trên hành trình thực sự - Chấp nhận đưa vào tập đánh giá đối chứng**).

---

## 4. Mô hình Toán học Kiểm định Giả thuyết (Dual Hypothesis Formalization)

### 4.1. Chuẩn hóa Biển số Phương tiện (Vehicle License Plate Normalization)
Để đối chiếu chính xác giữa hai nguồn:
- BusMap trả về định dạng có dấu gạch ngang và chấm: `"29F-052.68"`.
- TimBus trả về định dạng viết liền: `"29F05268"`.
Hàm chuẩn hóa chuỗi biển số:
$$\text{norm\_plate}(p) = \text{regex\_replace}(p, \text{"[^A-Z0-9]"}, \text{""})$$
Ví dụ: $\text{norm\_plate}(\text{"29F-052.68"}) = \text{norm\_plate}(\text{"29F05268"}) = \text{"29F05268"}$.

---

### 4.2. Kiểm định Giả thuyết 1: Parity Số lượng Xe & Hiện tượng Shadowing

Gọi $\mathcal{V}_{\text{BM}}^{(t)}$ là tập hợp biển số các xe hoạt động trên hành lang tích cực được BusMap phát hiện tại vòng quét $t$.  
Gọi $\mathcal{V}_{\text{TB}}^{(t)}$ là tập hợp biển số các xe hoạt động trên hành lang tích cực được TimBus phát hiện sau khi quét qua tất cả các trạm tại vòng quét $t$.

#### 1. Chỉ số Khám phá Phương tiện (Fleet Discovery Metrics):
- **Tỷ lệ Phủ Phương tiện (Vehicle Recall Rate):**
  $$\text{Recall}_{\text{TB vs BM}}^{(t)} = \frac{|\mathcal{V}_{\text{TB}}^{(t)} \cap \mathcal{V}_{\text{BM}}^{(t)}|}{|\mathcal{V}_{\text{BM}}^{(t)}|} \times 100\%$$
- **Hao hụt Số lượng (Deficit Count):**
  $$\Delta_{\text{fleet}}^{(t)} = |\mathcal{V}_{\text{BM}}^{(t)}| - |\mathcal{V}_{\text{TB}}^{(t)}|$$

#### 2. Định nghĩa Toán học của Hiện tượng "Shadowing" (Che khuất Xe):
Giả sử trên phân đoạn giữa 2 trạm liên tiếp $[S_k, S_{k+1}]$ đang có $m \ge 2$ xe buýt $v_1, v_2, \dots, v_m$ cùng di chuyển về phía trạm $S_{k+1}$, sắp xếp theo khoảng cách tăng dần:
$$0 \le \text{dist}(v_1, S_{k+1}) < \text{dist}(v_2, S_{k+1}) \le \dots \le \text{dist}(v_m, S_{k+1})$$

- **Phát hiện Shadowing Cục bộ:**
  Nếu tại trạm $S_{k+1}$, phản hồi của TimBus **chỉ chứa duy nhất xe $v_1$** mà không chứa các xe $v_2, \dots, v_m$, đồng thời không có trạm nào khác phía sau trả về $v_2, \dots, v_m$ $\implies$ **Khẳng định xảy ra hiện tượng Shadowing tại phân đoạn $[S_k, S_{k+1}]$**.
- **Chỉ số Định lượng Shadowing toàn mạng:**
  $$\text{Shadowing Rate} = \frac{\sum_{t=1}^T \sum_{k=1}^{N-1} \mathbb{I}(\text{Shadowing Detected at } [S_k, S_{k+1}])}{\sum_{t=1}^T \sum_{k=1}^{N-1} \mathbb{I}(m_{k, k+1} \ge 2)} \times 100\%$$

---

### 4.3. Kiểm định Giả thuyết 2: Độ lệch Không gian GPS và Đồng bộ Thời gian

Với mỗi xe buýt $v \in \mathcal{V}_{\text{BM}} \cap \mathcal{V}_{\text{TB}}$ xuất hiện đồng thời trong cả 2 luồng trong cửa sổ thời gian gần nhau ($|\Delta \tau| \le 30\text{s}$), ta đo đạc:

#### 1. Khoảng cách Không gian Haversine Thực tế:
$$D_{\text{haversine}}(P_{\text{BM}}, P_{\text{TB}}) = 2R \arcsin \sqrt{ \sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_{\text{BM}})\cos(\phi_{\text{TB}})\sin^2\left(\frac{\Delta \lambda}{2}\right) }$$
trong đó $\Delta \phi = \text{lat}_{\text{BM}} - \text{lat}_{\text{TB}}$, $\Delta \lambda = \text{lon}_{\text{BM}} - \text{lon}_{\text{TB}}$.

#### 2. Độ lệch Dọc Hành lang Frenet ($\Delta s$):
$$\Delta s_v = s_{\text{BM}, v} - s_{\text{TB}, v} \quad (\text{đơn vị: mét})$$

#### 3. Độ lệch Ngang Hành lang Frenet ($\Delta d$):
$$\Delta d_v = d_{\text{BM}, v} - d_{\text{TB}, v} \quad (\text{đơn vị: mét})$$

#### 4. Phân loại Mức độ Khớp GPS:
- **Khớp Hoàn hảo (Collocated / Sub-cycle match):** $D_{\text{haversine}} \le 15.0\text{ m}$. (Tương đương độ dịch chuyển của xe trong khoảng $1 - 2$ giây ở tốc độ đô thị).
- **Khớp Đồng bộ Chấp nhận được (Acceptable Polling Lag):** $15.0\text{ m} < D_{\text{haversine}} \le 50.0\text{ m}$. (Giải thích được do chênh lệch chu kỳ request giữa 2 luồng polling).
- **Lệch Lớn / Bất thường (Spatial Divergence):** $D_{\text{haversine}} > 50.0\text{ m}$. (Cần lưu vết chi tiết để kiểm toán nguyên nhân: xe rẽ tránh đường, server giữ cache cũ, hay sai số phần cứng hộp đen).

---

## 5. Quy trình Thu thập Thực nghiệm 10 Phút (10-Minute Polling Pipeline)

### 5.1. Kế hoạch Lấy mẫu Thời gian (Sampling & Scheduling Plan)

Thí nghiệm được thực hiện liên tục trong khoảng thời gian tối thiểu **10 phút (600 giây)** trong khung giờ xe buýt vận hành thực tế (06:00 - 21:00).

```
[Khởi động 10-Phút Thí nghiệm]
  |
  +---> LUỒNG 1: BusMap Route Query (Chạy lặp mỗi 10 giây)
  |       - Query Direction 0 (go) -> Nhận danh sách toàn tuyến -> Ghi raw capture
  |       - Query Direction 1 (re) -> Nhận danh sách toàn tuyến -> Ghi raw capture
  |       - Nghỉ 10 giây -> Lặp lại (Tổng cộng ~60 vòng)
  |
  +---> LUỒNG 2: TimBus Station Sweep Query (Chạy lặp mỗi 15-20 giây)
  |       - Duyệt tuần tự 31 trạm chiều go (delay 50ms giữa các trạm)
  |       - Duyệt tuần tự 33 trạm chiều re (delay 50ms giữa các trạm)
  |       - Hợp nhất thành danh sách xe duy nhất của vòng quét -> Ghi raw capture
  |       - Nghỉ 15 giây -> Lặp lại (Tổng cộng ~30 - 40 vòng)
  |
  +---> BỘ KẾT HỢP ĐỐI CHỨNG (Realtime Alignment Engine)
          - Chiếu Frenet 1D lên tim đường Tuyến 32
          - Áp dụng bộ lọc bến: Loại bỏ vùng [1 -> 2] và [N-1 -> N]
          - Đối chiếu biển số: Tính D_haversine, Delta_s, Shadowing
          - Ghi kết quả vào experiments/timbus/data/parity_records.csv
```

### 5.2. Chống Tắc nghẽn Mạng và Tôn trọng Server (Rate-Limiting & Politeness)
- Để tránh quá tải server TimBus (`www.timbus.vn:9149`), giữa mỗi request trạm liên tiếp phải chèn thời gian chờ tối thiểu $\Delta t_{\text{inter-station}} \ge 50\text{ms}$.
- Sử dụng cơ chế kết nối `Keep-Alive` (`urllib.request` hoặc `requests.Session`) nhằm tái sử dụng socket TCP, tránh cạn kiệt cổng (TCP port exhaustion) trên hệ điều hành Windows.

---

## 6. Cấu trúc File và Thư mục Thực nghiệm (Isolated Artifact Layout)

Toàn bộ các file phát sinh phải được đặt chính xác trong thư mục `experiments/timbus/`:

```text
z:\Desktop\Bus_tracking\experiments\timbus\
├── scripts\
│   ├── run_route32_parity_experiment.py     # Script thu thập đồng thời 10 phút & phân tích đối chứng
│   └── verify_timbus_sanity_probe.py        # Script kiểm chuẩn 1 request ban đầu theo Mục 2.1
├── data\
│   ├── raw_busmap_captures\                 # File JSON thô từng tick của BusMap (timestamped)
│   │   └── busmap_tick_20261112_*.json
│   ├── raw_timbus_captures\                 # File JSON/bytes thô từng sweep của TimBus (timestamped)
│   │   └── timbus_sweep_20261112_*.json
│   ├── parity_records.csv                   # Bảng chi tiết từng cặp xe đối chứng (GPS, Haversine, Frenet)
│   └── shadowing_events.csv                 # Bảng ghi nhận các sự kiện Shadowing phát hiện được
├── logs\
│   ├── experiment_run.log                   # Log thực thi đầy đủ
│   └── error.log                            # Log lỗi kết nối mạng (nếu có)
├── TIMBUS_ROUTE32_EXPERIMENT_REPORT.md      # Báo cáo tổng hợp số liệu khoa học và kết luận
└── [Các file báo cáo nghiên cứu trước đây giữ nguyên]
```

---

## 7. Cấu trúc Bảng Dữ liệu Đầu ra (Output Data Schemas)

### Bảng 1: Chi tiết Đối chứng Viễn trắc (`parity_records.csv`)

| Tên cột | Kiểu dữ liệu | Diễn giải |
| :--- | :---: | :--- |
| `timestamp` | ISO-8601 String | Thời điểm ghi nhận đối chứng |
| `direction` | String (`go` / `re`) | Chiều di chuyển của tuyến |
| `plate_normalized` | String | Biển số xe chuẩn hóa (ví dụ: `29F05268`) |
| `in_active_corridor` | Boolean (`True` / `False`) | Xe có nằm trong hành lang hợp lệ (đã lọc bến) không |
| `bm_lat` | Float64 | Vĩ độ do BusMap báo cáo |
| `bm_lng` | Float64 | Kinh độ do BusMap báo cáo |
| `bm_speed` | Int | Vận tốc BusMap báo cáo (km/h) |
| `bm_frenet_s` | Float64 | Khoảng cách Frenet dọc tim tuyến của BusMap (m) |
| `bm_cross_track_d` | Float64 | Khoảng cách vuông góc tim tuyến của BusMap (m) |
| `tb_lat` | Float64 | Vĩ độ do TimBus báo cáo (hoặc `NaN` nếu TimBus không thấy) |
| `tb_lng` | Float64 | Kinh độ do TimBus báo cáo (hoặc `NaN` nếu TimBus không thấy) |
| `tb_speed` | Int | Vận tốc TimBus báo cáo (km/h) |
| `tb_frenet_s` | Float64 | Khoảng cách Frenet dọc tim tuyến của TimBus (m) |
| `tb_cross_track_d` | Float64 | Khoảng cách vuông góc tim tuyến của TimBus (m) |
| `haversine_dist_m` | Float64 | Khoảng cách không gian giữa 2 tọa độ (m) |
| `delta_frenet_s_m` | Float64 | Chênh lệch khoảng cách dọc: $s_{\text{BM}} - s_{\text{TB}}$ (m) |
| `status_match` | String | `EXCELLENT` ($\le 15\text{m}$), `ACCEPTABLE` ($\le 50\text{m}$), `DIVERGENT` ($>50\text{m}$), `TIMBUS_MISSING` |

---

### Bảng 2: Sự kiện Shadowing (`shadowing_events.csv`)

| Tên cột | Kiểu dữ liệu | Diễn giải |
| :--- | :---: | :--- |
| `timestamp` | ISO-8601 String | Thời điểm phát hiện |
| `direction` | String (`go` / `re`) | Hướng tuyến |
| `from_station_id` | Int | ID trạm đầu phân đoạn |
| `to_station_id` | Int | ID trạm cuối phân đoạn (trạm đang query) |
| `busmap_vehicles` | String | Danh sách biển số BusMap nhìn thấy trên phân đoạn |
| `timbus_vehicles` | String | Danh sách biển số TimBus trả về |
| `shadowed_vehicles` | String | Biển số các xe bị che khuất (BusMap thấy, TimBus không trả về) |
| `is_shadowing_confirmed` | Boolean | `True` nếu có ít nhất 1 xe phía sau bị che |

---

## 8. Tiêu chí Nghiệm thu Đo kiểm (Verifiable Acceptance Criteria)

### 8.1. Trách nhiệm của `@leaf_coder`
1. **Tuân thủ Tuyệt đối Ranh giới Cô lập:**
   - Chỉ tạo mã nguồn và file mới trong `experiments/timbus/`.
   - Kết nối `data/hanoi_bus_system.db` ở chế độ chỉ đọc.
   - Không được chạm vào bất kỳ file nào trong `module_*`, `config/`, `data/lakehouse/`, `docs/evidence/`.
2. **Hiện thực hóa Đầy đủ 2 Bước Thực nghiệm:**
   - Bước 1: Kịch bản Sanity Probe (`verify_timbus_sanity_probe.py`) phải chạy thành công và in ra ít nhất 1 xe hợp lệ trước khi vào bước 2.
   - Bước 2: Kịch bản Polling 10 phút (`run_route32_parity_experiment.py`) chạy đồng thời cả 2 luồng, ghi log đầy đủ và tự động xuất các file CSV và Báo cáo Markdown.
3. **Thực thi Đúng Thuật toán và Bộ Lọc:**
   - Thực hiện đúng công thức chiếu Frenet 1D lên bảng `canonical_shape_master` Tuyến 32.
   - Lọc bỏ triệt để các xe rơi vào vùng đầu bến ($s < 137.8\text{m}$ với `go`, $s < 635.8\text{m}$ với `re`) và cuối bến ($s > 16,764.4\text{m}$ với `go`, $s > 18,751.1\text{m}$ với `re`).

---

### 8.2. Trách nhiệm của `@whitebox_auditor`
1. **Kiểm tra Ranh giới Filesystem (Git Status Audit):**
   - Chạy `git status --porcelain` để xác nhận $100\%$ file thay đổi/tạo mới chỉ nằm trong `experiments/timbus/` và file đặc tả `docs/specs/40_TIMBUS_ISOLATED_EXPERIMENT_AND_PARITY_SPEC.md`. Nếu phát hiện bất kỳ file nào bị sửa đổi trong `config/`, `module_*` hay `data/`, đánh trượt (FAIL) ngay lập tức.
2. **Kiểm tra Tính Độc lập và Magic Numbers:**
   - Xác nhận thuật toán Frenet và tọa độ trạm được nạp động từ CSDL SQLite, không hard-code tọa độ thủ công.
   - Kiểm tra việc xử lý biệt lệ mạng (Timeout, HTTP Retry, Checksum error) được bọc trong try-except an toàn, không làm crash luồng polling 10 phút.

---

### 8.3. Trách nhiệm của `@blind_tester`
Viết bộ kiểm tra độc lập trong `experiments/timbus/tests/test_timbus_parity_results.py` (hoặc kiểm tra trực tiếp artifact đầu ra mà **không đọc code của Leaf Coder**):
1. **Kiểm tra Artifact Tồn tại:**
   - Xác nhận sự tồn tại của `parity_records.csv`, `shadowing_events.csv`, và `TIMBUS_ROUTE32_EXPERIMENT_REPORT.md`.
2. **Kiểm tra Độ lớn Mẫu Thu thập:**
   - Xác nhận file log ghi nhận thời gian chạy thực nghiệm kéo dài tối thiểu 500 giây ($\approx 10$ phút).
   - Tổng số bản ghi quan sát trong `parity_records.csv` phải $> 100$ bản ghi.
3. **Kiểm chứng Kết luận Khoa học:**
   - Xác nhận báo cáo đưa ra câu trả lời định lượng rõ ràng cho cả 2 câu hỏi:
     * Có hay không có Shadowing? Tỷ lệ phát hiện xe của TimBus so với BusMap là bao nhiêu %?
     * Độ lệch GPS trung vị ($\text{Median } D_{\text{haversine}}$) giữa 2 bên đối với các xe trùng nhau là bao nhiêu mét? Có nhỏ hơn $50\text{m}$ không?

---

## 9. Hướng dẫn Bàn giao (Handover Note)

Đặc tả này là văn bản hiệu lực cao nhất định nghĩa phạm vi, ranh giới và phương pháp luận cho Thí nghiệm Độc lập TimBus Tuyến 32.
- Giai đoạn kế tiếp: Điều phối `@leaf_coder` tiến hành viết mã thực nghiệm trong `experiments/timbus/`.
- `@whitebox_auditor` và `@blind_tester` chuẩn bị sẵn checklist kiểm định độc lập đối chiếu trực tiếp theo Mục 8.
