# 22. HỒ SƠ THAM VẤN CHUYÊN GIA ML: MÔ HÌNH HÓA ĐỘ TRỄ PHÂN ĐOẠN XE BUÝT HÀ NỘI (ML EXPERT CONSULTATION DOSSIER & PROMPT SCRIPT)

> **Mục đích tài liệu:** Tài liệu này tổng hợp toàn bộ bối cảnh dự án, kiến trúc dữ liệu thực tế và thiết kế mô hình học máy hiện tại. Phần cuối tài liệu được đóng gói thành **Lời kịch bản (Prompt Script) chuẩn mực** để gửi trực tiếp cho Chuyên gia Học Máy (Machine Learning Engineer / Transport AI Specialist) hoặc mô hình AI cấp cao (GPT-4 / Claude Opus / Gemini Pro) nhằm lấy phản biện chuyên sâu.

---

# PHẦN 1: TỔNG QUAN HỆ THỐNG & DỮ LIỆU THỰC TẾ ĐANG CÓ

### 1.1. Bối cảnh dự án
Hệ thống giám sát và dự đoán thời gian xe buýt đến trạm (ETA) cho **19 tuyến xe buýt hành lang trọng điểm** kết nối qua Đại học Bách Khoa Hà Nội (mạng lưới gồm **220 xe buýt hoạt động liên tục từ 05:00 đến 22:00 hàng ngày** trong 45 – 60 ngày). Hệ thống vận hành $0$ đồng trên hạ tầng hybrid: GitHub Actions (chạy chu kỳ 9 phút liên hoàn) và điện thoại Android Termux (chạy nền 24/7).

### 1.2. Ba nguồn dữ liệu thô thu thập 24/7
1. **Dữ liệu Telemetry Xe buýt (BusMap API — Tần suất 60s/vòng)**:
   - Tọa độ GPS chuẩn hóa WGS84 (đã sửa lỗi đảo Lat/Lon của API).
   - Vận tốc động học thực tế ($v_{calc} = \Delta d / \Delta t$) kết hợp bộ lọc làm mịn hàm mũ (EMA Filter, $\alpha = 0.65$), loại bỏ hoàn toàn vận tốc rác của cảm biến.
   - Nhãn kiểm soát chất lượng: Gắn cờ xe đỗ bãi (`IDLE_DEPOT`), xe bay ra khỏi Hà Nội (`OUT_OF_BOUNDS`), nhảy cóc GPS phi vật lý $> 80\text{ km/h}$ (`GPS_DRIFT_JUMP`), ping lặp do xe đứng chờ nhịp GPS (`STALE_PING`).
2. **Dữ liệu Giao thông & Điểm nghẽn (TomTom Traffic API — Quota Freemium 20.000 call/tháng)**:
   - 19 điểm nút giao cổ chai cố định bao quanh hành lang Bách Khoa (`HUST_BOTTLENECK_NODES`): Trả về vận tốc thực tế $v_{current}$, vận tốc thông thoáng $v_{free\_flow}$, thời gian qua nút, và polyline của đoạn nghẽn.
   - 1 Bounding Box sự cố (`HUST_CORRIDOR_BBOX`): Ghi nhận tai nạn, ngập úng, thi công và độ trễ phát sinh (`delay_sec`).
   - Tần suất quét linh hoạt: 18 phút (khi kẹt xe hoặc giờ cao điểm) và 54 phút (giờ thấp điểm).
3. **Dữ liệu Thời tiết Mở (Open-Meteo API — Miễn phí, cập nhật theo giờ)**:
   - Lượng mưa tức thời `precipitation_mm` (mm/h) và lượng mưa tích lũy 30 phút gần nhất `rain_accumulation_30m` (mm).

---

# PHẦN 2: THIẾT KẾ BÀI TOÁN & CÔNG THỨC TOÁN HỌC

### 2.1. Phân rã bài toán: Tránh hai cực đoan
- **Không dùng Rollout vi mô 60s**: Dự đoán từng phút rồi cuộn liên tiếp sẽ làm sai số nhân dồn theo hàm mũ (Compounding Error / Drift), khiến kết quả trôi dạt vô cực sau 10 – 15 bước.
- **Không dùng hồi quy 1-shot toàn tuyến**: Dự đoán thẳng thời gian từ điểm bất kỳ đến trạm đích có không gian trạng thái quá rộng, độ bất định lớn, khó hội tụ.
- **Giải pháp lựa chọn: Mô hình Hồi quy Độ trễ Phân đoạn (Segment-Level Delay Residual Modeling)**.

### 2.2. Phân đoạn tuyến (Segmentation Strategy)
- Khung xương phân đoạn dựa trên **Trạm dừng (Inter-Stop Segments)**: Tuyến xe buýt được chia thành các chặng $k = (S_i \to S_{i+1})$, dài trung bình **$400\text{m} - 700\text{m}$** (thời gian chạy $1.5 - 3\text{ phút}$).
- Dữ liệu TomTom được **tiền xử lý giao cắt không gian ngoại tuyến (Offline Spatial Intersection)**: Xác định sẵn chiều dài giao cắt $L_{overlap}$ giữa chặng buýt và đoạn TomTom đo.

### 2.3. Khai phá Baseline đường thông thoáng $T_{base}(k)$
Không dùng công thức giả định $d/v + \tau$. Toàn bộ thời gian cơ sở khi đường vắng được khai phá trực tiếp từ dữ liệu cào 5h sáng:
$$T_{base}(k) = \text{Quantile}_{0.15}\Big( \{ T_{obs}(k) \mid t \in \text{Khung giờ vắng} \} \Big)$$
$T_{base}(k)$ tự động hấp thụ toàn bộ độ gồ ghề, khúc cua, nhịp đèn tín hiệu cơ sở và thời gian dừng đón khách tự nhiên tại trạm $S_{i+1}$.

### 2.4. Công thức dự đoán và xử lý chặng dở dang (Partial Segment)
Thời gian xe hoàn tất chặng dở dang hiện tại $k=1$ (xe đang cách trạm tiếp theo $d_{remaining}$, tỷ lệ $\alpha = d_{remaining} / L_1$):
$$T_{partial} = \frac{d_{remaining}}{\max(v_{current\_momentum}, 3.0) \times \frac{1}{3.6}} + \alpha \cdot \hat{\Delta T}_{delay}(1)$$

Tổng thời gian dự kiến tới trạm đích $S_K$:
$$\mathbf{ETA} = T_{partial} + \sum_{k=2}^{K} \Big( T_{base}(k) + \mathbf{\hat{\Delta T}_{delay}(k)} \Big)$$

- **Đầu ra mục tiêu của ML ($y$)**: $\mathbf{\Delta T_{delay}(k)} = T_{thực\_tế}(k) - T_{base}(k) \ge 0$ (Độ trễ phát sinh do tắc đường, mưa, đèn đỏ).

---

# PHẦN 3: ĐẶC TẢ BỘ ĐẶC TRƯNG 23 CHIỀU (ROUTE-AGNOSTIC)

Mô hình được thiết kế **Độc lập Tuyến 100% (Route-Agnostic)** để một mô hình duy nhất có thể học và phục vụ trên toàn bộ mạng lưới:

| STT | Tên đặc trưng | Kiểu | Ý nghĩa nhân quả (Causality) |
| :---: | :--- | :---: | :--- |
| **I** | **HẠ TẦNG & HÌNH HỌC CHẶNG** | | |
| 1 | `segment_length_m` | float | Chiều dài tim đường thực tế của chặng (mét). |
| 2 | `road_class` | int (1, 2, 3) | Cấp đường: 1 (phố hẹp hỗn hợp), 2 (đại lộ dải phân cách), 3 (cầu vượt/hầm chui). |
| 3 | `road_quality_index` | float $[0, 1]$ | Chỉ số chất lượng mặt đường & ma sát hạ tầng ($Q_{road} = v_{base} / v_{limit}$). |
| 4 | `num_traffic_signals` | int (0, 1, 2) | Số lượng nút giao có đèn tín hiệu trên chặng (đo xác suất phải dừng chờ đèn $60\text{s}$). |
| 5 | `tomtom_coverage_ratio` | float $[0, 1]$ | Tỷ lệ bao phủ của nút TomTom trên chặng ($L_{overlap} / L_{segment}$). |
| **II** | **HƯỚNG TUYẾN & TIẾN ĐỘ HÀNH TRÌNH** | | |
| 6 | `direction` | binary (0, 1) | **Hướng xe chạy (0: Chiều đi, 1: Chiều về)**: Giải quyết bất đối xứng dòng xe thủy triều sáng/chiều! |
| 7 | `route_progress_ratio` | float $[0, 1]$ | Tiến độ trên toàn tuyến ($s / L_{tổng}$): Đầu bến ($0-0.2$), Lõi xuyên tâm ($0.2-0.8$), Cuối bến ($0.8-1.0$). |
| **III** | **ĐỘNG HỌC XE & QUÁN TÍNH CHUYẾN ĐI** | | |
| 8 | `v_current_momentum` | float (km/h) | Vận tốc EMA của xe tại thời điểm bắt đầu xét chặng (động lượng và trớn chạy). |
| 9 | `cumulative_trip_delay_sec` | float (giây) | Độ trễ lũy kế của toàn chuyến xe từ đầu bến (phản ánh lượng khách nén trên xe & tâm lý tài xế bù giờ). |
| **IV** | **ĐỘI XE & CẢM BIẾN PROBE ĐA TUYẾN** | | |
| 10 | `headway_ratio` | float | Tỷ lệ giãn cách $H_{actual} / H_{sched}$ (Nhận diện xe dính chùm $< 0.5$ hoặc xe bị bỏ xa $> 1.5$). |
| 11 | `has_lead_bus_probe` | binary (0, 1) | Cờ có xe probe đi trước hay không (0: Xe đầu ngày / Cold-start, 1: Có dữ liệu). |
| 12 | `lead_bus_delay` | float (giây) | Độ trễ $\Delta T_{delay}$ của xe buýt cùng tuyến chạy trước tại chặng này ($= 0$ nếu không có probe). |
| 13 | `lead_bus_age_min` | float (phút) | Xe đi trước đã rời chặng này cách đây bao lâu (đo độ tươi của cảm biến probe). |
| 14 | `segment_cross_route_delay_30m`| float (giây) | Độ trễ trung bình của **mọi xe buýt** (bất kỳ tuyến nào) qua chặng này trong 30 phút qua. |
| **V** | **BỐI CẢNH TOMTOM & SỰ CỐ** | | |
| 15 | `downstream_tomtom_ratio` | float $[0, 1]$ | Tỷ lệ tắc TomTom phía trước chặng ($v_{current} / v_{free}$). |
| 16 | `tomtom_delay_contrib` | float (giây) | Độ trễ TomTom thực tế đóng góp trên chiều dài giao cắt: $L_{overlap} \times (1/v - 1/v_{free})$. |
| 17 | `incident_impact_penalty` | float (giây) | Độ trễ sự cố ngập úng/tai nạn ảnh hưởng trực tiếp đến chặng (bằng 0 nếu không có sự cố). |
| **VI** | **CHU KỲ THỜI GIAN ĐÔ THỊ** | | |
| 18 | `time_sin` | float | $\sin(2\pi \cdot \text{minute\_of\_day} / 1440)$ — Chu kỳ phút trong ngày. |
| 19 | `time_cos` | float | $\cos(2\pi \cdot \text{minute\_of\_day} / 1440)$. |
| 20 | `day_sin` | float | $\sin(2\pi \cdot \text{day\_of\_week} / 7)$ — Chu kỳ ngày trong tuần. |
| 21 | `is_weekend` | binary (0, 1) | Cờ thứ 7 & Chủ Nhật. |
| **VII**| **THỜI TIẾT & TÁC ĐỘNG MẶT ĐƯỜNG** | | |
| 22 | `precipitation_mm` | float (mm/h) | Lượng mưa thực tế thời gian thực tại Hà Nội (từ Open-Meteo). |
| 23 | `rain_accumulation_30m` | float (mm) | Lượng mưa tích lũy trong 30 phút gần nhất (đo độ trơn trượt mặt đường & ngập trũng kéo dài). |

---

# PHẦN 4: LỜI KỊCH BẢN PROMPT THAM VẤN CHUYÊN GIA ML (COPY & PASTE SCRIPT)

> *Bạn hãy sao chép toàn bộ phần khung bên dưới để gửi cho chuyên gia AI hoặc giáo viên hướng dẫn:*

```text
Chào Chuyên gia Machine Learning và Kỹ nghệ Giao thông Thông minh (ITS),

Tôi đang xây dựng hệ thống dự đoán thời gian xe buýt đến trạm (ETA) thời gian thực cho 19 tuyến hành lang trọng điểm tại Hà Nội (220 xe buýt, cào dữ liệu 24/7 trong 45 ngày). Dữ liệu gồm: GPS xe buýt 60s, TomTom Traffic API (19 nút nghẽn + BBox sự cố), và Open-Meteo Weather API.

Sau nhiều vòng tranh biện kỹ thuật, chúng tôi đã đưa ra kiến trúc thiết kế như sau:

1. ĐỊNH NGHĨA BÀI TOÁN & MỤC TIÊU:
- Phân đoạn tuyến thành các chặng Trạm-đến-Trạm cố định k = (S_i -> S_{i+1}), dài trung bình 400m - 700m.
- Khai phá thời gian cơ sở đường thông thoáng T_base(k) = Quantile_0.15 của các chuyến xe thực tế lúc 5h sáng (đã tự động hấp thụ dwell time cơ sở và hình học tĩnh).
- Mô hình Machine Learning KHÔNG dự đoán toàn tuyến mà CHỈ dự đoán ĐỘ TRỄ DÔI DƯ:
  y = \Delta T_{delay}(k) = T_{thực_tế}(k) - T_{base}(k) >= 0 (đơn vị: giây).
- Khi xe đang ở giữa chặng dở dang, áp dụng công thức suy giảm theo tỷ lệ quãng đường còn lại alpha = d_remaining / L_1.
- Tổng ETA = T_{partial} + \sum (T_{base}(k) + \hat{\Delta T}_{delay}(k)).

2. THIẾT KẾ ĐẶC TRƯNG (23 CHIỀU ROUTE-AGNOSTIC):
Mô hình hoàn toàn độc lập với mã tuyến (route_id) để dùng chung cho toàn mạng lưới:
- Hạ tầng chặng (5 chiều): segment_length_m, road_class (1-3), road_quality_index (v_base/v_limit), num_traffic_signals, tomtom_coverage_ratio (L_overlap/L).
- Hướng & Vòng đời (2 chiều): direction (0: chiều đi, 1: chiều về để xử lý kẹt xe thủy triều sáng/chiều), route_progress_ratio (tiến độ trên tuyến [0, 1]).
- Động học & Quán tính chuyến (2 chiều): v_current_momentum (vận tốc EMA hiện tại), cumulative_trip_delay_sec (trễ lũy kế từ đầu bến phản ánh tải khách & tâm lý tài xế).
- Đội xe & Probe đa tuyến (5 chiều): headway_ratio (actual/scheduled - Bus bunching), has_lead_bus_probe (cờ cold-start), lead_bus_delay, lead_bus_age_min, segment_cross_route_delay_30m (trễ trung bình của mọi xe buýt qua chặng trong 30p qua).
- TomTom & Sự cố (3 chiều): downstream_tomtom_ratio, tomtom_delay_contrib = L_overlap * (1/v - 1/v_free), incident_impact_penalty.
- Chu kỳ thời gian (4 chiều): time_sin, time_cos, day_sin, is_weekend.
- Thời tiết (2 chiều): precipitation_mm, rain_accumulation_30m (mưa tích lũy 30p đo đọng nước/ngập).

XIN THAM VẤN CHUYÊN GIA 5 VẤN ĐỀ TRỌNG TÂM:

Câu hỏi 1: LỰA CHỌN MÔ HÌNH HỌC MÁY (MODEL SELECTION)
Với vector dạng bảng 23 chiều và kích thước tập dữ liệu khoảng 2 - 3 triệu mẫu, mô hình nào là tối ưu nhất giữa LightGBM, CatBoost, XGBoost, hay TabNet/MLP? Có nên sử dụng Stacking Ensemble không, hay một mô hình LightGBM đơn lẻ với điều chỉnh siêu tham số là đủ để đảm bảo độ trễ suy luận < 1ms?

Câu hỏi 2: HÀM MẤT MÁT (LOSS FUNCTION OPTIMIZATION)
Bài toán dự đoán độ trễ xe buýt có tính bất đối xứng: Người đi xe buýt ghét việc "dự đoán xe tới sau 5 phút nhưng 3 phút xe đã tới và bị lỡ xe" hơn là "xe tới trễ 2 phút". Chúng tôi nên dùng MSE, Huber Loss, hay Asymmetric Loss / Quantile Loss (Pinball Loss) với phân vị tau = 0.7 - 0.8 để dự đoán cận trên an toàn cho hành khách?

Câu hỏi 3: CHIẾN LƯỢC CHIA TẬP DỮ LIỆU & CHỐNG RÒ RỈ DỮ LIỆU (VALIDATION STRATEGY)
Để đánh giá mô hình khách quan nhất, chúng tôi nên chia Train / Validation / Test theo:
- Time-based Split (ví dụ: Train 30 ngày đầu, Test 15 ngày sau)?
- Blocked Cross-Validation (Purged Group Time Series Split)?
Làm thế nào để triệt tiêu hoàn toàn rò rỉ dữ liệu (Data Leakage) giữa các xe cùng tuyến chạy gần nhau trong cùng khung giờ?

Câu hỏi 4: XỬ LÝ GIÁ TRỊ THIẾU KHI COLD-START (IMPUTATION & EDGE CASES)
Khi xe chạy chuyến đầu tiên lúc 05:00 sáng, chưa có xe nào đi trước (lead_bus_delay = NaN, segment_cross_route_delay_30m = NaN). Chúng tôi đã thêm cờ has_lead_bus_probe = 0. Với các trường số bị thiếu, nên gán giá trị mặc định bằng 0, giá trị trung bình lịch sử, hay để LightGBM tự động xử lý giá trị NaN (LightGBM Native Missing Value Handling)?

Câu hỏi 5: THEO CHUYÊN GIA, CÒN BẤT KỲ ĐIỂM YẾU ẨN (LATENT PITFALL) HOẶC RỦI RO NÀO TRONG THIẾT KẾ TRÊN MÀ CHÚNG TÔI CHƯA NHÌN THẤY?

Rất mong nhận được phản biện chuyên sâu và lời khuyên quý báu từ Chuyên gia!
```
