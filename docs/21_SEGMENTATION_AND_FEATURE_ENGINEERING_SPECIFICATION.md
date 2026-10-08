# 21. ĐẶC TẢ PHÂN ĐOẠN TUYẾN, XỬ LÝ CHẶNG DỞ DANG & BỘ ĐẶC TRƯNG 24 CHIỀU (SEGMENTATION & FEATURE SPECIFICATION)

> **Mục tiêu tài liệu:** Chuẩn hóa phương pháp phân đoạn tuyến (Segmentation Strategy), giải thuật toán học xử lý xe đang ở giữa đoạn (Partial Segment), và đặc tả chi tiết 24 chiều đặc trưng đầu vào cùng đầu ra của mô hình Machine Learning.

---

## 1. Bài Toán Phân Đoạn Tuyến: Theo TomTom Hay Theo Trạm Dừng?

### 1.1. So sánh hai trường phái:
- **Nếu chia theo TomTom (Bottleneck-based)**:
  - Toàn bộ hành lang Bách Khoa chỉ có 19 điểm nghẽn TomTom. Một tuyến xe buýt dài 12–15 km chỉ đi qua 2–3 nút TomTom.
  - Các đoạn bị quá dài (3–5 km/đoạn), bên trong chứa tới 6–8 trạm dừng.
  - Mất hoàn toàn độ phân giải vi mô; người dùng đứng ở trạm giữa chừng không thể biết khi nào xe đến trạm của mình.
- **Nếu chia theo Trạm Dừng (Inter-Stop Segments)**:
  - Một tuyến có khoảng 25–35 trạm dừng. Chiều dài tự nhiên của một chặng giữa 2 trạm là **400m – 700m** (thời gian xe chạy 1.5 – 3 phút).
  - Đây là đơn vị tự nhiên gắn liền với hành vi người dùng (họ đứng chờ ở trạm, lên/xuống ở trạm).

### 1.2. Giải pháp Hợp Nhất (Hierarchical Overlay Strategy):
> **Lấy Trạm Dừng làm khung xương chính (Primary Segmentation), phủ TomTom làm thuộc tính không gian (Spatial Overlay Attribute).**

```text
[Trạm S_1] ─────────────── [Trạm S_2] ─────────────── [Trạm S_3]
   │                           │                           │
   └──────── Chặng 1 ──────────┘──────── Chặng 2 ──────────┘
             (500m)                      (650m)
                                           ▲
                                           │ (Chứa nút giao TomTom Ngã Tư Sở)
                                    [TomTom Bottleneck Overlay]
```

- **Mỗi chặng $k = (S_i \to S_{i+1})$ là 1 đơn vị dự báo độc lập.**

### 1.3. Tiền Xử Lý Không Gian Cố Định: Bảng Giao Cắt TomTom Ngoại Tuyến (Offline Precomputed Spatial Overlap)
Do tọa độ 19 nút TomTom và tim đường 19 tuyến buýt là **cố định tuyệt đối về mặt địa lý**:
- Ta thực hiện tiền xử lý hình học (GIS Spatial Intersection) **1 lần duy nhất offline** trước khi chạy hệ thống.
- Với mỗi chặng $k$, hệ thống tính sẵn:
  - `tomtom_node_id`: Chặng $k$ giao với nút TomTom nào (nếu không giao $\implies$ `None`).
  - `L_overlap_m`: Chiều dài thực tế phần đường giao nhau giữa chặng $k$ và đoạn TomTom đo (mét).
- **Lúc vận hành thực tế (Inference)**: Không tính toán hình học GIS, chỉ tra bảng thời gian $O(1)$ và nhân trực tiếp với độ trễ TomTom:
  $$\Delta t_{tomtom\_contrib} = L_{overlap\_m} \times \left( \frac{1}{v_{tomtom\_current}} - \frac{1}{v_{free\_flow}} \right) \quad (\text{giây})$$

### 1.4. Chỉ Số Chất Lượng Mặt Đường & Ma Sát Hạ Tầng (Road Surface Quality & Impedance Index)
Giữa khoảng cách $d$ và thời gian thông thoáng $T_{base}$, có một sự chênh lệch tự nhiên do chất lượng mặt đường, gờ giảm tốc, độ gồ ghề và xung đột tĩnh gây ra.
- Vận tốc thiết kế lý tưởng trên đường phẳng: $v_{limit} \approx 40\text{ km/h}$ ($11.1\text{ m/s}$).
- Vận tốc thông thoáng thực tế đo được từ số liệu: $v_{base}(k) = \frac{L_k}{T_{base}(k)} \times 3.6$ (km/h).
- **Chỉ số Chất lượng Đường (`road_quality_index` $\in (0.0, 1.0]$)**:
  $$Q_{road}(k) = \frac{v_{base}(k)}{v_{limit}}$$
  - **Đường đẹp, mặt đường asphan phẳng (Đại lộ Giải Phóng, Cầu vượt)**: Xe chạy bon, $v_{base} \approx 36\text{ km/h} \implies Q_{road} \approx 0.90$ (Chất lượng rất cao).
  - **Đường xấu, hẹp gồ ghề, nhiều nắp cống (Chùa Bộc, Đê La Thành cũ)**: Xe phải rà phanh nhíp nảy dù đường vắng, $v_{base} \approx 18\text{ km/h} \implies Q_{road} \approx 0.45$ (Chất lượng kém, ma sát cao).
  - Đây là một **đặc trưng nội tại cực kỳ giá trị**, phản ánh trực tiếp chất lượng hạ tầng vật lý của từng cung đường Hà Nội!

---

## 2. Giải Thuật Xử Lý Xe Đang Ở Giữa Đoạn (Partial In-Progress Segment)

Khi người dùng mở ứng dụng tại thời điểm $t_{now}$, xe buýt hiếm khi nằm đúng vạch xuất phát của trạm $S_1$, mà đang ở một vị trí bất kỳ ở **giữa Chặng 1**.

```text
                    Vị trí hiện tại v(t_now)
[Trạm S_1] ───────────────●──────────────────────────► [Trạm S_2] ───► [Trạm S_3] ───► [Trạm Đích S_K]
 ├──── d_traveled ────────┤├──── d_remaining ─────────┤
 └───────────────── Tổng chiều dài L_1 ───────────────┘
  ◄──────────── CHẶNG DỞ DANG (PARTIAL) ──────────────► ◄──── CÁC CHẶNG NGUYÊN VẸN (FULL) ────►
```

### 2.1. Phân rã hành trình:
$$\text{Lộ trình} = \text{Phần dở dang của Chặng 1} + \sum_{k=2}^{K} \text{Chặng nguyên vẹn } k$$

### 2.2. Công thức tính thời gian chạy nốt phần dở dang ($T_{partial}$):
Gọi:
- $L_1$: Chiều dài toàn bộ Chặng 1 (mét).
- $d_{remaining} = L_1 - d_{traveled}$: Quãng đường còn lại của Chặng 1 tới Trạm $S_2$ (mét).
- Tỷ lệ quãng đường còn lại: $\alpha = \frac{d_{remaining}}{L_1} \in (0.0, 1.0]$.
- $v_{current\_smoothed}$: Vận tốc EMA hiện tại của xe từ ping GPS gần nhất (km/h).
- $\hat{\Delta T}_{delay}(1)$: Độ trễ toàn chặng do ML dự đoán cho Chặng 1.

Thời gian để xe hoàn tất phần dở dang của Chặng 1:

$$T_{partial} = \underbrace{\frac{d_{remaining}}{\max(v_{current\_smoothed}, 3.0) \times \frac{1}{3.6}}}_{\text{Thời gian vật lý theo trớn chạy hiện tại}} + \underbrace{\alpha \cdot \hat{\Delta T}_{delay}(1)}_{\text{Độ trễ kẹt xe tỷ lệ với đoạn còn lại}}$$

- **Nếu xe đang bon bon ($v = 30\text{ km/h}$)**: Xe lướt nốt phần còn lại rất nhanh theo đúng vận tốc thật.
- **Nếu xe đang bò ($v = 0$ do đèn đỏ)**: Mẫu số được chặn dưới bởi $3.0\text{ km/h}$ để không bị chia cho 0, và phần trễ $\hat{\Delta T}$ sẽ bù đắp chính xác thời gian chờ đèn.

### 2.3. Công thức tổng hợp ETA toàn tuyến:

$$\mathbf{ETA} = T_{partial} + \sum_{k=2}^{K} \Big( T_{base}(k) + \hat{\Delta T}_{delay}(k) \Big)$$

---

## 3. Khai Phá Baseline Đường Thông Thoáng $T_{base}(k)$ Từ Dữ Liệu Thật

Tuyệt đối không dùng công thức giả định $d/v + \tau$. Toàn bộ $T_{base}(k)$ được khai phá trực tiếp từ dữ liệu cào:

$$T_{base}(k) = \text{Quantile}_{0.15}\Big( \{ T_{obs}(k) \mid t \in \text{Giờ vắng (05h-06h, 12h-13h, 21h-22h)} \} \Big)$$

- Tự động bao hàm thời gian đón khách đông/vắng tự nhiên của từng trạm.
- Tự động bao hàm độ dốc, khúc cua, nhịp đèn tín hiệu cơ sở của chặng.

---

## 4. Đặc Tả Chi Tiết 24 Chiều Đặc Trưng Của Mô Hình Học Máy

Mô hình dự đoán: $\mathbf{\hat{\Delta T}_{delay}(k)} = f(X_k)$.

### Nhóm 1: Thuộc Tính Không Gian Của Chặng (Static Segment) — 5 Chiều
1. `segment_length_m` (float): Chiều dài tim đường thực tế của chặng (mét).
2. `road_quality_index` (float: 0.0 - 1.0): **Chỉ số Chất lượng Mặt đường & Ma sát Hạ tầng** ($Q_{road} = v_{base} / v_{limit}$, phản ánh đường gồ ghề, nắp cống, gờ giảm tốc).
3. `road_class` (int: 1, 2, 3): Phân loại cấp đường (1: Phố hẹp hỗn hợp; 2: Đại lộ dải phân cách; 3: Cầu vượt/Hầm chui).
4. `tomtom_coverage_ratio` (float: 0.0 - 1.0): **Tỷ lệ bao phủ của nút TomTom trên chặng** ($L_{overlap\_m} / L_{segment\_m}$). Đo mức độ chặng bị chiếm bởi nút giao nghẽn (thay thế cờ nhị phân thô thiển).
5. `target_stop_historical_dwell_sec` (float): **Thời gian dừng đón khách lịch sử tại trạm đích** $S_{i+1}$ (giây, tính từ trung vị thời gian dừng thực tế của trạm đó). Phân biệt rành mạch giữa trạm trung chuyển lớn (ĐH Bách Khoa: 45s) và trạm nhỏ ven đường (12s). (Thay thế biến vô nghĩa `num_stops_in_segment` vốn luôn bằng 1).

### Nhóm 2: Động Học Xe & Vị Trí Hành Trình (Kinematics & Route) — 4 Chiều
6. `route_progress_ratio` (float: 0.0 - 1.0): Tiến độ hoàn thành trên toàn tuyến ($s / L_{tổng}$).
7. `v_entry_smoothed` (float): Vận tốc EMA khi bắt đầu chạm vạch đầu chặng (km/h).
8. `entry_acceleration` (float): Gia tốc lúc vào chặng ($v_{entry} - v_{prev}$, $\text{m/s}^2$).
9. `entry_stopped_duration` (float): Thời gian xe đã đứng yên tại chỗ ngay trước khi vào chặng (giây).

### Nhóm 3: Tương Tác Đội Xe & Giãn Cách Biểu Đồ (Fleet Regularity) — 4 Chiều
10. `headway_ratio` (float): Tỷ lệ giãn cách thực tế / Giãn cách biểu đồ ($H_{actual} / H_{scheduled}$). Nhận diện dính chùm (Bus bunching $< 0.5$) hoặc quá tải khách ($> 1.5$).
11. `lead_bus_delay` (float): Độ trễ $\Delta T_{delay}$ của xe buýt cùng tuyến chạy trước nó tại chính chặng này (giây).
12. `lead_bus_speed` (float): Vận tốc thực tế của xe đi trước khi chạy qua chặng này (km/h).
13. `lead_bus_age_min` (float): Xe đi trước đã rời chặng này cách đây bao nhiêu phút.

### Nhóm 4: Bối Cảnh Dòng Chảy TomTom & Sự Cố (Traffic Context) — 4 Chiều
14. `downstream_tomtom_ratio` (float: 0.0 - 1.0): Tỷ lệ $v_{current} / v_{free}$ của nút TomTom thuộc/phía trước chặng này.
15. `tomtom_delay_contrib` (float): **Độ trễ TomTom thực tế đóng góp trên chiều dài giao cắt $L_{overlap}$** (giây):
    $$\Delta t_{tomtom\_contrib} = L_{overlap\_m} \times \left( \frac{1}{v_{tomtom\_current}} - \frac{1}{v_{free\_flow}} \right)$$
16. `incident_impact_penalty` (float): Độ trễ tai nạn/ngập úng ảnh hưởng trực tiếp đến chặng:
    $$\text{penalty} = \frac{\text{delay\_sec}}{1 + \left(\frac{d_{incident}}{300\text{m}}\right)^2}$$
17. `corridor_congestion_index` (float: 0.0 - 1.0): Tỷ lệ xe buýt trên toàn hành lang Bách Khoa đang chạy $< 10\text{ km/h}$.

### Nhóm 5: Chu Kỳ Thời Gian Đô Thị (Temporal Cycles) — 5 Chiều
18. `time_sin`: $\sin(2\pi \cdot \text{minute\_of\_day} / 1440)$
19. `time_cos`: $\cos(2\pi \cdot \text{minute\_of\_day} / 1440)$
20. `day_sin`: $\sin(2\pi \cdot \text{day\_of\_week} / 7)$
21. `day_cos`: $\cos(2\pi \cdot \text{day\_of\_week} / 7)$
22. `is_weekend` (binary: 0 hoặc 1): Cờ thứ 7 & Chủ Nhật.

### Nhóm 6: Thời Tiết & Tác Động Mặt Đường (Weather Impact) — 2 Chiều
23. `precipitation_mm` (float): Lượng mưa tức thời thời gian thực (mm/h, từ Open-Meteo).
24. `rain_accumulation_30m` (float): Lượng mưa tích lũy trong 30 phút gần nhất (mm). Đo độ ướt trơn trượt và ngập trũng kéo dài sau mưa.

---

## 5. Quy Tắc Tiền Xử Lý: Loại Bỏ Hoàn Toàn Xe Detour Khỏi ML

- **Tiêu chuẩn phát hiện**: Khoảng cách vuông góc từ xe tới tim đường $|d_{\perp}| > 80\text{m}$ liên tục trong 2 ping liên tiếp.
- **Quy tắc huấn luyện**: Toàn bộ các ping bị Detour bị **loại bỏ 100%** khỏi tập train của mô hình $\Delta T_{delay}$ để không làm nhiễu dữ liệu chuẩn.
- **Quy tắc phục vụ (Inference)**: Nếu phát hiện xe đang detour, hệ thống hiển thị cảnh báo: *"Xe đang chạy lộ trình tránh đường"* và dùng thuật toán fallback vận tốc động học tức thời, không cố ép ML dự đoán.

