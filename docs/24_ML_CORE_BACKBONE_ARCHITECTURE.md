# 24. KIẾN TRÚC MÔ HÌNH HỌC MÁY CỐT LÕI & ĐỘNG CƠ SUY LUẬN ETA (ML CORE BACKBONE & INFERENCE ENGINE SPECIFICATION)

> **Mục tiêu tài liệu:** Đóng băng (Freeze) toàn bộ thiết kế kiến trúc Machine Learning của hệ thống dự đoán thời gian xe buýt đến trạm (ETA) Hà Nội sau các vòng phản biện chuyên sâu. Đây là bản đặc tả kỹ thuật tối hậu (Final Blueprint) làm cơ sở cho giai đoạn ETL, Feature Engineering và Huấn luyện mô hình.

---

## 1. TRIẾT LÝ THIẾT KẾ & ĐỊNH NGHĨA BÀI TOÁN

```text
               HÀNH TRÌNH TỪ VỊ TRÍ HIỆN TẠI TỚI TRẠM ĐÍCH
┌─────────────────────────────────┬────────────────────────────────────────────────────────┐
│   Chặng dở dang hiện tại (k=1)  │         Chuỗi các chặng nguyên vẹn tiếp theo           │
│   (Vị trí xe hiện tại -> S_2)   │           (S_2 -> S_3 -> ... -> S_K)                   │
├─────────────────────────────────┼────────────────────────────────────────────────────────┤
│     T_partial (Convex Blend)    │   ∑ [ T_base(k) + ΔT_delay(k) ] (Dynamic Propagation)  │
└─────────────────────────────────┴────────────────────────────────────────────────────────┘
```

### 1.1. Bốn nguyên lý kiến trúc bất biến
1. **Mô hình Hồi quy Độ trễ Phân đoạn (Segment Delay Residual Modeling):**
   - Mô hình không dự đoán toàn tuyến 1-shot (tránh bùng nổ không gian trạng thái).
   - Mô hình không cuộn vi mô 60s (tránh trôi dạt sai số tích lũy nhân dồn).
   - Đơn vị dự đoán chuẩn là **chặng Trạm-đến-Trạm ($S_i \to S_{i+1}$)**, chiều dài tự nhiên $400\text{m} - 700\text{m}$.
   - Mục tiêu dự đoán là độ trễ dôi dư do giao thông:
     $$y_k = \Delta T_{delay}(k) = T_{actual}(k) - T_{base}(k) \ge 0 \quad (\text{giây})$$

2. **Độc lập Tuyến 100% (Route-Agnostic Paradigm):**
   - Không sử dụng `route_id` làm đặc trưng đầu vào.
   - Một mô hình LightGBM duy nhất học quy luật ứng xử vật lý của dòng giao thông và hành vi đội xe trên toàn bộ 19 tuyến hành lang.

3. **Khai phá Baseline $T_{base}(k)$ Bất biến từ Tập Train:**
   - $T_{base}(k) = \text{Quantile}_{0.15}\big(\{ T_{obs}(k) \mid t \in \text{Giờ vắng (5h-6h, 12h-13h, 21h-22h trong Train Set)} \}\big)$.
   - $T_{base}$ tự động hấp thụ: dwell time dừng đón khách cơ sở, số nhịp đèn tín hiệu tĩnh, khúc cua, gờ giảm tốc và độ dốc của chặng.

4. **Triệt tiêu Hoàn toàn Leakage & Magic Numbers:**
   - Thay thế toàn bộ hệ số nhân cảm tính bằng lý thuyết toán học chuẩn xác (**Tweedie Loss, Conformal Residuals, Convex Kinematic Blending**).

---

## 2. KHUNG TOÁN HỌC & CÔNG THỨC SUY LUẬN TỐI HẬU

### 2.1. Giải thuật Chặng dở dang $T_{partial}$ (Triệt tiêu Double-Counting)
Khi xe đang ở giữa chặng 1, cách trạm tiếp theo $d_{remaining}$, tỷ lệ quãng đường còn lại là $\alpha = \frac{d_{remaining}}{L_1} \in (0.0, 1.0]$.

Thời gian hoàn tất phần dở dang được mô hình hóa bằng **phép pha trộn lồi (Convex Blending)** giữa trớn động học tức thời và dự báo vĩ mô của mô hình:

$$\mathbf{T_{partial}} = (1 - \alpha) \cdot \underbrace{\frac{d_{remaining}}{\max(v_{current\_smoothed}, 3.0) \times \frac{1}{3.6}}}_{\text{Trớn động học tức thời (gần trạm đích)}} + \alpha \cdot \underbrace{\left( \alpha \cdot \left[ T_{base}(1) + \hat{\Delta T}_{delay}(1) \right] \right)}_{\text{Ước lượng vĩ mô (vừa rời trạm gốc)}}$$

- **Khi xe vừa rời trạm $S_1$ ($\alpha \to 1$):** Trọng số nghiêng trọn vẹn về dự báo của mô hình $\alpha \cdot (T_{base} + \hat{\Delta T})$.
- **Khi xe đã áp sát trạm $S_2$ ($\alpha \to 0$):** Trọng số chuyển mượt sang động học tức thời của xe $\frac{d_{remaining}}{v_{current}}$.
- **Triệt tiêu triệt để hiện tượng phạt trễ hai lần (Double-Counting) khi xe đang bò chậm trong đám tắc.**

### 2.2. Lan truyền Pha Thời gian Động (Dynamic Timestamp Propagation)
Khi hành khách tra cứu một chuyến xe cách xa $K$ trạm (thời gian chạy tới 30–50 phút), điều kiện giao thông tại các chặng xa sẽ biến thiên theo thời gian.

Quy trình giải mã tuần tự dọc theo tuyến:
1. **Chặng dở dang $k=1$:**
   $$t_{est}(1) = t_{now} + T_{partial}$$
2. **Các chặng tiếp theo $k = 2, 3, \dots, K$:**
   $$t_{est}(k) = t_{est}(k-1) + T_{base}(k-1) + \hat{\Delta T}_{delay}(k-1)$$
   - Các đặc trưng thời gian của chặng $k$ được tính toán trực tiếp từ mốc thời gian đến dự kiến $t_{est}(k)$:
     $$\text{time\_sin}_k = \sin\left(\frac{2\pi \cdot \text{minute}(t_{est}(k))}{1440}\right), \quad \text{time\_cos}_k = \cos\left(\frac{2\pi \cdot \text{minute}(t_{est}(k))}{1440}\right)$$
   - Điều này đảm bảo: Nếu xe đến chặng 10 đúng vào khung 17h15 (đỉnh cao điểm tan tầm), mô hình sẽ kích hoạt đúng đặc trưng cao điểm thay vì lấy giờ hiện tại (16h40).

### 2.3. Tổng hợp ETA Toàn Tuyến & Lớp Hiển Thị An Toàn (Conformalized Display)
Tổng thời gian kỳ vọng nội bộ:
$$\mathbf{ETA_{expected}} = T_{partial} + \sum_{k=2}^{K} \Big( T_{base}(k) + \mathbf{\hat{\Delta T}_{delay}(k)} \Big)$$

Để đảm bảo hành khách không bị lỡ xe do kỳ vọng quá lạc quan, lớp hiển thị sử dụng **Conformal Residual Quantile** được tính toán ngoại tuyến trên tập Validation:
- Tính sai số phần dư trên tập kiểm định: $e_i = y_{true, i} - \hat{y}_{pred, i}$.
- Trích xuất phân vị an toàn 80%: $\delta_{conformal} = \text{Quantile}_{0.80}(\{e_i\})$.
- Thời gian hiển thị trên ứng dụng hành khách:
  $$\mathbf{ETA_{display}} = \mathbf{ETA_{expected}} + \sqrt{K} \cdot \delta_{conformal}$$
  *(Sai số cộng dồn theo quy luật bước ngẫu nhiên $\sqrt{K}$ của chuỗi chặng độc lập tương đối).*

---

## 3. BỘ 23 CHIỀU ĐẶC TRƯNG CHUẨN HÓA (CANONICAL 23-D VECTOR)

```text
Vector Đặc Trưng Đầu Vào X_k (23 Chiều Route-Agnostic)
├── Nhóm 1: Hạ Tầng & Mặt Đường Vật Lý     [5 chiều]
├── Nhóm 2: Hướng Tuyến & Vị Trí Hành Trình  [2 chiều]
├── Nhóm 3: Động Lực Học Xe & Quán Tính      [2 chiều]
├── Nhóm 4: Đội Xe & Cảm Biến Probe Đa Tuyến [5 chiều]
├── Nhóm 5: Tải Dòng Xe TomTom & Sự Cố       [3 chiều]
├── Nhóm 6: Chu Kỳ Thời Gian Đô Thị          [4 chiều]
└── Nhóm 7: Thời Tiết & Ngập Nước             [2 chiều]
```

### Chi tiết 23 đặc trưng

| STT | Tên đặc trưng | Kiểu | Miền giá trị | Bản chất nhân quả & Xử lý biên |
|:---:|:---|:---:|:---:|:---|
| **I** | **HẠ TẦNG & MẶT ĐƯỜNG** | | | |
| 1 | `segment_length_m` | float | $[150, 2000]$ | Chiều dài tim đường thực tế của chặng (mét). |
| 2 | `road_class` | int | $\{1, 2, 3\}$ | Cấp đường: 1 (phố hẹp hỗn hợp), 2 (đại lộ dải phân cách), 3 (cầu vượt/hầm). |
| 3 | `road_quality_index` | float | $(0.0, 1.0]$ | $Q_{road} = v_{base} / v_{limit}$. Đo độ gồ ghề, nắp cống, ma sát mặt đường. |
| 4 | `num_traffic_signals` | int | $\{0, 1, 2, 3\}$ | Số lượng nút giao có đèn tín hiệu trên chặng (xác suất dừng chờ chu kỳ đỏ). |
| 5 | `tomtom_coverage_ratio` | float | $[0.0, 1.0]$ | Tỷ lệ phủ của đoạn TomTom trên chặng ($L_{overlap} / L_{segment}$). |
| **II**| **HƯỚNG & TIẾN ĐỘ** | | | |
| 6 | `direction` | binary | $\{0, 1\}$ | Hướng chạy (0: Outbound, 1: Inbound) giải quyết thủy triều giao thông sáng/chiều. |
| 7 | `route_progress_ratio` | float | $[0.0, 1.0]$ | Tiến độ hành trình ($s / L_{total}$): Đầu bến ($0-0.2$), Xuyên tâm ($0.2-0.8$), Cuối bến ($0.8-1.0$). |
| **III**| **ĐỘNG LỰC HỌC XE** | | | |
| 8 | `v_current_momentum` | float | $[0.0, 60.0]$ | Vận tốc EMA của xe tại ping gần nhất (km/h). Đại diện cho trớn chạy tức thời. |
| 9 | `cumulative_trip_delay_sec` | float | $[0.0, 3600.0]$| Trễ tích lũy từ đầu chuyến (phản ánh áp lực nén khách & xu hướng ép ga bù giờ). |
| **IV**| **ĐỘI XE & PROBE ĐA TUYẾN**| | | |
| 10 | `headway_ratio` | float | $[0.2, 3.0]$ | $H_{actual} / H_{nominal}$. Nhận diện dính chùm (Bunching $<0.5$) hoặc rỗng chuyến ($>1.5$). |
| 11 | `has_lead_bus_probe` | binary | $\{0, 1\}$ | Cờ cold-start (0: Xe đầu ngày chưa có probe, 1: Có dữ liệu probe tin cậy). |
| 12 | `lead_bus_delay` | float | $[0.0, 1800.0]$| Độ trễ $\Delta T$ của xe cùng tuyến đi trước tại chặng này (NaN nếu cold-start). |
| 13 | `lead_bus_age_min` | float | $[1.0, 45.0]$ | Xe đi trước đã rời chặng này cách đây bao lâu (độ tươi thông tin). |
| 14 | `segment_cross_route_delay_30m`| float | $[0.0, 1800.0]$| Độ trễ trung bình của **mọi xe buýt khác tuyến** qua cặp trạm này trong 30p qua. |
| **V** | **TOMTOM & SỰ CỐ** | | | |
| 15 | `downstream_tomtom_ratio` | float | $[0.0, 1.0]$ | Tỷ lệ thông thoáng $v_{current} / v_{free}$ của nút TomTom thuộc chặng. |
| 16 | `tomtom_delay_contrib` | float | $[0.0, 600.0]$ | $L_{overlap} \times (1/\max(v_{tom}, 3.0) - 1/\max(v_{free}, 15.0)) \times 3.6$. Bị kẹp trần $\le 600\text{s}$. |
| 17 | `incident_impact_penalty` | float | $[0.0, 1800.0]$| Độ trễ phát sinh do ngập úng, tai nạn ghi nhận từ BBox TomTom (0 nếu không có). |
| **VI**| **CHU KỲ THỜI GIAN** | | | |
| 18 | `time_sin` | float | $[-1.0, 1.0]$ | $\sin(2\pi \cdot \text{minute\_of\_day} / 1440)$ tính theo thời điểm đến dự kiến $t_{est}(k)$. |
| 19 | `time_cos` | float | $[-1.0, 1.0]$ | $\cos(2\pi \cdot \text{minute\_of\_day} / 1440)$ tính theo thời điểm đến dự kiến $t_{est}(k)$. |
| 20 | `day_sin` | float | $[-1.0, 1.0]$ | $\sin(2\pi \cdot \text{day\_of\_week} / 7)$ đại diện chu kỳ tuần. |
| 21 | `is_weekend` | binary | $\{0, 1\}$ | Cờ ngày cuối tuần (Thứ 7 & Chủ Nhật có mô hình giao thông khác biệt). |
| **VII**| **THỜI TIẾT & ĐỘ ĐỌNG NƯỚC**| | | |
| 22 | `precipitation_mm` | float | $[0.0, 150.0]$ | Cường độ mưa tức thời thời gian thực (mm/h) từ Open-Meteo. |
| 23 | `rain_accumulation_30m` | float | $[0.0, 100.0]$ | Mưa tích lũy 30 phút gần nhất (đo trơn trượt mặt đường và ngập nước kéo dài). |

---

## 4. CẤU HÌNH MÔ HÌNH HỌC MÁY & HÀM MẤT MÁT

### 4.1. Lựa chọn Hàm Mất Mát: Tweedie Loss (Compound Poisson-Gamma)
Do phân phối độ trễ $\Delta T_{delay} \ge 0$ có khối lượng xác suất lớn tập trung tại 0 (~45% trường hợp đường thông thoáng không trễ) và có đuôi phải kéo dài (kẹt xe đột biến), **Tweedie Deviance với phương sai lũy thừa $p = 1.4$** là hàm mất mát tối ưu nhất:
- Không biến đổi Log $\implies$ **Triệt tiêu hoàn toàn cạm bẫy Bất đẳng thức Jensen**.
- Tự nhiên bảo đảm đầu ra không âm $\hat{y} \ge 0$.
- Gradient ổn định, kháng nhiễu cực tốt trước các điểm cực trị kẹt xe.

### 4.2. Siêu tham số Huấn Luyện LightGBM Chuẩn Mực
```python
LIGHTGBM_BACKBONE_PARAMS = {
    "objective": "tweedie",
    "tweedie_variance_power": 1.4,       # Phù hợp phân phối zero-inflated continuous
    "boosting_type": "gbdt",
    "num_leaves": 127,                   # Độ sâu biểu diễn mối quan hệ phi tuyến
    "max_depth": -1,
    "learning_rate": 0.03,
    "n_estimators": 3000,
    "min_child_samples": 200,            # Tránh overfit cho các chặng ít xe chạy
    "subsample": 0.8,                    # Bagging fraction
    "subsample_freq": 5,
    "colsample_bytree": 0.8,             # Feature fraction
    "reg_alpha": 0.1,                    # L1 Regularization
    "reg_lambda": 1.0,                   # L2 Regularization
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}
```

---

## 5. GIAO THỨC CHIA TẬP & BẢO VỆ CHỐNG RÒ RỈ DỮ LIỆU (ANTI-LEAKAGE PROTOCOL)

```text
  Ngày 1 ──────────────────────── Ngày 30     Ngày 31 ───────── Ngày 38     Ngày 39 ───────── Ngày 45
┌───────────────────────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
│              TRAIN SET                │ │    VALIDATION SET     │ │       TEST SET        │
│       (~2.0 - 2.2 triệu mẫu)          │ │    (~500 - 600k mẫu)  │ │   (~400 - 500k mẫu)   │
└───────────────────────────────────────┘ └───────────────────────┘ └───────────────────────┘
                                         ▲                         ▲
                                  [PURGE GAP 6H]            [PURGE GAP 6H]
```

### Ba quy tắc cô lập nghiêm ngặt:
1. **Phân vùng thời gian tuyệt đối (Time-based Split with 6-Hour Purge Gap):**
   - Không dùng K-Fold ngẫu nhiên.
   - Giữa Train và Validation chèn khoảng trống 6 giờ để cắt đứt hoàn toàn sự rò rỉ của đặc trưng trễ trượt `segment_cross_route_delay_30m`.
2. **Lagging cứng cho đặc trưng tổng hợp:**
   - Khi tính toán `segment_cross_route_delay_30m` tại thời điểm $t_{now}$, chỉ được tổng hợp dữ liệu từ các chuyến xe đã hoàn thành trước $t_{now} - 1\text{ phút}$.
3. **Khai phá Baseline $T_{base}(k)$ khép kín:**
   - Giá trị $T_{base}(k)$ của toàn bộ mạng lưới **bắt buộc chỉ được tính toán từ dữ liệu nội bộ của TRAIN SET**. Cấm tuyệt đối việc dùng dữ liệu toàn bộ 45 ngày để tính $T_{base}$.

---

## 6. XỬ LÝ BIÊN & VẬN HÀNH THỜI GIAN THỰC (EDGE CASES & SERVING)

### 6.1. Cold-Start (Chuyến xe đầu ngày lúc 05:00 sáng)
- Khi chưa có xe đi trước:
  - `has_lead_bus_probe = 0`
  - `lead_bus_delay = np.nan`
  - `lead_bus_age_min = np.nan`
  - `segment_cross_route_delay_30m = np.nan`
- **Cơ chế xử lý:** Tận dụng 100% thuật toán **Native Missing Value Handling của LightGBM**. Mô hình tự động phân nhánh học các quy luật prior thống kê khi vắng mặt tín hiệu probe mà không bị thiên lệch bởi các giá trị gán 0 nhân tạo.

### 6.2. Phát hiện & Xử lý Xe Chạy Tránh Tuyến (Detour Handling)
- Khi khoảng cách vuông góc từ xe tới tim đường hình học chặng $|d_{\perp}| > 80\text{m}$ liên tiếp 2 ping:
  - **Lúc Train:** Loại bỏ 100% các mẫu này khỏi tập huấn luyện.
  - **Lúc Serve:** Tạm ngắt mô hình ML, hiển thị cờ *"Xe đang đi đường tránh"* và chuyển sang ước lượng theo vận tốc động học thuần túy.

### 6.3. Giới hạn Độ Trễ Phục Vụ (Serving SLA)
- Vector đặc trưng 23 chiều được chuẩn bị thông qua bảng tra cứu trước (Precomputed Lookups).
- Thời gian suy luận 1 lượt cho hành trình $K = 25$ chặng trên CPU:
  $$\tau_{inference} = 25 \times 0.03\text{ms} \approx \mathbf{0.75\text{ms}} \ll 100\text{ms} \quad (\text{Đạt chuẩn thời gian thực tuyệt đối}).$$

---

## 7. KẾT LUẬN & TRẠNG THÁI ĐÓNG BĂNG

> **XÁC NHẬN ĐÓNG BĂNG KIẾN TRÚC ML (ARCHITECTURE FROZEN):**
> Toàn bộ logic phân đoạn chặng, công thức toán học chặng dở dang, bộ 23 đặc trưng, hàm mất mát Tweedie và giao thức chống rò rỉ dữ liệu đã được chốt hạ hoàn toàn tại văn bản này.
> 
> **BƯỚC TIẾP THEO CỦA DỰ ÁN:**
> Chuyển toàn bộ trọng tâm sang **Kỹ nghệ Tiền xử lý Dữ liệu Thô (Data Cleaning, Map-Matching, ETL Parquet Pipeline)** theo đúng lộ trình đã vạch ra tại `docs/20_DATA_PROCESSING_AND_ETA_PIPELINE_ROADMAP.md`.
