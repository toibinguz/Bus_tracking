# SPEC-08: ĐẶC TẢ KIẾN TRÚC & MÔ HÌNH TOÁN HỌC - TÍCH HỢP DỰ BÁO ETA ĐẾN TRẠM DỪNG LÊN BẢN ĐỒ VỆ TINH ESRI
> **Verification note (2026-11-10):** The product contract remains applicable. The current endpoint is implemented in `step_3_5_web_demo/app.py` (around line 165); the referenced black-box test is a pending deliverable, not passing evidence.
## Document ID: `08_STATION_ETA_MAP_INTEGRATION_SPEC`

- **Tác giả:** `@architect`
- **Người thẩm định:** `@orchestrator`
- **Người thực thi triển khai:** `@leaf_coder`
- **Người nghiệm thu độc lập:** `@blind_tester`
- **Ngày ban hành:** 2026-11-09
- **Trạng thái:** APPROVED / READY FOR IMPLEMENTATION
- **Căn cứ pháp lý & kỹ thuật:**
  - `AGENTS.md` (Simplicity First - Minimum code, zero dead code, surgical changes)
  - `docs/specs/04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md` (SPEC-04: Kiến trúc Giật cục Rời rạc Thuần BusMap)
  - `docs/specs/05_ROUTE_SHAPE_AND_STATION_INTERACTIONS_SPEC.md` (SPEC-05: Tim tuyến và Trạm dừng đánh số trên nền Esri)
  - `docs/specs/06_CLEANUP_SCRIPTS_AND_EXPERIMENTS_AUDIT.md` (SPEC-06: Tinh giản scripts)
  - `docs/specs/07_TECHNICAL_DEBT_LEDGER_PARITY_AUDIT.md` (SPEC-07: Chuẩn hóa sổ cái nợ kỹ thuật)

---

## 1. TỔNG QUAN KIẾN TRÚC & NGUYÊN TẮC THIẾT KẾ (ARCHITECTURE OVERVIEW)

### 1.1. Mục tiêu cốt lõi
Trong hệ thống theo dõi xe buýt Hà Nội, giá trị thiết thực nhất đối với hành khách chờ xe tại trạm dừng không phải là việc nhìn xe trượt liên tục 60 FPS (vốn sinh ra ảo giác và hao pin), mà là câu trả lời tin cậy cho câu hỏi:
> **"Còn bao nhiêu phút nữa thì xe buýt kế tiếp sẽ tới trạm dừng này, và tôi nên có mặt lúc mấy giờ để tuyệt đối không bị lỡ xe?"**

Hệ thống cần cung cấp tính năng **Dự báo ETA Thời gian Thực đến Trạm Dừng (Station ETA)** được tích hợp trực tiếp vào giao diện bản đồ ảnh vệ tinh **Esri World Imagery** và thanh điều khiển bên hông (Sidebar), tuân thủ triệt để triết lý **Simplicity First**:
1. **Dữ liệu viễn trắc xe trực tiếp:** 100% sử dụng vị trí xe rời rạc từ API BusMap HTTPS (`fetch_route_buses_live`), chu kỳ 15 giây. Tuyệt đối 0% TimBus, 0% TCP socket, 0% XOR cipher.
2. **Hình học không gian chuẩn xác:** Tọa độ tim tuyến (`canonical_shape_master`) và danh mục trạm dừng (`canonical_station_master`) đã được vector hóa và gióng vuông góc trên mặt phẳng cục bộ WGS84, có sẵn lý trình tích lũy mét $s$ và số thứ tự trạm `station_order`.
3. **Mô hình thời gian di chuyển tin cậy:** Ma trận Baseline $P_{50}$ lịch sử từ bảng `agg_segment_travel_times` (169.830 ô dữ liệu sạch), phân tách theo loại ngày (`day_type`: Ngày thường / Thứ 7 / Chủ Nhật) và khung giờ (`hour_slot`: 5h - 21h), cung cấp đầy đủ bộ phân vị $[P_{10}, P_{50}, P_{90}]$ để thiết lập **Cửa sổ an toàn bất đối xứng**.

```
+-------------------------------------------------------------------------------+
|                      NGUỒN DỮ LIỆU ĐỘC NHẤT (SIMPLICITY FIRST)                |
|                                                                               |
|  +--------------------+   +-----------------------+   +--------------------+  |
|  | Live Bus Telemetry |   | Canonical Stations    |   | Baseline P50 Matrix|  |
|  | (BusMap API 15s)   |   | (canonical_station)   |   | (agg_segment_tt)   |  |
|  | lat, lon, speed    |   | s_cum_m, station_ord  |   | P10, P50, P90      |  |
|  +---------+----------+   +-----------+-----------+   +---------+----------+  |
|            |                          |                         |             |
+------------|--------------------------|-------------------------|-------------+
             |                          |                         |
             v                          v                         v
+-------------------------------------------------------------------------------+
|                  BỘ ĐIỀU ĐỘ TÍNH TOÁN ETA (ETA INFERENCE SERVICE)              |
|                                                                               |
|   1. Lọc xe cùng chiều phía sau trạm đích: s_bus < s_target - 10m             |
|   2. Chiếu 1D Frenet tìm đoạn trạm hiện tại [k, k+1]                          |
|   3. Tính thời gian dư đoạn hiện tại: Residual = (s_{k+1} - s_bus)/L_k * P50  |
|   4. Cộng dồn ma trận Baseline phân vị: ETA_P50 = Residual + Sum(P50)         |
|   5. Thiết lập Cửa sổ An toàn Bất đối xứng: [P10, P90]                        |
+-------------------------------------------------------------------------------+
             |
             v
+-------------------------------------------------------------------------------+
|                   GIAO DIỆN NGƯỜI DÙNG TRỰC QUAN (WEB DEMO UX)                |
|                                                                               |
|  +-------------------------------------+   +-------------------------------+  |
|  | 1. Leaflet Popup trên Marker Trạm   |   | 2. Sidebar Station Focus Card |  |
|  | - Nhấp huy hiệu trạm (1..N)         |   | - Ghim trạm theo dõi          |  |
|  | - Danh sách xe sắp đến + Phút ETA   |   | - Tự động cập nhật nhịp 15s   |  |
|  | - Khuyến nghị giờ có mặt tại trạm   |   | - Thanh tiến độ trạm còn lại  |  |
|  +-------------------------------------+   +-------------------------------+  |
+-------------------------------------------------------------------------------+
```

---

## 2. MÔ HÌNH TOÁN HỌC DỰ BÁO ETA ĐẾN TRẠM (MATHEMATICAL MODEL)

### 2.1. Không gian Trạng thái & Định nghĩa Đại lượng

Xét một tuyến xe buýt $R$ chạy theo chiều $D \in \{0, 1\}$ ($0 = \text{'go' - Chiều đi}, 1 = \text{'re' - Chiều về}$):
- **Tim tuyến 1D Frenet:** Quỹ đạo đường đi được chuẩn hóa thành hàm độ dài cung $s \in [0, L]$, với $L$ là tổng chiều dài hành trình của tuyến (mét).
- **Danh mục Trạm dừng Chính tắc:** Chuỗi $N$ trạm dừng có thứ tự:
  $$\mathcal{S} = \{ S_0, S_1, S_2, \dots, S_{N-1} \}$$
  Mỗi trạm $S_i$ được đặc trưng bởi bộ ba:
  $$S_i = \left( \text{id}_i, \; \text{ord}_i = i, \; s_i \right)$$
  với tính chất đơn điệu ngặt theo chiều chuyển động:
  $$0 = s_0 < s_1 < s_2 < \dots < s_{N-1} = L$$
  Độ dài đoạn trạm giữa hai trạm liên tiếp là $L_i = s_{i+1} - s_i > 0$.

- **Trạm Đích được Người dùng Chọn:**
  Hành khách lựa chọn một trạm dừng mục tiêu $S_{\text{target}}$ tại thứ tự $\text{ord}_{\text{target}} \in [0, N-1]$ có tọa độ lý trình $s_{\text{target}}$.

- **Vị trí Đoàn xe Thời gian Thực:**
  Tại thời điểm truy vấn $t_{\text{now}}$, API BusMap trả về danh sách $M$ xe buýt đang hoạt động trên tuyến $R$ và chiều $D$:
  $$\mathcal{V} = \{ V_1, V_2, \dots, V_M \}$$
  Mỗi xe $V_j$ có tọa độ WGS84 $(lat_j, lon_j)$, vận tốc đo $v_j$ (km/h), góc quay $\text{deg}_j$ và biển số $\text{plate}_j$.

---

### 2.2. Phép chiếu 1D Frenet & Phân định Vị trí Xe

1. **Chiếu vuông góc lên Tim Tuyến:**
   Tọa độ WGS84 $(lat_j, lon_j)$ của xe $V_j$ được chiếu trực giao lên tim tuyến $\mathcal{C}_{R, D}$ trên mặt phẳng tiếp diện cục bộ:
   $$s_{\text{bus}, j} = \Pi_{\mathcal{C}}(lat_j, lon_j) \in [0, L]$$
   $$d_{\perp, j} = \text{Dist}_{\perp}(lat_j, lon_j, \mathcal{C}) \ge 0$$

2. **Lọc Hành lang An toàn (Corridor Hygiene):**
   - Nếu $d_{\perp, j} > 35.0\text{ m}$: Xe bị lệch hành lang lộ trình quá lớn (xe đi vòng đường tránh detour, hoặc đang đỗ trong khuôn viên bãi sâu). Đánh dấu trạng thái `DETOUR` và loại khỏi danh sách xe tiếp cận chuẩn.
   - Nếu $d_{\perp, j} \le 35.0\text{ m}$: Xe đang bám sát tim đường chính tắc.

3. **Điều kiện Tiếp cận Hợp lệ (Incoming Eligibility Criterion):**
   Xe $V_j$ chỉ được coi là "đang chạy đến trạm $S_{\text{target}}$" khi và chỉ khi xe đang ở **phía sau trạm đích** theo đúng chiều di chuyển:
   $$s_{\text{bus}, j} < s_{\text{target}} - \Delta s_{\text{deadband}}$$
   với vùng đệm khử nhiễu $\Delta s_{\text{deadband}} = 10.0\text{ m}$.
   - Nếu $s_{\text{bus}, j} \ge s_{\text{target}} - 10.0\text{ m}$: Xe đã đi qua trạm $S_{\text{target}}$ hoặc đang cập bến xuất phát sau trạm đó $\to$ Bị loại khỏi danh sách dự báo cho trạm này.
   - Khoảng cách còn lại theo lý trình:
     $$\Delta s_j = s_{\text{target}} - s_{\text{bus}, j} > 0$$

4. **Xác định Đoạn trạm Hiện tại $[k, k+1]$:**
   Tìm chỉ số trạm $k \in [0, N-2]$ thỏa mãn:
   $$s_k \le s_{\text{bus}, j} < s_{k+1}$$
   - $S_k$ là trạm dừng gần nhất mà xe vừa vượt qua.
   - $S_{k+1}$ là trạm dừng vật lý tiếp theo ngay trước đầu xe ($k+1 \le \text{ord}_{\text{target}}$).
   - Số trạm dừng còn lại xe cần vượt qua để tới trạm đích:
     $$\text{stops\_remaining}_j = \text{ord}_{\text{target}} - k$$

---

### 2.3. Thuật toán Tính toán Thời gian Di chuyển Baseline Tích lũy

Thời gian di chuyển từ vị trí hiện tại của xe $s_{\text{bus}, j}$ đến trạm đích $s_{\text{target}}$ được phân rã thành **2 thành phần độc lập**:

$$\text{ETA}(V_j \to S_{\text{target}}) = \text{Residual}(V_j \to S_{k+1}) + \sum_{m = k+1}^{\text{ord}_{\text{target}} - 1} \Delta T_{\text{baseline}}(m \to m+1)$$

#### Thành phần 1: Thời gian Dư của Phân đoạn Hiện tại ($\text{Residual}$)
Đoạn trạm $[k, k+1]$ xe đã đi được một phần quãng đường.
- Quãng đường còn lại của đoạn hiện tại:
  $$\Delta s_{\text{rem}, j} = s_{k+1} - s_{\text{bus}, j}$$
- Tỷ lệ quãng đường còn lại trên tổng chiều dài đoạn:
  $$\rho_j = \frac{\Delta s_{\text{rem}, j}}{s_{k+1} - s_k} = \frac{s_{k+1} - s_{\text{bus}, j}}{L_k} \in (0, 1]$$
- Thời gian di chuyển của đoạn $[k, k+1]$ được tra cứu từ Ma trận Baseline `agg_segment_travel_times` theo đúng chế độ vận hành thời gian thực $(\text{day\_type}, \text{hour\_slot})$:
  $$T_{P_{50}}(k \to k+1) = \mathcal{M}_{P_{50}}(R, D, k, k+1, \text{day\_type}, \text{hour\_slot})$$
- Thời gian dư trung vị được tính theo tỷ lệ tiến trình không gian:
  $$\text{Residual}_{P_{50}}(j) = \rho_j \times T_{P_{50}}(k \to k+1)$$
  Tương tự cho phân vị nhanh $P_{10}$ và phân vị chậm $P_{90}$:
  $$\text{Residual}_{P_{10}}(j) = \rho_j \times T_{P_{10}}(k \to k+1)$$
  $$\text{Residual}_{P_{90}}(j) = \rho_j \times T_{P_{90}}(k \to k+1)$$

*(Ghi chú: Không chia thô cho vận tốc tức thời $v_j$ khi xe đang dừng chờ đèn đỏ $v_j=0$ để tránh lỗi chia cho 0 hoặc làm ETA nhảy vọt vô lý).*

#### Thành phần 2: Tổng Thời gian Di chuyển Các Đoạn trạm Tiếp theo
Nếu $k+1 = \text{ord}_{\text{target}}$, xe đang ở ngay đoạn trạm cuối cùng dẫn tới đích $\to$ Thành phần 2 bằng 0.
Nếu $k+1 < \text{ord}_{\text{target}}$, cộng dồn trực tiếp các ô tương ứng trong ma trận Baseline:
$$\text{Intermediate}_{P_{50}}(j) = \sum_{m = k+1}^{\text{ord}_{\text{target}} - 1} \mathcal{M}_{P_{50}}(R, D, m, m+1, \text{day\_type}, \text{hour\_slot})$$
$$\text{Intermediate}_{P_{10}}(j) = \sum_{m = k+1}^{\text{ord}_{\text{target}} - 1} \mathcal{M}_{P_{10}}(R, D, m, m+1, \text{day\_type}, \text{hour\_slot})$$
$$\text{Intermediate}_{P_{90}}(j) = \sum_{m = k+1}^{\text{ord}_{\text{target}} - 1} \mathcal{M}_{P_{90}}(R, D, m, m+1, \text{day\_type}, \text{hour\_slot})$$

#### Thành phần 3: Tổng Hợp Dự báo ETA
$$\text{ETA}_{P_{50}}(V_j \to S_{\text{target}}) = \text{Residual}_{P_{50}}(j) + \text{Intermediate}_{P_{50}}(j)$$
$$\text{ETA}_{P_{10}}(V_j \to S_{\text{target}}) = \text{Residual}_{P_{10}}(j) + \text{Intermediate}_{P_{10}}(j)$$
$$\text{ETA}_{P_{90}}(V_j \to S_{\text{target}}) = \text{Residual}_{P_{90}}(j) + \text{Intermediate}_{P_{90}}(j)$$

---

### 2.4. Bất biến Toán học & Cửa sổ An toàn Bất đối xứng (Asymmetric Safe Window)

1. **Bất biến Thứ tự Phân vị Ngặt (Quantile Monotonicity Invariant):**
   Với mọi xe $V_j$ và mọi trạm $S_{\text{target}}$, kết quả dự báo bắt buộc phải thỏa mãn:
   $$0 \le \text{ETA}_{P_{10}} \le \text{ETA}_{P_{50}} \le \text{ETA}_{P_{90}}$$
   Nếu ma trận dữ liệu có ô khuyết hoặc nhiễu, thuật toán bắt buộc phải kẹp giá trị (clamping):
   $$\text{ETA}_{P_{50}} = \max(\text{ETA}_{P_{10}}, \text{ETA}_{P_{50}})$$
   $$\text{ETA}_{P_{90}} = \max(\text{ETA}_{P_{50}}, \text{ETA}_{P_{90}})$$

2. **Khái niệm "Cửa sổ An toàn Chống Lỡ Xe":**
   - Phân vị $P_{10}$ đại diện cho kịch bản giao thông hoàn toàn thông thoáng (xe chạy nhanh nhất trong 10% trường hợp).
   - Do đó, thời điểm sớm nhất xe có thể cập bến là:
     $$t_{\text{early}} = t_{\text{now}} + \text{ETA}_{P_{10}}$$
   - **Khuyến nghị cho Hành khách (Actionable User Recommendation):**
     Hành khách **bắt buộc phải có mặt tại trạm trước thời điểm $t_{\text{early}}$** để đảm bảo xác suất bắt kịp xe là **$\ge 90\%$**.
   - Thời gian chờ đợi dự kiến thông thường là $\text{ETA}_{P_{50}}$, và thời gian trễ tối đa trong điều kiện ùn tắc là $\text{ETA}_{P_{90}}$.

---

### 2.5. Cơ chế Mở rộng Kết nối Mô hình Máy học (XGBoost Residual Integration)

Kiến trúc hỗ trợ giao diện cắm ghép (pluggable interface) cho mô hình máy học XGBoost mà không làm phá vỡ tính ổn định của hệ thống:
1. **Kiểm tra Tuyến Hỗ trợ ML:** Nếu tuyến $R$ có mô hình XGBoost residual $\mathcal{F}_{\text{XGB}}^{(R)}$ được tải sẵn trong RAM:
   $$\Delta \widehat{\text{ETA}} = \mathcal{F}_{\text{XGB}}^{(R)}(\mathbf{x}_{\text{features}})$$
   $$\text{ETA}_{\text{ML}} = \text{clip}\left(\text{ETA}_{P_{50}} + \Delta \widehat{\text{ETA}}, \;\; \text{ETA}_{P_{10}}, \;\; \text{ETA}_{P_{90}}\right)$$
2. **Cơ chế Fallback An toàn Tuyệt đối:** Nếu tuyến $R$ chưa huấn luyện mô hình ML riêng biệt, hoặc thời gian trích xuất đặc trưng vượt quá $5\text{ms}$, hệ thống **tự động fallback trực tiếp về $\text{ETA}_{P_{50}}$** của Ma trận Baseline. Tuyệt đối không để dịch vụ bị gián đoạn hay trả về mã lỗi 500.

---

### 2.6. Xử lý Toàn diện Các Ca Biên (Edge Cases)

| Kịch bản biên | Biểu hiện không gian / thời gian | Hành vi xử lý chuẩn của hệ thống |
| :--- | :--- | :--- |
| **Ca Biên 1: Trạm Đầu Bến ($S_0$)** | Hành khách chọn trạm xuất phát `station_order = 0`. | Không có xe nào ở phía sau trạm 0 ($s_{\text{bus}} < 0$). Trả về danh sách xe rỗng `buses: []`, hiển thị thông báo: *"Trạm đầu bến. Xe xuất bến theo nốt điều độ."* |
| **Ca Biên 2: Trạm Cuối Bến ($S_{N-1}$)** | Hành khách chọn trạm bến đích `station_order = N - 1`. | Toàn bộ các xe đang lưu thông trên hành trình đều hợp lệ ($s_{\text{bus}} < s_{N-1}$). Tính toán ETA đầy đủ cho toàn đoàn xe. |
| **Ca Biên 3: Xe Vừa Cập Bến Trạm ($\Delta s \le 30\text{m}$)** | $s_{\text{target}} - 30\text{m} \le s_{\text{bus}} < s_{\text{target}}$. | Gán nhãn trạng thái `ARRIVING_NOW`. Đặt $\text{ETA} = 0\text{ phút}$. Hiển thị huy hiệu nhấp nháy: *"Xe đang cập bến"*. |
| **Ca Biên 4: Xe Đã Vượt Qua Trạm** | $s_{\text{bus}} \ge s_{\text{target}}$. | Xe đã đi qua trạm, tuyệt đối không tính lùi. Tự động chuyển trọng tâm sang xe tiếp theo chạy phía sau. |
| **Ca Biên 5: Rỗng Xe Trên Tuyến** | Toàn bộ xe đã về bến hoặc không có xe nào phía sau trạm. | Trả về `buses: []`. Ước lượng khoảng cách giãn cách trung bình chuyến kế tiếp ($\approx 10 - 15\text{ phút}$). |
| **Ca Biên 6: Ca Đêm Sau 22:30** | Thời gian thực $t_{\text{now}} > 22:30$ hoặc trước $05:00$. | Trả về trạng thái `NIGHT_OFF_SERVICE`. Hiển thị thông báo: *"Tuyến đã kết thúc ca chạy trong ngày. Giờ mở bến: 05:00 sáng mai"*. |

---

## 3. THIẾT KẾ HỢP ĐỒNG GIAO TIẾP API RESTFUL (API CONTRACT)

### 3.1. Endpoint Đặc tả
- **Giao thức:** HTTPS GET
- **Đường dẫn:** `/api/station-eta`
- **Thời gian phản hồi cam kết (SLA Latency):** $\le 20\text{ms}$ (truy vấn ma trận nạp sẵn trong RAM bộ nhớ đệm).

### 3.2. Tham số Yêu cầu (Request Query Parameters)

| Tham số | Kiểu dữ liệu | Bắt buộc | Mặc định | Ý nghĩa & Ví dụ |
| :--- | :---: | :---: | :---: | :--- |
| `route_id` | `integer` | Tùy chọn* | `null` | ID tuyến nguyên bản BusMap (ví dụ: `2`, `27`, `101103`). |
| `route` | `string` | Tùy chọn* | `null` | Số hiệu tuyến buýt (ví dụ: `'02'`, `'27'`, `'E01'`). |
| `direction` | `string` / `int` | Bắt buộc | `0` | Hướng di chuyển: `0` hoặc `'go'` (Chiều đi); `1` hoặc `'re'` (Chiều về). |
| `station_order` | `integer` | Bắt buộc | - | Thứ tự trạm dừng mục tiêu (0-based, từ `0` đến `N-1`). |

*Ghi chú: Bắt buộc cung cấp ít nhất một trong hai tham số `route_id` hoặc `route`.*

### 3.3. Cấu trúc Dữ liệu Phản hồi (Response JSON Schema)

```json
{
  "route_id": 2,
  "route_code": "02",
  "direction": 0,
  "direction_str": "go",
  "target_station": {
    "station_order": 5,
    "station_id": 5765,
    "station_name": "Ga La Khê",
    "cum_distance_m": 2815.0,
    "lat": 20.963609,
    "lon": 105.766824,
    "address": "Đối diện Ga La Khê - Quang Trung (Hà Đông)"
  },
  "query_time": "2026-11-09T13:45:22+07:00",
  "day_type": 0,
  "hour_slot": 13,
  "traffic_condition": "THONG_THOANG",
  "approaching_count": 2,
  "buses": [
    {
      "vehicle_id": 8836680,
      "plate": "29B-190.63",
      "distance_to_station_m": 590.6,
      "stops_remaining": 1,
      "eta_seconds": 105.0,
      "eta_minutes": 1.8,
      "safe_window": {
        "p10_seconds": 88.0,
        "p50_seconds": 105.0,
        "p90_seconds": 132.0,
        "recommended_arrival_time": "13:46:50"
      },
      "speed_kmh": 24.5,
      "status": "IN_TRANSIT"
    },
    {
      "vehicle_id": 8836704,
      "plate": "29B-193.01",
      "distance_to_station_m": 1666.0,
      "stops_remaining": 3,
      "eta_seconds": 312.0,
      "eta_minutes": 5.2,
      "safe_window": {
        "p10_seconds": 265.0,
        "p50_seconds": 312.0,
        "p90_seconds": 380.0,
        "recommended_arrival_time": "13:49:47"
      },
      "speed_kmh": 20.0,
      "status": "IN_TRANSIT"
    }
  ],
  "message": "Có 2 xe đang di chuyển về trạm."
}
```

### 3.4. Các Mã Lỗi Chuẩn (Error Responses)
- `HTTP 400 Bad Request`: Thiếu tham số `route_id`/`route`, sai định dạng `direction` (không phải 0, 1, 'go', 're'), hoặc `station_order < 0`.
- `HTTP 404 Not Found`: Tuyến không tồn tại trong danh mục hoặc `station_order >= N`.
- `HTTP 200 OK (Thành công nhưng rỗng)`: Tuyến hợp lệ nhưng hiện không có xe nào tiếp cận trạm (`approaching_count = 0`, `buses = []`).

---

## 4. THIẾT KẾ TRẢI NGHIỆM NGƯỜI DÙNG TRÊN GIAO DIỆN (UX/UI SPECIFICATION)

### 4.1. Tương tác Nhấp Marker Trạm Dừng (Leaflet Station Badge Popup)
Hiện tại, khi nhấp vào trạm dừng trên bản đồ vệ tinh Esri, popup chỉ hiển thị thông tin tĩnh (tên trạm, số thứ tự, mã trạm, lý trình).
**Nâng cấp tương tác:**
1. Khi sự kiện `marker.on('click')` được kích hoạt trên một trạm dừng $S_{\text{target}}$:
   - Popup mở ra tức thì hiển thị thông tin trạm kèm một thẻ trạng thái: *"Đang tính toán thời gian xe đến..."*
   - Gọi bất đồng bộ `fetch('/api/station-eta?route_id=...&direction=...&station_order=...')`.
2. Khi có dữ liệu phản hồi:
   - Nếu có xe tiếp cận:
     * Hiển thị nổi bật xe gần nhất: **Biển số**, **Phút ETA** (`1.8 phút`), và **Cửa sổ an toàn** (`[1.5 - 2.2 phút]`).
     * Dòng khuyến nghị trực quan: `Đến trạm trước 13:46 để không lỡ xe`.
     * Nếu có $\ge 2$ xe: Hiển thị bảng thu nhỏ (Mini-timeline) các chuyến tiếp sau.
   - Nếu không có xe nào: Hiển thị: *"Hiện chưa có xe nào chạy về trạm này. Giãn cách dự kiến: ~10-15 phút"*.
   - Nút hành động tiện ích: `[📌 Ghim theo dõi trạm]` để đưa thông tin trạm này vào bảng điều khiển bên hông (Sidebar).

```text
+-----------------------------------------------------------+
| [14] Trạm: ĐH Kiến Trúc Hà Nội                 [Chiều đi] |
| Trạm số 14 / 38 &bull; Lý trình: 7.45 km                  |
+-----------------------------------------------------------+
| 🚍 XE GẦN NHẤT ĐANG ĐẾN:                                   |
| Biển số: 29B-190.63 &bull; Còn 1 trạm (590 m)              |
| Thời gian dự kiến (ETA):  1.8 PHÚT                        |
| Cửa sổ an toàn: [1.5 phút  -  2.2 phút]                   |
| Khuyến nghị: Có mặt trước 13:46:50                        |
+-----------------------------------------------------------+
| 🕒 Chuyến kế tiếp: 29B-193.01 &bull; 5.2 phút (3 trạm nữa)|
+-----------------------------------------------------------+
| [ 📌 Ghim theo dõi trạm vào thanh bên ]                    |
+-----------------------------------------------------------+
```

### 4.2. Bảng Theo Dõi Trạm Ghim trên Sidebar (Station Focus Card)
1. Khi một trạm được ghim (pinned station):
   - Phía trên danh sách xe (`.vehicles-section`) trong Sidebar xuất hiện khối thẻ **`#stationFocusCard`** với viền sáng nổi bật (Accent Border).
   - Khối thẻ hiển thị cố định: Tên trạm được ghim, số thứ tự, và đếm lùi thời gian đến của xe gần nhất.
2. Cơ chế Đồng bộ Chu kỳ 15s (Discrete Polling Synchronization):
   - Bảng ETA trạm được tự động làm mới đồng bộ với nhịp `POLL_INTERVAL_MS = 15000` của bản đồ.
   - Không tạo thêm timer độc lập gây giật lag hoặc quá tải request.
   - Nút `[✕ Bỏ ghim]` cho phép người dùng đóng thẻ và quay lại chế độ xem tổng quan toàn tuyến.

---

## 5. BỘ TIÊU CHUẨN KIỂM THỬ HỘP ĐEN ĐỘC LẬP CHO `@blind_tester` (ACCEPTANCE CRITERIA)

Bộ kiểm thử được viết hoàn toàn độc lập dưới dạng kịch bản black-box, không phụ thuộc mã nội bộ:

### TC-ETA-01: Kiểm định Hợp đồng Schema & Mã Trả về (DoD-1)
- **Hành động:** Gửi `GET /api/station-eta?route=02&direction=0&station_order=5`.
- **Kỳ vọng:**
  - HTTP Status `200 OK`.
  - Schema phản hồi chứa đầy đủ các trường: `route_id`, `route_code`, `direction`, `target_station`, `approaching_count`, `buses`.
  - Mảng `target_station` có đầy đủ: `station_order == 5`, `cum_distance_m > 0`, `station_name` không rỗng.

### TC-ETA-02: Bất biến Toán học Phân vị & Thứ tự Không gian (DoD-2)
- **Hành động:** Kiểm tra toàn bộ các đối tượng trong mảng `buses`:
- **Kỳ vọng:**
  - $0 \le \text{safe\_window.p10\_seconds} \le \text{safe\_window.p50\_seconds} \le \text{safe\_window.p90\_seconds}$.
  - $\text{distance\_to\_station\_m} > 0$.
  - $\text{stops\_remaining} \ge 0$.
  - $\text{eta\_minutes} = \text{round}(\text{eta\_seconds} / 60.0, 1)$.

### TC-ETA-03: Tính Nhất Quán về Chiều và Vị trí Xe (DoD-3)
- **Hành động:** Đối chiếu danh sách xe tiếp cận với API `/api/live-vehicles?route=02&direction=0`:
- **Kỳ vọng:**
  - 100% xe trong danh mục tiếp cận phải có mặt trong tập xe của `/api/live-vehicles` tại cùng chiều `direction=0`.
  - Không có bất kỳ xe nào có vị trí $s_{\text{bus}} > s_{\text{target}} + 30\text{m}$ (không lọt xe đã đi qua trạm).

### TC-ETA-04: Kiểm thử Ca Biên Bến Xuất phát & Bến Cuối (DoD-4)
- **Ca 4.1:** Gửi truy vấn trạm đầu bến `station_order = 0`:
  - `approaching_count == 0` và `buses == []`.
- **Ca 4.2:** Gửi truy vấn trạm cuối cùng `station_order = N - 1`:
  - Số lượng xe tiếp cận `approaching_count` bằng toàn bộ số xe đang lưu thông trên tuyến ở chiều đó.

### TC-ETA-05: Kiểm định Hiệu năng Đáp ứng Thời gian Thực (SLA Latency) (DoD-5)
- **Hành động:** Chạy lặp 50 truy vấn liên tiếp qua TestClient:
- **Kỳ vọng:**
  - Thời gian phản hồi $P_{95} \le 20.0\text{ ms}$.
  - CPU không tăng đột biến, không có rò rỉ bộ nhớ (Zero Memory Leak).

---

## 6. KẾ HOẠCH BÀN GIAO & PHÂN CÔNG THỰC THI

1. **`@leaf_coder`:**
   - Cài đặt hàm tính ETA đến trạm trong `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/busmap_service.py`:
     * Nạp sẵn ma trận `agg_segment_travel_times` vào RAM (`_baseline_matrix_cache`) lúc khởi động service.
     * Cài đặt phương thức `get_station_eta(route_ident, direction, station_order)`.
   - Bổ sung route `/api/station-eta` trong `module_3_bus_eta_prediction/step_3_5_web_demo/app.py`.
   - Cập nhật giao diện trong `static/app.js` và `static/index.html`, `static/style.css`:
     * Mở rộng popup trạm dừng với thông tin ETA và cửa sổ an toàn.
     * Thêm khối `#stationFocusCard` bên thanh sidebar.
2. **`@blind_tester`:**
   - Xây dựng bộ test hộp đen `tests/test_station_eta_blackbox.py` phủ kín 5 ca kiểm định (TC-ETA-01..05) dựa trên đặc tả này và chạy nghiệm thu độc lập.
3. **`@architect`:**
   - Giám sát ranh giới kiến trúc, nghiệm thu độ thuần khiết Simplicity First, tuyệt đối không cho phép đưa mã nội suy 60 FPS quay trở lại.
