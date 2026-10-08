# Phân Tích Khoa Học: Giới Hạn Bao Phủ Tối Đa Của Hệ Thống Congestion (TomTom + Bus-as-a-Probe)

## 1. Định Nghĩa Khoa Học Về "Tiệm Cận Chính Xác" (Near-Accurate Precision)

Trong Lý thuyết Dòng giao thông Đô thị (Urban Traffic Flow Theory) và Kỹ thuật Dự báo ETA, một hệ thống giám sát mức độ tắc nghẽn được coi là **"tiệm cận chính xác theo thời gian thực"** khi thỏa mãn 3 điều kiện biên:

1. **Độ phân giải thời gian (Temporal Resolution $\tau_{\max}$):**
   - **Giờ cao điểm (Peak: 06:30 - 08:30 & 16:30 - 18:30):** Trạng thái giao thông biến đổi nhanh theo sóng xung kích (Shockwave propagation). Độ trễ cập nhật dữ liệu tốc độ trên mỗi phân đoạn đường bắt buộc phải thỏa mãn:
     $$\tau_{\text{peak}} \le 4 - 5 \text{ phút}$$
   - **Giờ thấp điểm (Off-peak: các khung giờ còn lại):** Dòng xe ổn định hơn:
     $$\tau_{\text{offpeak}} \le 8 - 10 \text{ phút}$$
   - *Nếu một phân đoạn bị bỏ trống $> 15\text{ phút}$ mà không có dữ liệu tốc độ mới, sai số dự báo ETA sẽ tăng vọt $> 30\%$.*
2. **Độ phân giải không gian (Spatial Resolution):**
   - Đoạn đường phân tích (Road segment) có chiều dài $\Delta s \approx 300 - 600\text{ m}$ (tương đương khoảng cách giữa 2 điểm dừng xe buýt liên tiếp hoặc giữa 2 ngã tư).
3. **Mục tiêu sai số ETA (Prediction Error Bound):**
   - Sai số tuyệt đối trung bình (MAE) của mô hình ETA: $\text{MAE} \le 1.5 - 2.5\text{ phút}$ cho lộ trình di chuyển 15 - 30 phút.

---

## 2. Mô Hình Toán Học Kết Hợp: Bus-as-a-Probe (BaaP) & TomTom

### 2.1. Nguồn Dữ Liệu Lõi: Bus-as-a-Probe (935 Xe Buýt Hà Nội)
- Chúng ta crawl dữ liệu GPS từ hệ thống BusMap với chu kỳ $\Delta t_{\text{crawl}} = 60\text{s}$.
- Xét một tuyến xe buýt có chiều dài 1 chiều $L$ (chiều dài 2 chiều $2L$), số xe buýt hoạt động đồng thời là $N_{\text{bus}}$, vận tốc trung bình thương mại $\bar{v}_{\text{bus}} \approx 16\text{ km/h}$.
- Thời gian quay vòng 1 chu kỳ hoàn chỉnh (Cycle time):
  $$T_{\text{cycle}} = \frac{2L}{\bar{v}_{\text{bus}}} \quad (\text{giờ})$$
- Tần suất xe buýt xuất hiện liên tiếp tại một phân đoạn đường bất kỳ (Headway $h$):
  $$h = \frac{T_{\text{cycle}}}{N_{\text{bus}}} = \frac{120 \cdot L}{N_{\text{bus}} \cdot \bar{v}_{\text{bus}}} \quad (\text{phút})$$

#### Thực tế tại Hà Nội:
- Tuyến buýt nội đô trục chính có $L \approx 18\text{ km}$, $N_{\text{bus}} \approx 16\text{ xe}$:
  $$h = \frac{120 \times 18}{16 \times 16} \approx 8.4\text{ phút}$$
- **Đánh giá năng lực của BaaP:**
  - Trên các đoạn đường thẳng thông thường (chiếm 80% chiều dài tuyến): Tần suất 8 - 9 phút/lần là **đạt chuẩn chính xác** vì vận tốc trên các đoạn này ít biến động đột ngột.
  - Tại các nút giao nghẽn cổ chai (Bottleneck - chiếm 20% chiều dài tuyến): Khoảng cách 8.4 phút **chưa đủ độ mịn** trong giờ cao điểm (khi mà chỉ cần 3 phút tắc đường đã lan rộng thêm 200m).

---

### 2.2. Nguồn Bù Đắp Khoảng Trống: TomTom FlowSegmentData API
TomTom được dùng làm **vũ khí bù đắp chính xác (Gap-Filling & Shockwave Tracking)** tại các điểm nghẽn cổ chai (Bottlenecks):

#### Thuật toán kích hoạt TomTom (Event-Driven Trigger Rule):
Tại mỗi điểm nút nghẽn $B_k$:
- Khi xe buýt vừa đi qua tại thời điểm $t_0$, hệ thống nhận vận tốc thực tế $v_{\text{bus}}$.
- Hệ thống đếm ngược: Nếu sau $\Delta t_{\text{threshold}} = 4\text{ phút}$ (giờ cao điểm) hoặc $8\text{ phút}$ (giờ thấp điểm) mà **chưa có xe buýt tiếp theo tiếp cận**, TomTom sẽ tự động "bắn" 1 request lấy `FlowSegmentData` tại đúng nút giao đó.
- Nhờ cơ chế này, độ trễ quan sát tại điểm nghẽn luôn được "ghim chặt" ở mức $\le 4\text{ phút}$!

#### Định mức request tiêu thụ cho 1 điểm Bottleneck / ngày:
Thời gian hoạt động xe buýt: 16 giờ/ngày (06:00 - 22:00 = 960 phút).
- **Giờ cao điểm (4 giờ = 240 phút):** Cần bù trung bình 7 lần/giờ $\times 4\text{h} \approx 28\text{ req}$.
- **Giờ bình thường (12 giờ = 720 phút):** Cần bù trung bình 2.5 lần/giờ $\times 12\text{h} \approx 30\text{ req}$.
- **Tổng request cho 1 điểm bottleneck:**
  $$C_{\text{bottleneck}} \approx 58 - 60 \text{ requests/ngày}$$

---

## 3. Xác Định Con Số Tối Đa (Maximum Capacity Limits)

Với hạn ngạch cố định của TomTom Free Tier: **$Q_{\text{tomtom}} = 2.500\text{ requests/ngày}$**:

### 3.1. Số điểm Bottleneck tối đa được bảo vệ 24/7:
$$M_{\max} = \frac{Q_{\text{tomtom}}}{C_{\text{bottleneck}}} = \frac{2.500}{60} \approx \mathbf{41\text{ điểm nghẽn trọng yếu}}$$

### 3.2. Số tuyến xe buýt tối đa có thể bao phủ:
Trong cấu trúc mạng lưới giao thông Hà Nội:
- Mỗi tuyến buýt trục chính (dài 18 - 25 km) thường đi qua **5 - 7 điểm nghẽn lớn** (ví dụ: Ngã Tư Sở, Cầu Giấy, Kim Mã, Chùa Bộc, Giải Phóng, Nguyễn Trãi).
- Tuy nhiên, **các tuyến xe buýt tại Hà Nội có tính chia sẻ hạ tầng cực kỳ cao**:
  - Trục Nguyễn Trãi - Tây Sơn: Tuyến 01, 02, 19, 27 cùng chạy chung.
  - Trục Cầu Giấy - Xuân Thủy: Tuyến 07, 27, 32, 26 cùng chạy chung.
  - Trung bình, 1 điểm nghẽn lớn phục vụ chung cho **1.8 đến 2.5 tuyến xe buýt**!
- Số điểm nghẽn độc nhất quy đổi trên mỗi tuyến chỉ khoảng **3.5 - 4.5 điểm**.

$$\text{Số lượng tuyến tối đa} = \frac{M_{\max}}{\text{Số điểm nghẽn riêng mỗi tuyến}} = \frac{41}{3.5 \text{ đến } 4.5} \approx \mathbf{9 - 12\text{ tuyến buýt}}$$

### 3.3. Số km đường tối đa bao phủ tiệm cận chính xác:
1. **Theo chiều dài lượt tuyến (Route-km):**
   - Mỗi tuyến có chiều dài khứ hồi khoảng $36 - 44\text{ km}$.
   - Với 9 - 12 tuyến:
     $$L_{\text{route}} = 10 \times 40\text{ km} \approx \mathbf{360 - 480\text{ km (Lượt tuyến)}}$$
2. **Theo chiều dài mạng lưới đường thực tế độc nhất (Unique Road Centerline-km):**
   - Với hệ số trùng lặp tuyến $K_{\text{overlap}} \approx 1.8$:
     $$L_{\text{physical}} = \frac{360 \text{ đến } 480}{1.8} \approx \mathbf{180 - 260\text{ km đường trục chính đô thị}}$$
   - *180 - 260 km đường là quy mô khổng lồ, đủ bao phủ toàn bộ các trục xuyên tâm huyết mạch nhất của toàn bộ khu vực nội thành Hà Nội (Vành đai 1, Vành đai 2, Vành đai 3 và các trục xuyên tâm).*

---

## 4. Bảng So Sánh 3 Kịch Bản Triển Khai Thực Tế

| Chỉ số kỹ thuật | Kịch bản 1: Thí điểm Tinh gọn (Pilot Core) | Kịch bản 2: Vùng Đô thị Tối ưu (Optimal Urban Corridor) | Kịch bản 3: Tới hạn Lý thuyết (Upper Bound Max) |
| :--- | :---: | :---: | :---: |
| **Số lượng tuyến** | **3 - 4 tuyến**<br>*(Tuyến 01, 02, 27, 32)* | **8 - 10 tuyến**<br>*(Thêm BRT01, 22A, 07, E01, E02)* | **14 - 16 tuyến**<br>*(Thêm 19, 29, 26, 34, 09)* |
| **Số xe buýt Probe (BaaP)** | **66 xe** | **169 xe** | **~250 xe** |
| **Số km đường vật lý** | **65 - 85 km** | **160 - 200 km** | **240 - 280 km** |
| **Số điểm nghẽn TomTom** | 14 nút giao | 36 nút giao | 48 nút giao |
| **Tần suất quét điểm nghẽn** | **3 - 4 phút/lần** (Rất dày) | **4 - 5 phút/lần** (Chuẩn) | **7 - 8 phút/lần** (Bị giãn cách) |
| **Độ trễ tối đa ($\tau_{\max}$)** | $\le 3\text{ phút}$ | $\le 5\text{ phút}$ | $\le 8\text{ phút}$ |
| **Sai số dự báo ETA (MAE)** | **$\pm 1.0 - 2.0\text{ phút}$** | **$\pm 2.0 - 2.8\text{ phút}$** | **$\pm 3.5 - 4.5\text{ phút}$** |
| **Request TomTom tiêu thụ** | ~840 / 2.500 req (Dư 66%) | ~2.160 / 2.500 req (Dư 14%) | ~2.500 / 2.500 req (Chạm trần 100%) |
| **Mức độ an toàn vận hành** | 🛡️ **Tuyệt đối an toàn** | 🎯 **Tối ưu nhất cho Big Data** | ⚠️ Rủi ro chạm trần khi mất mạng/retry |

---

## 5. Khuyến Nghị Lộ Trình Triển Khai Cho Dự Án

### Giai đoạn 1 (Tuần 1 - 3): Vận hành Kịch bản 1 (4 tuyến xương sống)
- **Tập hợp 4 tuyến:**
  1. **Tuyến 01:** BX Gia Lâm ⇄ BX Yên Nghĩa (Trục xuyên tâm Bắc - Nam, 7 xe)
  2. **Tuyến 02:** Bác Cổ ⇄ BX Yên Nghĩa (Trục Nguyễn Trãi - Trần Phú, 16 xe)
  3. **Tuyến 27:** BX Yên Nghĩa ⇄ Nam Thăng Long (Trục Vành đai 2 - 3, 20 xe)
  4. **Tuyến 32:** BX Giáp Bát ⇄ Nhổn (Trục Giải Phóng - Cầu Giấy, 13 xe)
- **Quy mô:** Bao phủ **~75 km đường trục**, kiểm soát **66 xe buýt telemetry 24/7**, và giám sát **14 nút giao tử thần** bằng TomTom.
- **Mục tiêu:** Tinh chỉnh thuật toán Map-Matching và Spark Streaming đạt độ chính xác ETA $\le 2\text{ phút}$.

### Giai đoạn 2 (Tuần 4 - 6): Mở rộng lên Kịch bản 2 (10 tuyến tối ưu)
- Bổ sung thêm 6 tuyến: **BRT01 (15 xe), 22A (16 xe), 07 (17 xe), E01 (23 xe), E02 (16 xe), 19 (13 xe)**.
- Đưa tổng số probe lên **169 xe buýt**, bao phủ **~180 km đường đô thị** khắp các quận nội thành Hà Nội, tiêu thụ vừa vặn **~2.200 requests TomTom/ngày**.

