# SPEC-15: ĐẶC TẢ TOÁN HỌC ĐỘNG HỌC VẬT LÝ, BÙ ĐẮP TRỄ VIỄN TRẮC & CHUẨN HÓA PHỤC VỤ THỜI GIAN THỰC (REAL-TIME PHYSICAL KINEMATICS & SERVING SPECIFICATION)

> Thiết kế giữ để tra hợp đồng; trạng thái/số liệu/giao diện gốc cần đối chiếu code/test. Xem [chỉ mục](README.md). Không tự thực thi phân công agent hoặc lệnh dọn file lịch sử.

> **Authority note (2026-11-10):** This is the current mathematical authority over SPEC-11--14. Server-side projection is permitted; BusMap-only, discrete browser behavior remains mandatory under [SPEC-04](04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md), so browser interpolation and TimBus remain prohibited.
## Document ID: `15_PHYSICAL_KINEMATICS_AND_SERVING_SPEC`

- **Tác giả:** `@architect` (Kinematics & System Architect)
- **Người thẩm định:** `@orchestrator`
- **Người thực thi triển khai:** `@leaf_coder`
- **Người nghiệm thu độc lập:** `@blind_tester` & `@peer_review`
- **Ngày ban hành:** 2026-11-09
- **Trạng thái:** BAN HÀNH CHÍNH THỨC (OFFICIAL SPECIFICATION - APPROVED FOR IMPLEMENTATION)
- **Căn cứ pháp lý & kỹ thuật:**
  - `AGENTS.md` (Constitutional Invariants: Think Before Coding - Simplicity First - Surgical Changes - Goal-Driven Execution)
  - `docs/specs/12_INDEPENDENT_CODE_AND_MATH_DEFECT_AUDIT.md` (Báo cáo Kiểm toán Mã nguồn & Toán học)
  - `docs/specs/13_INDEPENDENT_RUNTIME_TELEMETRY_AUDIT.md` (Thực nghiệm Trễ GPS BusMap 42s–79s trên 69 xe thực địa)
  - `docs/specs/14_PEER_REVIEW_CODER_MINDSET_AND_INVARIANTS_AUDIT.md` (Báo cáo Phản biện Độc lập về Lỗi tư duy & Bất biến Vật lý)
  - `docs/specs/08_STATION_ETA_MAP_INTEGRATION_SPEC.md` & `docs/specs/11_CONSERVATIVE_ASYMMETRIC_ETA_AND_UI_HYSTERESIS_SPEC.md`
  - `config/system_config.py` & `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/busmap_service.py`

---

## 1. TỔNG QUAN VẤN ĐỀ & BẢN CHẤT LỖI TƯ DUY HIỆN TẠI

### 1.1. Bối cảnh Kỹ thuật
Qua 3 đợt kiểm toán pháp y độc lập (DOC-12, DOC-13, DOC-14), hệ thống phục vụ dự báo thời gian đến của xe buýt (ETA Serving Pipeline) đã bộc lộ 4 điểm gãy đổ nghiêm trọng giữa lý thuyết toán học và thực tế vận hành trên đường phố Hà Nội:

1. **Điểm gián đoạn vách đá 10m (The 10m Cliff Discontinuity):**
   Mã nguồn sử dụng điều kiện loại trừ cứng `if s_bus >= s_target - 10.0: continue`. Hậu quả: Khi xe buýt tiến sát bến ở khoảng cách $d < 10\text{m}$, xe lập tức bị vứt bỏ khỏi danh sách tiếp cận, khiến ứng dụng chuyển trạng thái từ `~1 phút (15m)` sang `"Hiện chưa có xe nào... Giãn cách ~10-15 phút"`. Chiếc xe biến mất ngay trước mắt hành khách!
2. **Ảo giác Đóng băng Thời gian & Xe ma (Kinematic Freeze vs. Ghost Bus):**
   - Thay vì mô hình hóa chuyển động của xe trong khoảng thời gian trễ viễn trắc $\Delta t_{\text{age}} \in [40\text{s}, 90\text{s}]$, hệ thống giả định xe đứng yên bất động trong suốt $\Delta t_{\text{age}}$ và chỉ bắt đầu chạy tại thời điểm người dùng bấm xem (`now_epoch`), khiến ETA bị trôi nhân tạo vào tương lai.
   - Ngược lại, hệ thống không có ngưỡng ngắt gói tin cũ ($T_{\text{stale}}$), dẫn đến việc các xe đã tắt máy về bãi cách đây 10–30 phút vẫn được dự báo "đang chạy tới bến sau 3 phút", sinh ra hiện tượng "xe ma" ám ảnh hành khách.
3. **Mù quáng Hướng Vector La bàn (Heading Blindness on Divided Avenues):**
   Hệ thống chỉ kiểm tra khoảng cách hình chiếu trực giao $d_{\text{perp}} \le 35\text{m}$. Trên các đại lộ có dải phân cách giữa hẹp ($10\text{m} - 25\text{m}$) như Giải Phóng, Nguyễn Trãi, Quang Trung, xe buýt chạy chiều ngược lại bị nhận diện nhầm là xe đang tiến về trạm của chiều xuôi.
4. **Các trường DTO "Xác sống" & Mù ùn tắc nghiêm trọng (Zombie Fields & Jam Blindness):**
   Các trường `is_delayed = False` và `delay_seconds = 0.0` bị cắm chết bằng giá trị bù nhìn. Khi xe buýt kẹt cứng trong dòng phương tiện nhích từng mét ($0.5\text{ km/h}$, thực tế mất 45 phút mới tới bến), hệ thống vẫn thản nhiên tra bảng Baseline lịch sử và báo `"2 phút nữa xe tới"`.

### 1.2. Triết lý Thiết kế Cốt lõi của SPEC-15 (First-Principles Kinematics)
SPEC-15 giải quyết triệt để 4 lỗi trên bằng phương pháp luận **Vật lý Động học Nguyên bản (First-Principles Kinematics)**:
- Không dùng hàm clamp chắp vá (`floor_p50`, `delay_sec = 45.0s`).
- Mọi biến số và ngưỡng suy luận đều bắt nguồn từ thông số hình học phương tiện, đặc thù trạm dừng và động học giao thông thực địa Hà Nội.
- Đảm bảo tính liên tục Lipschitz của hàm khoảng cách và hàm thời gian trên toàn bộ miền xác định.

---

## 2. MÔ HÌNH TOÁN HỌC 1: BẮT BẾN & VÙNG CẬN BẾN (STATION CATCHMENT & TRANSITION)

### 2.1. Không gian Tọa độ Tim Tuyến Frenet 1D
Xét tim tuyến đường chuẩn (Canonical Route Centerline) biểu diễn bằng tập hợp các điểm tọa độ rời rạc trong mặt phẳng tiếp tuyến cục bộ WGS84:
$$\mathcal{C} = \{ (x_i, y_i, s_i) \}_{i=0}^{N-1}$$
Trong đó:
- $s_i$ là lý trình tích lũy (Cumulative Chainage) dọc theo tim tuyến, $s_0 = 0$, $s_N = L_{\text{route}}$ (mét).
- Với mỗi tọa độ WGS84 $(\phi, \lambda)$ (vĩ độ, kinh độ), phép chiếu cục bộ phẳng:
  $$x = \lambda \cdot k_x, \quad y = \phi \cdot k_y$$
  với $k_y = 110540.0\text{ m/deg}$, $k_x = 111320.0 \cdot \cos(\bar{\phi})\text{ m/deg}$.
- Phép chiếu trực giao 1D Frenet của một xe buýt tại vị trí $P = (x_p, y_p)$ lên tim tuyến $\mathcal{C}$ cho cặp tọa độ $(s_{\text{bus}}, d_{\text{perp}})$, trong đó $s_{\text{bus}} \in [0, L_{\text{route}}]$ là lý trình dọc tuyến và $d_{\text{perp}} \ge 0$ là khoảng cách lệch vuông góc tim đường.

### 2.2. Hình học Thực địa của Trạm Dừng Xe buýt Hà Nội
Trạm dừng xe buýt mục tiêu nằm tại lý trình $s_{\text{target}}$.
Cơ sở vật lý đo đạc thực tế:
- Chiều dài thân xe buýt tiêu chuẩn Hà Nội (Transerco / VinBus): $L_{\text{bus}} \in [10.5\text{m}, 12.2\text{m}]$.
- Chiều dài vệt đón trả khách / vịnh đỗ xe buýt (Bus Bay / Stop Box): $L_{\text{bay}} \in [15.0\text{m}, 25.0\text{m}]$.
- Vị trí cột biển báo trạm dừng (Station Signpost): Được đánh dấu tại tọa độ $s_{\text{target}}$. Khi xe buýt tấp vào lề đón khách, mũi xe hoặc ăng-ten GPS (thường đặt ở đầu hoặc giữa nóc xe) có thể dừng trước, ngang, hoặc hơi vượt qua cột biển báo từ $5\text{m}$ đến $15\text{m}$ do có nhiều xe cùng đón khách một lúc.

```
       HÀNH LANG ĐÓN BẾN & CHUYỂN TIẾP TRẠNG THÁI QUANH TRẠM DỪNG S_TARGET
  
  <--- Chiều xe chạy --->
========================================================================================
                      [----------- VÙNG CẬN BẾN (ARRIVING_NOW) -----------]
                      |                                                   |
  --------------------+------------------------+--------------------------+-------------
  APPROACHING         | D_entry (30m)          | Cột bến  D_exit (20m)    | PASSED
  (Đang tới)          |                        | s_target                 | (Đã qua)
  --------------------+------------------------+--------------------------+-------------
  s < s_target - 30m  |      s_target - 30m <= s_now <= s_target + 20m    | s > s_target + 20m
  d_rem > 30m         |                -20m <= d_rem <= 30m               | d_rem < -20m
  status: IN_TRANSIT  |                status: ARRIVING_NOW               | status: PASSED
                      [====== Chiều dài xe: 12m ======]                   | (Loại khỏi bến)
========================================================================================
```

### 2.3. Định nghĩa Miền Đón bến & Khoảng cách Cận bến Có dấu
Định nghĩa khoảng cách dọc tuyến có dấu (Signed Along-Track Distance to Station):
$$d_{\text{station}}(s) = s_{\text{target}} - s$$
- Khi $d_{\text{station}} > 0$: Xe đang ở phía thượng lưu (chưa tới trạm).
- Khi $d_{\text{station}} = 0$: Mũi/ăng-ten xe trùng đúng vị trí cột trạm.
- Khi $d_{\text{station}} < 0$: Mũi/ăng-ten xe đã vượt qua vị trí cột trạm một đoạn $|d_{\text{station}}|$.

Xác lập hai bán kính hình học chuẩn hóa (tập trung tại `config/system_config.py`):
1. **$D_{\text{arr\_entry}} = 30.0\text{ mét}$ (Ngưỡng đón bến thượng lưu):**
   Bao quát toàn bộ chiều dài tiếp cận vịnh đỗ, bảo đảm khi xe bắt đầu giảm tốc tấp lề ($25\text{m} - 30\text{m}$ trước biển báo), trạng thái "Đang cập bến" được kích hoạt mượt mà.
2. **$D_{\text{arr\_exit}} = 20.0\text{ mét}$ (Ngưỡng thoát bến hạ lưu):**
   Bao quát toàn bộ chiều dài thân xe buýt $12\text{m}$ cộng thêm dung sai đuôi xe đỗ sau biển báo $8\text{m}$. Khi xe đang dừng mở cửa cho khách lên xuống, dù tọa độ GPS có trôi quá cột biển báo $10\text{m} - 15\text{m}$, xe vẫn nằm trọn vẹn trong trạng thái cập bến.

### 2.4. Máy Trạng thái Phục vụ Trạm (Station Catchment State Machine)
Với mỗi xe có vị trí dự phóng hiện tại $s(t_{\text{now}})$:

$$\text{State}(s) = \begin{cases}
\text{APPROACHING (IN\_TRANSIT)}, & \text{khi } s(t_{\text{now}}) < s_{\text{target}} - D_{\text{arr\_entry}} \quad (d_{\text{station}} > 30.0\text{m}) \\
\text{ARRIVING\_NOW}, & \text{khi } s_{\text{target}} - D_{\text{arr\_entry}} \le s(t_{\text{now}}) \le s_{\text{target}} + D_{\text{arr\_exit}} \quad (-20.0\text{m} \le d_{\text{station}} \le 30.0\text{m}) \\
\text{PASSED\_STATION}, & \text{khi } s(t_{\text{now}}) > s_{\text{target}} + D_{\text{arr\_exit}} \quad (d_{\text{station}} < -20.0\text{m})
\end{cases}$$

#### Quy tắc Phục vụ Giao diện & DTO:
1. **Trường hợp `APPROACHING` ($d_{\text{station}} > 30.0\text{m}$):**
   - Xe được đưa vào danh sách `approaching_buses`.
   - `status = "IN_TRANSIT"`.
   - `distance_to_station_m = round(d_{\text{station}}, 1)`.
   - $\text{ETA} = f_{\text{kinematic}}(s, s_{\text{target}}) > 0$.
   - `display_eta_minutes = int(ceil(ETA / 60.0))`.
   - `display_text = f"{display_eta_minutes} phút"` (hoặc `"~1 phút"` nếu $\le 1$).
2. **Trường hợp `ARRIVING_NOW` ($-20.0\text{m} \le d_{\text{station}} \le 30.0\text{m}$):**
   - Xe **BẮT BUỘC ĐƯỢC GIỮ LẠI** trong danh sách `approaching_buses`.
   - `status = "ARRIVING_NOW"`.
   - `distance_to_station_m = round(max(0.0, d_{\text{station}}), 1)`.
   - `eta_seconds = 0.0`.
   - `display_eta_minutes = 0`.
   - `display_text = "Đang cập bến"`.
   - UI hiển thị huy hiệu xanh nhấp nháy (`pulse-badge`), phát âm thanh/rung thông báo cho hành khách chuẩn bị bước lên xe.
3. **Trường hợp `PASSED_STATION` ($d_{\text{station}} < -20.0\text{m}$):**
   - Xe đã hoàn toàn rời khỏi bến và di chuyển sang phân đoạn tiếp theo.
   - Xe bị loại khỏi danh sách phục vụ của trạm $s_{\text{target}}$.
   - Không xuất hiện trong JSON trả về cho trạm này.

### 2.5. Chứng minh Toán học: Triệt tiêu Điểm Gián đoạn (Cliff Elimination Proof)
- **Định lý 1 (Tính liên tục của tập tiếp cận):**
  Cho hàm đếm số lượng xe tiếp cận $N(s) = \sum_i \mathbb{I}(s_i \in \text{Catchment}(s_{\text{target}}))$.
  Dưới cơ chế cũ với điều kiện loại trừ $s \ge s_{\text{target}} - 10.0\text{m}$, tập đón bến bị cắt cụt tại $s_{\text{target}} - 10.0\text{m}$, tạo nên bước nhảy $\lim_{s \to (s_{\text{target}}-10)^-} N(s) = 1 \ne \lim_{s \to (s_{\text{target}}-10)^+} N(s) = 0$.
  Dưới cơ chế SPEC-15, miền hợp lệ tiếp cận là $(-\infty, s_{\text{target}} + D_{\text{arr\_exit}}]$.
  Tại ranh giới chuyển tiếp $s = s_{\text{target}} - D_{\text{arr\_entry}} = s_{\text{target}} - 30.0\text{m}$:
  $$\lim_{s \to 30^-} \text{display\_text} = \text{"~1 phút"} \quad \longrightarrow \quad \lim_{s \to 30^+} \text{display\_text} = \text{"Đang cập bến"}$$
  Xe vẫn tồn tại liên tục trong mảng `buses` với $N(s) = 1$.
  Tại ranh giới rời bến $s = s_{\text{target}} + 20.0\text{m}$, xe thực tế đã đón xong khách và lăn bánh cách trạm $20\text{m}$, việc chuyển trạng thái sang `PASSED_STATION` phản ánh $100\%$ sự thật vật lý mà không gây hụt hẫng cho hành khách tại trạm.

---

## 3. MÔ HÌNH TOÁN HỌC 2: ĐỘNG HỌC BÙ ĐẮP TRỄ TELEMETRY (DEAD-RECKONING KINEMATICS)

### 3.1. Đặc thù Dữ liệu Viễn trắc BusMap
Theo kết quả kiểm toán thực nghiệm DOC-13 trên 69 xe thực tế:
- Tuổi gói tin GPS $\Delta t_{\text{age}} = t_{\text{now}} - t_{\text{ping}} \in [42.7\text{s}, 78.7\text{s}]$, trung vị $\sim 60\text{s}$.
- Không có bất kỳ gói tin nào dưới $30\text{s}$.
- Gói tin chỉ chứa trạng thái tức thời tại thời điểm quá khứ $t_{\text{ping}}$:
  $$X(t_{\text{ping}}) = (s_{\text{ping}}, v_{\text{ping}}, \theta_{\text{ping}})$$

### 3.2. Mô hình Động học Hồi quy Trung bình Vận tốc (Mean-Reverting Velocity Relaxation)
Nếu giả định vận tốc không đổi ($s(t_{\text{now}}) = s_{\text{ping}} + v_{\text{ping}} \cdot \Delta t_{\text{age}}$):
- Nếu xe báo $v = 45\text{ km/h}$ ($12.5\text{ m/s}$) và $\Delta t_{\text{age}} = 75\text{s}$, độ dịch chuyển suy đoán là $937.5\text{m}$. Trên thực tế trong phố Hà Nội, không xe buýt nào có thể duy trì $45\text{ km/h}$ liên tục suốt 75s mà không gặp đèn tín hiệu hoặc giảm tốc. Phép ngoại suy tuyến tính thô bạo sẽ gây hiện tượng **nhảy cóc vượt trạm ảo**.
- Nếu xe báo $v = 0\text{ km/h}$ (đang dừng đèn đỏ 20s), giả định $v = 0$ suốt 75s sẽ bỏ qua việc xe đã khởi hành sau khi hết đèn đỏ.

Do đó, vận tốc tức thời $v(t)$ trong khoảng thời gian $[0, \Delta t_{\text{age}}]$ được mô hình hóa theo quá trình hồi quy trung bình (Ornstein-Uhlenbeck / Mean-Reverting Relaxation) về phía vận tốc kỳ vọng phân đoạn Baseline $v_{\text{base}}$:

$$\frac{dv(t)}{dt} = -\lambda \left( v(t) - v_{\text{base}} \right)$$

Nghiệm giải tích của phương trình vi phân:
$$v(t) = v_{\text{base}} + (v_{\text{ping}} - v_{\text{base}}) \cdot e^{-\lambda t}$$

Trong đó:
- $v_{\text{ping}}$: Vận tốc tức thời đo được từ GPS tại $t_{\text{ping}}$ (m/s).
- $v_{\text{base}}$: Vận tốc trung vị lịch sử $P_{50}$ của phân đoạn trạm hiện tại: $v_{\text{base}} = \frac{L_{\text{seg}}}{T_{\text{base\_p50}}}$ (m/s). Nếu thiếu dữ liệu phân đoạn, fallback về $v_{\text{urban\_default}} = 18.0\text{ km/h} = 5.0\text{ m/s}$.
- $\lambda$: Hệ số suy giảm vận tốc (Velocity Relaxation Rate):
  $$\lambda = \frac{\ln(2)}{\tau_{1/2}}$$
  Với chu kỳ bán rã vận tốc $\tau_{1/2} = 20.0\text{ giây} \implies \lambda \approx 0.034657\text{ s}^{-1}$.

### 3.3. Tích phân Quãng đường Dự phóng Động học
Quãng đường dịch chuyển suy đoán $\Delta s_{\text{dr}}$ trong khoảng thời gian $\Delta t_{\text{eff}}$:

$$\Delta s_{\text{dr}}(\Delta t_{\text{eff}}) = \int_{0}^{\Delta t_{\text{eff}}} v(u) \, du = v_{\text{base}} \cdot \Delta t_{\text{eff}} + \frac{v_{\text{ping}} - v_{\text{base}}}{\lambda} \left( 1 - e^{-\lambda \Delta t_{\text{eff}}} \right)$$

#### Các Ràng buộc Vật lý Giới hạn Biên (Physical Clamping Invariants):
1. **Chặn tuổi hiệu dụng $\Delta t_{\text{eff}}$:**
   $$\Delta t_{\text{eff}} = \min(\Delta t_{\text{age}}, T_{\text{dr\_max}})$$
   Với $T_{\text{dr\_max}} = 90.0\text{ giây}$. Tránh ngoại suy quá xa khi telemetry bị gián đoạn.
2. **Chặn vận tốc tối thiểu khi xe đang kẹt:**
   Nếu $v_{\text{ping}} < 1.0\text{ m/s}$ ($< 3.6\text{ km/h}$) và phân đoạn đang có mật độ ùn tắc cao, ta không ép xe tăng tốc lên $v_{\text{base}}$. Khi đó:
   $$\Delta s_{\text{dr}} = \max\left(0.0, \; v_{\text{ping}} \cdot \Delta t_{\text{eff}}\right)$$
   (Xe đứng yên hoặc bò chậm thì chỉ dịch chuyển tối đa một lượng vi mô, không phóng đại ảo).
3. **Chặn trần theo vị trí trạm mục tiêu (Station Ceiling):**
   Một chiếc xe buýt chưa hề phát ra gói tin viễn trắc nào chứng minh nó đã vượt qua trạm thì **TUYỆT ĐỐI KHÔNG ĐƯỢC PHÉP NGOẠI SUY VƯỢT QUÁ TRẠM**:
   $$s(t_{\text{now}}) = \min\left( s_{\text{target}} - 5.0\text{m}, \; s_{\text{ping}} + \Delta s_{\text{dr}} \right) \quad \text{nếu } s_{\text{ping}} < s_{\text{target}} - D_{\text{arr\_entry}}$$
   Điều này bảo đảm: Dù $\Delta t_{\text{age}}$ có lớn đến đâu, Dead Reckoning không bao giờ tự ý biến một chiếc xe đang tiếp cận thành xe đã qua trạm!

### 3.4. Ngưỡng Cắt Viễn trắc Cũ & Xóa sổ Xe ma ($T_{\text{stale}}$)
Định nghĩa thời gian chết của gói tin viễn trắc (Staleness Threshold):
$$T_{\text{stale}} = 300.0\text{ giây (5 phút)}$$
- Khi $\Delta t_{\text{age}} \le T_{\text{stale}}$: Dữ liệu hợp lệ, áp dụng Dead Reckoning.
- Khi $\Delta t_{\text{age}} > T_{\text{stale}}$:
  Thiết bị giám sát hành trình đã mất sóng, tắt máy hoặc xe đã ngừng phục vụ.
  **XỬ LÝ DỨT ĐIỂM:** Xe bị coi là `STALE_LOST` và **LOẠI BỎ HOÀN TOÀN KHỎI DANH SÁCH TIẾP CẬN**.
  Hệ thống tuyệt đối không tính ETA, không gán nhãn `is_delayed = False` cho xe này. Điều này tiêu diệt $100\%$ hiện tượng "xe ma" được chỉ ra trong DOC-14.

---

## 4. MÔ HÌNH TOÁN HỌC 3: TÍNH NHẤT QUÁN HƯỚNG VECTOR (HEADING VECTOR CONSISTENCY)

### 4.1. Bản chất Hình học Trục đường Đôi Phân cách Hẹp
Tại các tuyến phố đôi như Nguyễn Trãi, Giải Phóng, Quang Trung, hành lang xe chạy hai chiều chỉ cách nhau dải phân cách giữa $2\text{m} - 5\text{m}$. Khoảng cách trực giao từ xe chiều về ($dir = 1$) tới tim đường chiều đi ($dir = 0$) chỉ dao động trong khoảng $12\text{m} - 25\text{m}$, hoàn toàn lọt vào ngưỡng $d_{\text{perp}} \le 35.0\text{m}$.
Do đó, điều kiện khoảng cách $d_{\text{perp}}$ là **ĐIỀU KIỆN CẦN NHƯNG CHƯA ĐỦ**.

```
                HÌNH HỌC PHÂN ĐỊNH HƯỚNG VECTOR TRÊN ĐƯỜNG ĐÔI
  
  Chiều đi (dir=0) ------------------- Tangent T_route ----------> (Heading ~ 50 deg)
  [Dải phân cách hẹp 3m]
  Chiều về (dir=1) <--- u_bus (Deg ~ 230 deg) ------------------- (Xe ngược chiều)
  
  Tích vô hướng: cos(Delta_theta) = u_bus . T_route ≈ cos(180 deg) = -1.0  < -0.20
  ===> KẾT LUẬN: LOẠI BỎ XE NGƯỢC CHIỀU LẬP TỨC!
```

### 4.2. Vector Tiếp tuyến Tim Tuyến $\vec{T}_{\text{route}}$
Tại phân đoạn hình chiếu $[P_k, P_{k+1}]$ của tim tuyến:
$$\Delta x = (\lambda_{k+1} - \lambda_k) \cdot k_x, \quad \Delta y = (\phi_{k+1} - \phi_k) \cdot k_y$$
Chiều dài phân đoạn: $L_k = \sqrt{\Delta x^2 + \Delta y^2}$.
Vector đơn vị tiếp tuyến tim đường (hướng di chuyển chuẩn của tuyến):
$$\vec{u}_{\text{route}} = \left( \frac{\Delta x}{L_k}, \; \frac{\Delta y}{L_k} \right)$$
Trong đó trục $X$ hướng về phía Đông (East), trục $Y$ hướng về phía Bắc (North).

### 4.3. Vector Vận tốc La bàn của Xe $\vec{u}_{\text{bus}}$
BusMap API cung cấp góc hướng la bàn $\theta_{\text{bus}} = \text{Deg} \in [0^\circ, 360^\circ)$, tính theo chiều kim đồng hồ từ hướng Bắc thực:
- Hướng Bắc ($\theta = 0^\circ$): $\Delta x = 0, \Delta y = 1$.
- Hướng Đông ($\theta = 90^\circ$): $\Delta x = 1, \Delta y = 0$.
- Hướng Nam ($\theta = 180^\circ$): $\Delta x = 0, \Delta y = -1$.
- Hướng Tây ($\theta = 270^\circ$): $\Delta x = -1, \Delta y = 0$.

Vector đơn vị chuyển động của xe buýt trong hệ tọa độ phẳng $(X, Y)$:
$$\vec{u}_{\text{bus}}(\theta_{\text{bus}}) = \Big( \sin(\text{radians}(\theta_{\text{bus}})), \; \cos(\text{radians}(\theta_{\text{bus}})) \Big)$$

### 4.4. Tiêu chuẩn So khớp Lượng giác & Ngưỡng Lọc Ngược chiều
Góc lệch hướng giữa xe buýt và tim tuyến $\Delta \theta = \angle(\vec{u}_{\text{bus}}, \vec{u}_{\text{route}})$:
$$\cos(\Delta \theta) = \vec{u}_{\text{bus}} \cdot \vec{u}_{\text{route}} = \sin(\theta_{\text{bus}}) \cdot u_{\text{route}, x} + \cos(\theta_{\text{bus}}) \cdot u_{\text{route}, y}$$

#### Cơ chế Lọc Hai Phân vùng Động học:
1. **Phân vùng Xe Chạy ($v_{\text{bus}} \ge V_{\text{heading\_valid}}$ với $V_{\text{heading\_valid}} = 5.0\text{ km/h} \approx 1.39\text{ m/s}$):**
   Ở dải tốc độ này, cảm biến la bàn và đạo hàm vị trí GPS của thiết bị GSHT hoàn toàn chính xác.
   - Nếu $\cos(\Delta \theta) \ge \text{HEADING\_COS\_MIN} = -0.20$ (tương đương $\Delta \theta \le 101.5^\circ$):
     Xe đang di chuyển đồng hướng hoặc chuyển làn/rẽ nhẹ theo tuyến $\implies$ **CHẤP NHẬN**.
   - Nếu $\cos(\Delta \theta) < -0.20$ (tương đương $\Delta \theta > 101.5^\circ$):
     Xe đang quay đầu hoặc chạy theo chiều ngược lại $\implies$ **LOẠI BỎ NGAY LẬP TỨC**.
2. **Phân vùng Xe Bò / Dừng đỗ ($v_{\text{bus}} < V_{\text{heading\_valid}}$):**
   Khi xe dừng đỗ hoặc nhích từng centimet ($v < 5\text{ km/h}$), góc xoay la bàn GPS thường bị trôi dạt ngẫu nhiên (Compass Jitter).
   Để tránh loại bỏ nhầm xe đang dừng trả khách ở lề đường:
   - Cho phép dung sai rộng hơn: Chỉ loại bỏ nếu xe đã có lịch sử di chuyển lùi hoặc $\cos(\Delta \theta) < -0.60$ ($\Delta \theta > 127^\circ$).
   - Nếu không có dữ liệu lịch sử, bảo lưu trạng thái hợp lệ để tránh rớt xe oan.

---

## 5. MÔ HÌNH TOÁN HỌC 4: TÍCH HỢP ĐỘ TRỄ & ÙN TẮC THỜI GIAN THỰC (REAL-TIME DELAY & CONGESTION)

### 5.1. Phân biệt Bản chất giữa Baseline Lịch sử & Động học Tức thời
Ma trận Baseline trong SQLite cung cấp phân phối thời gian di chuyển chuẩn sạch:
$$T_{\text{baseline}} = [P_{10}, P_{50}, P_{90}]$$
- $P_{50}$ phản ánh kỳ vọng trung bình trong khung giờ `(day_type, hour_slot)`.
- Tuy nhiên, khi một sự cố giao thông đột ngột xảy ra (tai nạn, ngập úng, tắc đường nghiêm trọng), tốc độ thực tế $v_{\text{obs}}$ có thể tụt dốc về $0.5\text{ km/h}$ trong khi $P_{50}$ vẫn kỳ vọng $18.0\text{ km/h}$.
- Ngược lại, nếu một chiếc xe buýt chỉ dừng đèn đỏ 20 giây, ta không thể lấy $v = 0$ để nhân cho toàn bộ quãng đường $5\text{km}$ còn lại (gây nổ ETA lên vô tận).

### 5.2. Mô hình Pha trộn Đoạn trạm Động học - Baseline (Hybrid Kinematic-Segment Model)
Hành trình từ vị trí dự phóng hiện tại $s(t_{\text{now}})$ đến trạm mục tiêu $s_{\text{target}}$ đi qua các phân đoạn:
$$\text{Segment } k \quad \longrightarrow \quad \text{Segment } k+1 \quad \dots \quad \longrightarrow \quad \text{Segment } \text{target}-1$$

1. **Phân đoạn Hiện tại $[k, k+1]$ (Immediate Segment):**
   Đây là đoạn đường xe đang thực sự lăn bánh và chịu tác động trực tiếp của vận tốc tức thời $v_{\text{obs}}$.
   Vận tốc hiệu dụng trên phần còn lại của đoạn $k$ ($\Delta s_k = s_{k+1} - s(t_{\text{now}})$):
   $$v_{\text{eff}, k} = \max\left( V_{\text{crawl\_min}}, \; w_{\text{obs}} \cdot v_{\text{obs}} + (1 - w_{\text{obs}}) \cdot v_{k, \text{base\_p50}} \right)$$
   Trong đó:
   - $w_{\text{obs}} = 0.75$ (Trọng số ưu tiên vận tốc tức thời thực đo trên đoạn hiện tại).
   - $V_{\text{crawl\_min}} = 2.0\text{ km/h} \approx 0.556\text{ m/s}$ (Sàn vận tốc tối thiểu, chống chia cho 0).
   Thời gian di chuyển ước lượng cho đoạn hiện tại:
   $$\hat{t}_k = \frac{\Delta s_k}{v_{\text{eff}, k}}$$
2. **Các Phân đoạn Kế tiếp $m \in [k+1, \text{target}-1]$ (Downstream Segments):**
   Do xe chưa tiến vào các đoạn này, thời gian di chuyển được chi phối bởi phân vị Baseline lịch sử kết hợp hệ số lan truyền tắc nghẽn (Congestion Propagation Factor $\psi_{\text{cong}}$):
   $$\hat{t}_m = \psi_{\text{cong}} \cdot T_{m, P_{50}}$$
   Trong đó:
   $$\psi_{\text{cong}} = \max\left( 1.0, \; \min\left( 2.5, \; \frac{v_{k, \text{base\_p50}}}{v_{\text{eff}, k}} \right)^{0.5} \right)$$
   Hàm mũ bậc $0.5$ bảo đảm sự lan truyền suy giảm mềm (Damped Propagation): Tắc nghẽn ở đoạn hiện tại có ảnh hưởng đến các đoạn kế tiếp nhưng mức độ suy giảm dần theo khoảng cách.

### 5.3. Công thức Tính toán Độ trễ Thực tế $\Delta t_{\text{delay}}$
Tổng thời gian di chuyển ước lượng cập nhật động học:
$$\text{ETA}_{\text{kinematic}} = \hat{t}_k + \sum_{m = k+1}^{\text{target}-1} \hat{t}_m$$

Thời gian di chuyển danh định theo Baseline thuần túy:
$$\text{ETA}_{\text{baseline\_p50}} = \rho_k \cdot T_{k, P_{50}} + \sum_{m = k+1}^{\text{target}-1} T_{m, P_{50}}$$

Độ trễ vật lý thực sự đo lường được:
$$\Delta t_{\text{delay}} = \max\left( 0.0, \; \text{ETA}_{\text{kinematic}} - \text{ETA}_{\text{baseline\_p50}} \right)$$

### 5.4. Quy tắc Xác định Cờ Cảnh báo & Trạng thái Giao thông
Khôi phục trọn vẹn ý nghĩa nguyên bản của các trường DTO:
1. **Cờ cảnh báo trễ (`is_delayed`):**
   $$\text{is\_delayed} = \left( \Delta t_{\text{delay}} \ge T_{\text{delay\_threshold}} \right)$$
   Với $T_{\text{delay\_threshold}} = 120.0\text{ giây (2 phút)}$.
2. **Giá trị thời gian trễ (`delay_seconds`):**
   $$\text{delay\_seconds} = \text{round}(\Delta t_{\text{delay}}, 1)$$
   (Chấm dứt hoàn toàn việc gán cứng `45.0` hoặc `0.0` giả mạo).
3. **Trạng thái Giao thông của Phương tiện (`traffic_status`):**
   $$\text{traffic\_status} = \begin{cases}
   \text{"UN\_TAC"}, & \text{khi } v_{\text{obs}} < 10.0\text{ km/h} \quad \text{hoặc} \quad \Delta t_{\text{delay}} \ge 120.0\text{s} \\
   \text{"BINH\_THUONG"}, & \text{khi } 10.0\text{ km/h} \le v_{\text{obs}} < 20.0\text{ km/h} \quad \text{và} \quad \Delta t_{\text{delay}} < 120.0\text{s} \\
   \text{"THONG\_THOANG"}, & \text{khi } v_{\text{obs}} \ge 20.0\text{ km/h} \quad \text{và} \quad \Delta t_{\text{delay}} < 30.0\text{s}
   \end{cases}$$

---

## 6. MÔ HÌNH TOÁN HỌC 5: ĐỆM BẢO VỆ BẤT ĐỐI XỨNG & SUY GIẢM CẬN BẾN (LINEX BUFFER & ATTENUATION)

### 6.1. Hợp nhất Hàm Mất mát LINEX với Động học Thực tế
Theo SPEC-11, nghiệm tối ưu Bayes dưới hàm mất mát bất đối xứng LINEX (phạt nặng việc lỡ xe hơn việc chờ xe) đòi hỏi một độ lệch an toàn $\Delta t_{\text{buffer}} > 0$.
Tuy nhiên, để khắc phục triệt để lỗi "kẹp trần 180s thô bạo" và "nhảy giật khi vào gần bến", độ đệm an toàn được tính toán như sau:

$$\text{ETA}_{\text{conservative}} = \text{ETA}_{\text{kinematic}} + \Delta t_{\text{buffer}}$$

### 6.2. Cấu trúc Độ đệm Bảo vệ Thích ứng $\Delta t_{\text{buffer}}$
$$\Delta t_{\text{buffer}} = \kappa(d) \cdot \left[ \alpha \cdot \sigma_{\text{accum}} + \beta \cdot \tau_{\text{telemetry}} + \gamma \cdot \text{ETA}_{\text{kinematic}} \right]$$

Trong đó:
- $\sigma_{\text{accum}} = \sqrt{\rho_k^2 \sigma_k^2 + \sum_{m=k+1}^{\text{target}-1} \sigma_m^2}$ là độ lệch chuẩn tích lũy từ SQLite.
- $\alpha = 0.60$: Trọng số hấp thụ phương sai giao thông.
- $\tau_{\text{telemetry}} = 15.0\text{s}$: Bù đắp nhịp trễ lấy mẫu BusMap.
- $\beta = 0.5$: Hệ số co cụm nhịp trễ.
- $\gamma = 0.04$: Hệ số dãn nở theo chân trời (4%).

### 6.3. Hàm Bao Suy giảm Liên tục Cận bến $\kappa(d)$ (Smooth Near-Station Attenuation Envelope)
Để xóa bỏ triệt để bước nhảy phi liên tục, hàm bao suy giảm $\kappa(d)$ được thiết kế trơn bậc 2 ($C^1$-smooth cubic hermite):

$$\kappa(d) = \begin{cases}
1.0, & \text{khi } d > D_{\text{buffer\_max}} \quad (d > 150.0\text{m}) \\
3\xi^2 - 2\xi^3, & \text{khi } D_{\text{buffer\_min}} < d \le D_{\text{buffer\_max}} \quad \text{với } \xi = \frac{d - D_{\text{buffer\_min}}}{D_{\text{buffer\_max}} - D_{\text{buffer\_min}}} \\
0.0, & \text{khi } d \le D_{\text{buffer\_min}} \quad (d \le 30.0\text{m})
\end{cases}$$

Với $D_{\text{buffer\_min}} = 30.0\text{m}$ và $D_{\text{buffer\_max}} = 150.0\text{m}$.
- Tại $d = 30.0\text{m}$: $\kappa(30) = 0.0$, đạo hàm $\kappa'(30) = 0.0$.
- Tại $d = 150.0\text{m}$: $\kappa(150) = 1.0$, đạo hàm $\kappa'(150) = 0.0$.
- Hàm $\kappa(d)$ chuyển tiếp mượt mà $100\%$, không có góc gãy (smooth gradient), triệt tiêu hoàn toàn rung lắc đệm khi xe tiến sát bến!

```
               ĐỒ THỊ HÀM SUY GIẢM ĐỆM AN TOÀN TRƠN BẬC 2 KAPPA(D)
  kappa(d)
    1.0 |                                          +--------------------- (d > 150m: Đệm tối đa 100%)
        |                                      ..-'
    0.8 |                                   .-'
        |                                 .'
    0.5 |                               .'
        |                            .-'
    0.2 |                         .-'
        |                     _.-'
    0.0 +--------------------+-------------------------------------------> Khoảng cách d (m)
        0                   30m                  150m
      (Đang cập bến)     (D_min: Bắt đầu suy giảm)  (D_max: Đệm đầy đủ)
```

---

## 7. CHUẨN HÓA HẰNG SỐ & GIAO DIỆN HỆ THỐNG (`config/system_config.py`)

Mọi tham số vật lý và ngưỡng động học trong SPEC-15 phải được khai báo tập trung duy nhất tại `config/system_config.py`, tuyệt đối cấm mọi hình thức hardcode inline trong mã nguồn logic.

### 7.1. Bảng Thông số Vật lý & Động học Chuẩn hóa

| Tên Hằng số | Giá trị | Đơn vị | Ý nghĩa & Cơ sở Khoa học |
| :--- | :---: | :---: | :--- |
| `STATION_ARRIVING_ENTRY_M` | `30.0` | mét | Bán kính kích hoạt trạng thái "Đang cập bến" thượng lưu bến. |
| `STATION_ARRIVING_EXIT_M` | `20.0` | mét | Dung sai cho phép xe đỗ trả khách quá cột bến hạ lưu trước khi ngắt. |
| `STATION_BUFFER_ATTEN_MIN_M` | `30.0` | mét | Ngưỡng dưới triệt tiêu hoàn toàn đệm an toàn ($\kappa = 0$). |
| `STATION_BUFFER_ATTEN_MAX_M` | `150.0` | mét | Ngưỡng trên kích hoạt $100\%$ đệm an toàn ($\kappa = 1$). |
| `DEAD_RECKONING_TAU_HALF_LIFE_S` | `20.0` | giây | Chu kỳ bán rã vận tốc trong mô hình hồi quy trung bình động học. |
| `DEAD_RECKONING_MAX_HORIZON_S` | `90.0` | giây | Thời gian ngoại suy tối đa cho phép của Dead Reckoning. |
| `MAX_TELEMETRY_STALE_SEC` | `300.0` | giây | Ngưỡng gói tin cũ (5 phút); quá thời gian này xe bị loại bỏ (chống xe ma). |
| `HEADING_MIN_SPEED_KMPH` | `5.0` | km/h | Vận tốc tối thiểu để kích hoạt bộ lọc kiểm tra góc la bàn. |
| `HEADING_COS_SIMILARITY_MIN` | `-0.20` | vô thứ nguyên | Ngưỡng cosine tối thiểu ($\Delta \theta \le 101.5^\circ$); nhỏ hơn bị coi là ngược chiều. |
| `CONGESTION_SPEED_THRESHOLD_KMPH` | `10.0` | km/h | Vận tốc kích hoạt trạng thái ùn tắc phân đoạn. |
| `FREEFLOW_SPEED_THRESHOLD_KMPH` | `20.0` | km/h | Vận tốc phân định trạng thái thông thoáng. |
| `REALTIME_DELAY_ALERT_SEC` | `120.0` | giây | Ngưỡng trễ thời gian thực để bật cờ `is_delayed = True`. |
| `MIN_PHYSICAL_CRAWL_SPEED_MPS` | `0.556` | m/s | Sàn vận tốc vật lý khi kẹt xe ($2.0\text{ km/h}$), chống chia cho 0. |
| `MAX_SAFE_BUFFER_CEILING_SEC` | `180.0` | giây | Trần đệm an toàn tối đa trên các lộ trình dài ($3\text{ phút}$). |

### 7.2. Danh mục Thanh lọc Dead Code & Rác Cấu hình
Trong đợt refactoring tiếp theo, `@leaf_coder` có nghĩa vụ pháp lý xóa bỏ hoàn toàn các biến rác sau khỏi `config/system_config.py`:
- Xóa toàn bộ khối TimBus Dead Code: `TIMBUS_GATEWAY_HOST`, `TIMBUS_GATEWAY_PORT`, `TIMBUS_BASE_URL`, `TIMBUS_CLIENT_ID`, `TIMBUS_HEARTBEAT_MS`, `KEY1_LENGTH_BYTES`, `KEY2_LENGTH_BYTES`, `ROTATION_ANIM_DURATION_MS`, `DEAD_RECKONING_HALF_LIFE_S`, `DEAD_RECKONING_MAX_DIST_M`, `DEAD_RECKONING_MAX_TIME_S`.
- Xóa toàn bộ các biến alias trùng lặp: `LAT_DEGREE_TO_METERS`, `LON_DEGREE_TO_METERS`, `CORRIDOR_DEVIATION_METERS`.

---

## 8. GIẢI THUẬT VÀ PSEUDOCODE TRIỂN KHAI

### 8.1. Thuật toán 1: Lọc Phương tiện, Kiểm tra Hướng & Dự phóng Vị trí (`ProjectFilterAndExtrapolateVehicle`)

```python
def project_filter_and_extrapolate_vehicle(
    v: BusMapVehicleDTO,
    shape_model: ShapeModel,
    s_target: float,
    now_epoch: float,
    baseline_matrix: Dict,
    route_id: Union[int, str],
    dir_int: int,
    day_type: int,
    hour_slot: int
) -> Optional[ExtrapolatedBusState]:
    """
    Thực hiện chiếu Frenet 1D, kiểm tra tuổi gói tin, kiểm tra hướng vector la bàn
    và dự phóng vị trí động học (Dead Reckoning).
    Trả về None nếu xe không hợp lệ hoặc đã qua trạm.
    """
    # 1. Trích xuất thời gian và kiểm tra độ cũ của gói tin (Staleness Check)
    t_ping = parse_ping_epoch(v.updated_at, now_epoch)
    delta_t_age = max(0.0, now_epoch - t_ping)
    if delta_t_age > MAX_TELEMETRY_STALE_SEC:
        return None  # Loại bỏ xe ma tắt máy/mất sóng > 5 phút

    # 2. Chiếu trực giao 1D Frenet lên tim tuyến
    s_ping, d_perp, seg_idx = project_point_with_segment(shape_model, v.lat, v.lng)
    if d_perp > MAX_CORRIDOR_CROSS_TRACK_M:
        return None  # Lệch hành lang tuyến

    # 3. Kiểm tra tính nhất quán hướng vector (Heading Consistency Check)
    v_speed_mps = max(0.0, v.speed_kmh / 3.6)
    if v.speed_kmh >= HEADING_MIN_SPEED_KMPH and v.deg is not None:
        u_route_x, u_route_y = shape_model.get_segment_unit_tangent(seg_idx)
        theta_rad = math.radians(v.deg)
        u_bus_x = math.sin(theta_rad)
        u_bus_y = math.cos(theta_rad)
        cos_similarity = u_bus_x * u_route_x + u_bus_y * u_route_y
        if cos_similarity < HEADING_COS_SIMILARITY_MIN:
            return None  # Loại bỏ xe chạy ngược chiều trên đường đôi!

    # 4. Dự phóng vị trí động học (Dead-Reckoning with Mean-Reverting Relaxation)
    v_base_mps = shape_model.lookup_segment_baseline_speed(
        baseline_matrix, route_id, dir_int, seg_idx, day_type, hour_slot
    )
    delta_t_eff = min(delta_t_age, DEAD_RECKONING_MAX_HORIZON_S)
    
    if v_speed_mps < MIN_PHYSICAL_CRAWL_SPEED_MPS:
        delta_s_dr = v_speed_mps * delta_t_eff
    else:
        lam = math.log(2.0) / DEAD_RECKONING_TAU_HALF_LIFE_S
        delta_s_dr = v_base_mps * delta_t_eff + ((v_speed_mps - v_base_mps) / lam) * (1.0 - math.exp(-lam * delta_t_eff))
    
    delta_s_dr = max(0.0, delta_s_dr)
    
    # Giới hạn trần: Không được tự ý ngoại suy vượt trạm nếu ban đầu chưa qua trạm
    if s_ping < s_target - STATION_ARRIVING_ENTRY_M:
        s_now = min(s_target - 5.0, s_ping + delta_s_dr)
    else:
        s_now = s_ping + delta_s_dr

    # 5. Kiểm tra ranh giới trạm (Station Catchment Bounds)
    # Xe đã đi qua trạm hoàn toàn khi s_now > s_target + STATION_ARRIVING_EXIT_M
    if s_now > s_target + STATION_ARRIVING_EXIT_M:
        return None  # Xe đã rời trạm

    return ExtrapolatedBusState(
        vehicle=v,
        s_now=s_now,
        d_station=s_target - s_now,
        v_obs_mps=v_speed_mps,
        delta_t_age=delta_t_age,
        t_ping=t_ping
    )
```

---

### 8.2. Thuật toán 2: Tính toán ETA Động học & Phục vụ Trạm (`ComputeKinematicStationETA`)

```python
def compute_kinematic_station_eta(
    bus_state: ExtrapolatedBusState,
    route_id: Union[int, str],
    dir_int: int,
    target_st: StationDTO,
    station_s: List[float],
    now_epoch: float,
    baseline_matrix: Dict,
    day_type: int,
    hour_slot: int
) -> ApproachingBusDTO:
    """
    Tính toán ETA động học, xử lý vùng cận bến, đo lường độ trễ thực và tạo DTO hoàn chỉnh.
    """
    s_now = bus_state.s_now
    d_station = bus_state.d_station
    s_target = target_st.cum_distance_m
    v_obs_kmh = bus_state.vehicle.speed_kmh
    v_obs_mps = bus_state.v_obs_mps

    # 1. KIỂM TRA TRẠNG THÁI CẬN BẾN (ARRIVING_NOW)
    # Vùng cập bến: [-STATION_ARRIVING_EXIT_M, STATION_ARRIVING_ENTRY_M]
    if -STATION_ARRIVING_EXIT_M <= d_station <= STATION_ARRIVING_ENTRY_M:
        safe_window = SafeWindowDTO(
            p10_seconds=0.0,
            p50_seconds=0.0,
            p90_seconds=15.0,
            p10_minutes=0,
            p90_minutes=1,
            conservative_eta_seconds=0.0,
            buffer_seconds=0.0,
            display_eta_minutes=0,
            is_delayed=False,
            delay_seconds=0.0,
            recommended_arrival_time=format_epoch_hms(now_epoch)
        )
        return ApproachingBusDTO(
            vehicle_id=bus_state.vehicle.id,
            plate=bus_state.vehicle.plate,
            distance_to_station_m=round(max(0.0, d_station), 1),
            stops_remaining=1 if d_station > 0 else 0,
            eta_seconds=0.0,
            eta_minutes=0.0,
            display_eta_minutes=0,
            display_text="Đang cập bến",
            safe_window=safe_window,
            speed_kmh=round(v_obs_kmh, 1),
            status="ARRIVING_NOW",
            traffic_status="BINH_THUONG",
            ping_time=format_epoch_iso(bus_state.t_ping),
            ping_age_seconds=round(bus_state.delta_t_age, 1),
            arrival_time_epoch=round(now_epoch, 1)
        )

    # 2. XÁC ĐỊNH PHÂN ĐOẠN TRẠM & TÍNH TOÁN BASELINE TÍCH LŨY
    k = find_current_segment_index(station_s, s_now)
    station_order = target_st.order
    stops_rem = max(1, station_order - k)
    
    # Baseline phân đoạn hiện tại
    l_k = max(1.0, station_s[k + 1] - station_s[k])
    rem_in_seg = max(0.0, station_s[k + 1] - s_now)
    rho = min(1.0, max(0.0, rem_in_seg / l_k))
    
    t_k_p10, t_k_p50, t_k_p90, _, std_k = lookup_baseline(route_id, dir_int, k, k + 1, day_type, hour_slot, l_k)
    sigma_sq = (rho * std_k) ** 2
    
    base_rem_p10 = rho * t_k_p10
    base_rem_p50 = rho * t_k_p50
    base_rem_p90 = rho * t_k_p90
    
    for m in range(k + 1, station_order):
        seg_len_m = max(1.0, station_s[m + 1] - station_s[m])
        m_p10, m_p50, m_p90, _, std_m = lookup_baseline(route_id, dir_int, m, m + 1, day_type, hour_slot, seg_len_m)
        base_rem_p10 += m_p10
        base_rem_p50 += m_p50
        base_rem_p90 += m_p90
        sigma_sq += std_m ** 2

    sigma_accum = math.sqrt(sigma_sq)

    # 3. ĐIỀU CHỈNH ĐỘNG HỌC PHÂN ĐOẠN HIỆN TẠI & TÍNH ĐỘ TRỄ THỰC TẾ
    v_base_k = l_k / max(1.0, t_k_p50)
    v_eff_k = max(MIN_PHYSICAL_CRAWL_SPEED_MPS, 0.75 * v_obs_mps + 0.25 * v_base_k)
    t_k_kinematic = rem_in_seg / v_eff_k
    
    # Thời gian động học toàn trình đến bến
    eta_kinematic_p50 = t_k_kinematic + (base_rem_p50 - rho * t_k_p50)
    delta_delay = max(0.0, eta_kinematic_p50 - base_rem_p50)
    is_delayed = (delta_delay >= REALTIME_DELAY_ALERT_SEC)

    # 4. TÍNH ĐỘ ĐỆM BẢO VỆ BẤT ĐỐI XỨNG & HÀM SUY GIẢM TRƠN BẬC 2
    if d_station > STATION_BUFFER_ATTEN_MAX_M:
        kappa = 1.0
    elif d_station <= STATION_BUFFER_ATTEN_MIN_M:
        kappa = 0.0
    else:
        xi = (d_station - STATION_BUFFER_ATTEN_MIN_M) / (STATION_BUFFER_ATTEN_MAX_M - STATION_BUFFER_ATTEN_MIN_M)
        kappa = 3.0 * (xi ** 2) - 2.0 * (xi ** 3)

    raw_buffer = kappa * (0.60 * sigma_accum + 7.5 + 0.04 * eta_kinematic_p50)
    delta_buffer = max(0.0, min(MAX_SAFE_BUFFER_CEILING_SEC, raw_buffer))
    
    conservative_eta = eta_kinematic_p50 + delta_buffer
    display_min = max(1, int(math.ceil(conservative_eta / 60.0)))
    display_text = "~1 phút" if display_min <= 1 else f"{display_min} phút"

    # Trạng thái giao thông
    if v_obs_kmh < CONGESTION_SPEED_THRESHOLD_KMPH or is_delayed:
        traffic_status = "UN_TAC"
    elif v_obs_kmh < FREEFLOW_SPEED_THRESHOLD_KMPH:
        traffic_status = "BINH_THUONG"
    else:
        traffic_status = "THONG_THOANG"

    safe_window = SafeWindowDTO(
        p10_seconds=round(max(0.0, base_rem_p10), 1),
        p50_seconds=round(max(0.0, eta_kinematic_p50), 1),
        p90_seconds=round(max(0.0, base_rem_p90 + delta_delay), 1),
        p10_minutes=max(1, int(math.ceil(base_rem_p10 / 60.0))),
        p90_minutes=max(1, int(math.ceil((base_rem_p90 + delta_delay) / 60.0))),
        conservative_eta_seconds=round(conservative_eta, 1),
        buffer_seconds=round(delta_buffer, 1),
        display_eta_minutes=display_min,
        is_delayed=is_delayed,
        delay_seconds=round(delta_delay, 1),
        recommended_arrival_time=format_epoch_hms(now_epoch + base_rem_p10)
    )

    return ApproachingBusDTO(
        vehicle_id=bus_state.vehicle.id,
        plate=bus_state.vehicle.plate,
        distance_to_station_m=round(d_station, 1),
        stops_remaining=stops_rem,
        eta_seconds=round(conservative_eta, 1),
        eta_minutes=round(conservative_eta / 60.0, 1),
        display_eta_minutes=display_min,
        display_text=display_text,
        safe_window=safe_window,
        speed_kmh=round(v_obs_kmh, 1),
        status="IN_TRANSIT",
        traffic_status=traffic_status,
        ping_time=format_epoch_iso(bus_state.t_ping),
        ping_age_seconds=round(bus_state.delta_t_age, 1),
        arrival_time_epoch=round(now_epoch + conservative_eta, 1)
    )
```

---

## 9. LƯỢC ĐỒ GIAO DIỆN VÀ DTO CHUẨN HÓA

### 9.1. Lớp DTO Cửa sổ An toàn (`SafeWindowDTO`)

```python
class SafeWindowDTO(BaseModel):
    p10_seconds: float = Field(..., description="Thời gian phân vị sớm P10 (giây)")
    p50_seconds: float = Field(..., description="Thời gian phân vị trung vị P50 có bù động học (giây)")
    p90_seconds: float = Field(..., description="Thời gian phân vị trễ P90 có cộng dồn trễ (giây)")
    p10_minutes: int = Field(..., description="Phút nguyên phân vị sớm P10")
    p90_minutes: int = Field(..., description="Phút nguyên phân vị trễ P90")
    conservative_eta_seconds: float = Field(..., description="Thời gian ETA bảo vệ hành khách (giây)")
    buffer_seconds: float = Field(..., description="Độ đệm an toàn bất đối xứng delta_buffer (giây)")
    display_eta_minutes: int = Field(..., description="Số phút nguyên hiển thị giao diện (ceil)")
    is_delayed: bool = Field(..., description="Cờ cảnh báo trễ/ùn ứ (> 120s so với baseline)")
    delay_seconds: float = Field(..., description="Thời gian trễ thực đo được so với baseline (giây)")
    recommended_arrival_time: str = Field(..., description="Mốc giờ khuyến nghị hành khách có mặt (HH:MM:SS)")
```

### 9.2. Lớp DTO Xe Tiếp cận Bến (`ApproachingBusDTO`)

```python
class ApproachingBusDTO(BaseModel):
    vehicle_id: int = Field(..., description="ID định danh phương tiện")
    plate: str = Field(..., description="Biển kiểm soát xe buýt (VD: 29B-205.54)")
    distance_to_station_m: float = Field(..., description="Khoảng cách dọc tuyến còn lại tới trạm (m)")
    stops_remaining: int = Field(..., description="Số trạm dừng còn lại trước khi tới trạm mục tiêu")
    eta_seconds: float = Field(..., description="ETA tính bằng giây")
    eta_minutes: float = Field(..., description="ETA tính bằng phút thập phân")
    display_eta_minutes: int = Field(..., description="Số phút nguyên làm tròn trần hiển thị")
    display_text: str = Field(..., description="Chuỗi văn bản hiển thị ('Đang cập bến', '~1 phút', '5 phút')")
    safe_window: SafeWindowDTO = Field(..., description="Cửa sổ thời gian an toàn chi tiết")
    speed_kmh: float = Field(..., description="Vận tốc tức thời từ GPS (km/h)")
    status: str = Field(..., description="Trạng thái: 'ARRIVING_NOW' | 'IN_TRANSIT'")
    traffic_status: str = Field(..., description="Mật độ giao thông: 'THONG_THOANG' | 'BINH_THUONG' | 'UN_TAC'")
    ping_time: str = Field(..., description="Thời điểm ghi nhận ping GPS gốc (ISO 8601)")
    ping_age_seconds: float = Field(..., description="Tuổi của gói tin viễn trắc (giây)")
    arrival_time_epoch: float = Field(..., description="Mốc epoch dự kiến cập bến (giây)")
```

---

## 10. TIÊU CHUẨN NGHIỆM THU ĐỘC LẬP (VERIFIABLE ACCEPTANCE TEST MATRIX)

Dành riêng cho `@blind_tester` và `@peer_review` thực thi kiểm thử hộp đen:

| Mã Kiểm thử | Kịch bản Thử nghiệm | Dữ liệu Đầu vào | Kỳ vọng Bắt buộc (Pass Criteria) | Bất biến Bảo vệ |
| :--- | :--- | :--- | :--- | :--- |
| **TC-01** | Xe cận bến cự ly $8.0\text{m}$ | $s_{\text{target}} = 1000\text{m}, s_{\text{bus}} = 992\text{m}$, $v = 15\text{ km/h}$ | `status == "ARRIVING_NOW"`<br>`display_text == "Đang cập bến"`<br>`approaching_count == 1` | Xóa sổ điểm gián đoạn 10m; xe không được phép biến mất! |
| **TC-02** | Xe vừa chớm qua biển trạm $+12\text{m}$ | $s_{\text{target}} = 1000\text{m}, s_{\text{bus}} = 1012\text{m}$, $v = 0\text{ km/h}$ | `status == "ARRIVING_NOW"`<br>`display_text == "Đang cập bến"`<br>`approaching_count == 1` | Bảo vệ xe dừng mở cửa trả khách sau cột biển báo. |
| **TC-03** | Xe đã qua bến hoàn toàn $+25\text{m}$ | $s_{\text{target}} = 1000\text{m}, s_{\text{bus}} = 1025\text{m}$ | `approaching_count == 0` | Ngắt phục vụ dứt khoát khi xe thoát khỏi bến. |
| **TC-04** | Telemetry bị stale 400 giây | $\Delta t_{\text{age}} = 400.0\text{s} > 300.0\text{s}$ | `approaching_count == 0`<br>Không tính ETA | Loại bỏ $100\%$ xe ma tắt máy/mất sóng. |
| **TC-05** | Xe ngược chiều trên đường đôi | $v = 30\text{ km/h}$, $\theta_{\text{bus}} = 225^\circ$, $\theta_{\text{route}} = 45^\circ$, $d_{\text{perp}} = 15\text{m}$ | `cos(Delta_theta) ≈ -1.0`<br>`approaching_count == 0` | Loại bỏ $100\%$ xe ngược chiều lọt vào corridor $35\text{m}$. |
| **TC-06** | Ùn tắc nghiêm trọng tại chỗ | $v = 0.5\text{ km/h}$, $d_{\text{station}} = 300\text{m}$, Baseline = $45\text{s}$ | `traffic_status == "UN_TAC"`<br>`is_delayed == True`<br>`delay_seconds > 120.0s`<br>`eta_seconds > 180.0s` | Khôi phục ý nghĩa thực tế của cảnh báo trễ và tắc đường. |
| **TC-07** | Bù đắp trễ viễn trắc thông thường | $\Delta t_{\text{age}} = 60.0\text{s}$, $v = 36\text{ km/h}$, Baseline $18\text{ km/h}$ | $s_{\text{now}} > s_{\text{ping}} + 300\text{m}$<br>ETA giảm tương ứng với quãng đường đã đi | Chấm dứt giả định "đóng băng thời gian". |
| **TC-08** | Tính liên tục của hàm ETA cận bến | Đo ETA tại $d = 31.0\text{m}$ và $d = 29.0\text{m}$ | ETA chuyển tiếp từ $\approx 2.0\text{s}$ sang $0.0\text{s}$ mà không bị kẹp sàn $15.0\text{s}$ gượng ép | Bãi bỏ hoàn toàn các hàm clamp `floor_p50`. |
| **TC-09** | Thanh lọc rác cấu hình | Rà soát `config/system_config.py` | Không chứa bất kỳ hằng số TimBus nào (`TIMBUS_...`) | Đạt chuẩn Single Source of Truth & Simplicity First. |
| **TC-10** | Tính đơn điệu lượng tử hóa phút | Quét chuỗi $d \in [200\text{m}, 20\text{m}]$ | $M_{\text{disp}}(d_1) \ge M_{\text{disp}}(d_2)$ khi $d_1 > d_2$ | Không rung lắc hiển thị số phút. |

---

## 11. HƯỚNG DẪN BÀN GIAO TRIỂN KHAI (HANDOFF DIRECTIVE)

1. **Đối với `@leaf_coder`:**
   - Đọc kỹ SPEC-15 trước khi sửa đổi bất kỳ dòng mã nguồn nào.
   - Triển khai chính xác 2 hàm `project_filter_and_extrapolate_vehicle` và `compute_kinematic_station_eta` vào `busmap_service.py`.
   - Di chuyển toàn bộ các hằng số quy định tại Mục 7 vào `config/system_config.py`. Xóa sạch dead code TimBus.
   - Không được sáng tác thêm bất kỳ magic number hoặc if-else vá víu nào.
2. **Đối với `@blind_tester`:**
   - Dựng file test suite `tests/test_spec15_kinematics_and_serving.py` dựa trên 10 test case trong Ma trận Nghiệm thu Mục 10.
   - Chạy test kiểm chứng và báo cáo trực tiếp log đầu ra.
