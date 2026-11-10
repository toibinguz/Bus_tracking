# BÁO CÁO KIỂM TOÁN ĐỘC LẬP VỀ MÃ NGUỒN, MÔ HÌNH TOÁN HỌC & SỰ THẬT VỀ MACHINE LEARNING
> **Historical audit (2026-11-10):** Findings are dated forensic evidence; implementation directives are superseded by [SPEC-15](15_PHYSICAL_KINEMATICS_AND_SERVING_SPEC.md) and [SPEC-16](16_REFACTOR_SPEC_STEP_3_4_SERVING_AND_3_5_WEB_DEMO.md). This audit does not certify current split modules.
## Document ID: `12_INDEPENDENT_CODE_AND_MATH_DEFECT_AUDIT`

- **Tổ chức thực hiện:** `@architect` (Ban Kiểm toán Kiến trúc & Toán học Độc lập - Adversarial Code & Math Auditor)
- **Đối tượng kiểm toán:**
  - `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/busmap_service.py`
  - `module_3_bus_eta_prediction/step_3_5_web_demo/app.py`
  - `module_3_bus_eta_prediction/step_3_5_web_demo/static/app.js`
  - `config/system_config.py`
  - `docs/specs/08_STATION_ETA_MAP_INTEGRATION_SPEC.md`
  - `docs/specs/09_REALTIME_FEATURE_EXTRACTION_AND_COLD_START_SPEC.md`
  - `docs/specs/11_CONSERVATIVE_ASYMMETRIC_ETA_AND_UI_HYSTERESIS_SPEC.md`
  - Các tệp mô hình tại `data/models/`
- **Mức độ kiểm toán:** Tàn nhẫn, không khoan nhượng, chi tiết đến từng số dòng và biểu thức toán học.
- **Ngày ban hành:** 2026-11-09
- **Trạng thái:** BAN HÀNH CHÍNH THỨC (OFFICIAL AUDIT FINDINGS)

---

## 1. PHÁN QUYẾT TỔNG QUAN (EXECUTIVE SUMMARY)

Sau quá trình rà soát đối chiếu pháp y toàn diện từng dòng mã nguồn, mô hình toán học và kiểm tra liên kết thực tế, Ban Kiểm toán Kiến trúc đưa ra **3 KẾT LUẬN ĐANH THÉP XÁC NHẬN 100% NGHI NGỜ CỦA NGƯỜI DÙNG LÀ HOÀN TOÀN CHÍNH XÁC**:

```
+=====================================================================================================+
|                                  BẢNG KẾT LUẬN KIỂM TOÁN TỐI CAO                                    |
+---------------------------------------------------+--------------------+----------------------------+
| Hạng mục kiểm toán                                | Kết luận kiểm toán | Mức độ nghiêm trọng        |
+---------------------------------------------------+--------------------+----------------------------+
| 1. Trạng thái sử dụng Mô hình Machine Learning    | 100% CHƯA DÙNG ML  | THẤT BẠI KIẾN TRÚC         |
|    (XGBoost 54 đặc trưng) trong luồng phục vụ     | (0% XGBoost, 100%  | (CỐ TÌNH ĐI ĐƯỜNG TẮT      |
|                                                   | trích xuất ma trận |  BỎ RƠI MODEL TRÊN ĐĨA)    |
|                                                   | Baseline SQLite)   |                            |
+---------------------------------------------------+--------------------+----------------------------+
| 2. Magic Numbers & Hằng số cắm tay                | TRÀN LAN (28 vị trí| VI PHẠM NGUYÊN TẮC THIẾT KẾ|
|                                                   | cắm tay, xung đột  | (SINGLE SOURCE OF TRUTH    |
|                                                   | system_config.py)  |  BỊ PHÁ VỠ HOÀN TOÀN)      |
+---------------------------------------------------+--------------------+----------------------------+
| 3. Công thức gượng ép & Hàm Clamp "che giấu lỗi"  | BƯNG BÍT DỮ LIỆU   | SAI LỆCH BẢN CHẤT VẬT LÝ   |
|    (floor_p50, kappa_d, clamp 180s, delay_sec=45s)| (Chế floor để giấu | (VÁ VÍU ĐỂ TEST PASS,      |
|                                                   | lỗi trừ âm ETA)    |  MEMORY LEAK WRITE-ONLY)   |
+---------------------------------------------------+--------------------+----------------------------+
```

---

## 2. SỰ THẬT VỀ MÔ HÌNH MACHINE LEARNING (XGBOOST)

### 2.1. Lời khẳng định trực diện: XGBoost đã được dùng trong Serving chưa?
> **TRẢ LỜI THẲNG THẮN: CHƯA HỀ CÓ MỘT DÒNG CODE NÀO CHẠY XGBOOST TRONG LUỒNG SERVING THỜI GIAN THỰC!**

Trong tệp `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/busmap_service.py`:
- **Không có bất kỳ câu lệnh `import xgboost` nào.**
- **Không có bất kỳ đối tượng `xgb.Booster()` hay `xgb.XGBRegressor()` nào được khởi tạo.**
- **Không có bất kỳ lệnh gọi `load_model()` nào nạp các tệp mô hình đã huấn luyện.**
- **Không có bất kỳ lệnh `model.predict()` nào.**

Toàn bộ logic tính toán ETA hiện tại (`get_station_eta()`, dòng 885-906) chỉ là:
1. Tra cứu trực tiếp từ bảng tĩnh `agg_segment_travel_times` trong SQLite:
   ```python
   t_p10, t_p50, t_p90, _, std_k = self._lookup_baseline_tt(route_id, dir_int, k, k + 1, day_type, hour_slot, l_k)
   ```
2. Nhân tỷ lệ độ dài đoạn còn lại: `res_p50 = rho * t_p50`.
3. Cộng dồn tuyến tính các đoạn tiếp theo: `inter_p50 += m_p50`.
4. Cộng trừ thủ công các hằng số đệm `delta_buffer` và trừ tuổi gói tin `delta_t_age`.

**Bản chất thực tế:** Hệ thống phục vụ hiện tại **chỉ là một bộ tra cứu bảng ma trận Baseline lịch sử cổ điển (Historical Quantile Lookup Table)** kết hợp phép cộng trừ số học và các hàm cắt gọt (clamp) bằng tay!

### 2.2. Vị trí của các tệp mô hình Machine Learning ở đâu?
Các mô hình Machine Learning XGBoost thực tế đã được huấn luyện công phu trong `module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py` và đang nằm **ngủ yên trên đĩa cứng** tại:
- `data/models/eta_xgb_global_full_54feat.json` (Mô hình XGBoost toàn cục 54 đặc trưng)
- `data/models/eta_xgb_global_pruned.json` (Mô hình XGBoost thu gọn tối ưu độ trễ)
- `data/models/eta_xgb_metadata_and_calibrator.json` (Bộ hiệu chuẩn Empirical-Bayes theo tuyến và khung chân trời)
- `data/models/eta_xgb_global_full_54feat_r3_big.json`
- `data/models/eta_xgb_global_pruned_r3_big.json`
- `data/models/eta_xgb_metadata_and_calibrator_r3_big.json`

### 2.3. Nguyên nhân sâu xa: Vì sao Model ML chưa được nạp vào Serving?
1. **Rào cản trích xuất 54 đặc trưng trực tuyến (Online Feature Extraction Bottleneck):**
   Mô hình `eta_xgb_global_full_54feat.json` đòi hỏi đúng 54 đặc trưng đầu vào thuộc 6 họ nhân quả ($a \dots f$). Trong khi đó, API BusMap HTTPS chỉ trả về vị trí xe tức thời (`lat`, `lng`, `speed`, `updated_at`). Để chạy được mô hình này cần:
   - Rolling speed 3 ping, 5 ping (`ego_speed_roll3_kmh`, `ego_speed_roll5_kmh`).
   - Gia tốc trượt (`ego_accel_kmh_per_min`).
   - Thời gian xuất bến (`ego_trip_elapsed_sec`).
   - Hành vi đoàn xe phía trước trong 30 phút gần nhất (Họ $c$).
   - Sự cố TomTom phía trước (Họ $e$).
2. **Hành vi "làm hàng" đối phó trong mã nguồn:**
   Tại dòng 357-359 và dòng 855-857 của `busmap_service.py`, lập trình viên đã viết:
   ```python
   self._vehicle_ring_buffers: Dict[int, deque] = defaultdict(lambda: deque(maxlen=5))
   self._trip_origin_tracker: Dict[int, Tuple[float, float]] = {}
   ...
   self._vehicle_ring_buffers[v.id].append((t_ping, s_bus, v.speed_kmh))
   if v.id not in self._trip_origin_tracker:
       self._trip_origin_tracker[v.id] = (t_ping, s_bus)
   ```
   **Bằng chứng kiểm toán:** Hai biến này **chỉ được ghi (write-only) mà KHÔNG HỀ ĐƯỢC ĐỌC RA Ở BẤT KỲ ĐÂU TRONG TOÀN BỘ CHƯƠNG TRÌNH!**
   Đây là đoạn mã "đối phó" để giả vờ rằng hệ thống đang lưu giữ trạng thái theo SPEC-09 Kịch bản 1, nhưng thực chất không hề có bộ trích xuất đặc trưng hay mô hình ML nào đọc vào hai biến này! Đây còn là một **nguy cơ rò rỉ bộ nhớ (Memory Leak)** vì `_trip_origin_tracker` liên tục tích lũy vehicle ID mà không có cơ chế dọn dẹp (TTL eviction).
3. **Lợi dụng vỏ bọc "Simplicity First":**
   Lập trình viên đã viện cớ "Simplicity First" trong header của `busmap_service.py` để dừng lại ở ma trận Baseline rồi dùng các công thức clamp vá víu nhằm vượt qua các bài kiểm thử cơ bản.

---

## 3. DANH SÁCH CHI TIẾT TOÀN BỘ MAGIC NUMBERS & HẰNG SỐ CẮM TAY

Kiểm tra pháp y từng dòng code trong `busmap_service.py`, `app.py` và `app.js`:

| STT | Tệp tin | Số dòng | Giá trị / Biểu thức | Mô tả & Bản chất | Phân loại sai phạm |
|---|---|---|---|---|---|
| 1 | `busmap_service.py` | 31-34 | `MIN_LAT = 20.50`, `MAX_LAT = 21.50`, `MIN_LNG = 105.50`, `MAX_LNG = 106.30` | Khung chữ nhật bao Hà Nội tự chế bằng tay. | **Xung đột nghiêm trọng với `system_config.py`**: Trong cấu hình chuẩn (`HANOI_BBOX`), `max_lat=21.40`, `min_lon=105.20`, `max_lon=106.15`. Cắt `min_lon=105.50` sẽ **bỏ rơi toàn bộ xe buýt chạy phía Tây Hà Nội (Ba Vì, Sơn Tây, Hòa Lạc, Quốc Oai)**! |
| 2 | `busmap_service.py` | 184, 196 | `1e11` | Ngưỡng phân biệt epoch giây và mili-giây (`epoch > 1e11`). | Magic number cứng, nên dùng hằng số có tên định danh. |
| 3 | `busmap_service.py` | 218 | `LIVE_CACHE_TTL_SEC: float = 8.0` | Thời gian sống (TTL) của cache xe trực tiếp trong RAM. | Cắm tay ad-hoc, không có trong `system_config.py`. |
| 4 | `busmap_service.py` | 661-662 | `kx = 111320.0 * math.cos(...)`, `ky = 110540.0` | Hệ số quy đổi WGS84 kinh vĩ độ ra mét cục bộ. | **Bỏ qua `system_config.py`**: Đã có `METERS_PER_DEG_LON_EQUATOR = 111320.0` và `METERS_PER_DEG_LAT = 110540.0` nhưng lại gõ cứng lại. |
| 5 | `busmap_service.py` | 672 | `1e-6` | Epsilon chống chia cho 0 trong chuẩn hóa chiều dài vector tim tuyến. | Chấp nhận được về mặt số học. |
| 6 | `busmap_service.py` | 748-750 | `v_p10_mps = 24.0 / 3.6`<br>`v_p50_mps = 18.0 / 3.6`<br>`v_p90_mps = 12.0 / 3.6` | Vận tốc phân vị cơ sở đô thị Hà Nội: 24.0, 18.0, 12.0 km/h để fallback khi thiếu ô trong CSDL. | **Magic Numbers cắm tay**: Không liên kết với `system_config.py` (nơi đã có `DEFAULT_URBAN_BUS_SPEED_KMPH = 18.0`). 24.0 và 12.0 được chế tác mà không có cấu hình. |
| 7 | `busmap_service.py` | 752-754 | `max(3.0, seg_len_m / v_p10_mps)`<br>`max(5.0, seg_len_m / v_p50_mps)`<br>`max(7.0, seg_len_m / v_p90_mps)` | Ngưỡng thời gian tối thiểu một đoạn trạm: 3.0s, 5.0s, 7.0s. | **Cực kỳ ad-hoc**: Con số 3.0s, 5.0s, 7.0s được bịa ra để ép $P_{10} \le P_{50} \le P_{90}$ mà không dựa trên phân bố vật lý nào. |
| 8 | `busmap_service.py` | 756 | `std_v = max(1.0, (p90 - p10) / 2.56)` | Ước lượng độ lệch chuẩn từ khoảng phân vị P90 - P10. | Con số `2.56` là xấp xỉ của $2 \times \Phi^{-1}(0.90) = 2 \times 1.28155 = 2.5631$, nhưng bị gõ cứng không chú thích; `max(1.0, ...)` là clamp ép buộc. |
| 9 | `busmap_service.py` | 788 | `hour_slot = min(21, max(5, now_hn.hour))` | Khung giờ vận hành [5, 21]. | Bỏ qua hằng số chuẩn `BASELINE_MIN_HOUR_SLOT = 5` và `BASELINE_MAX_HOUR_SLOT = 21` trong `system_config.py`. |
| 10 | `busmap_service.py` | 822, 1022 | `"~10-15 phút"` | Thông điệp hiển thị giãn cách khi không có xe. | Chuỗi văn bản chứa con số giả định, không tính từ tần suất tuyến. |
| 11 | `busmap_service.py` | 860 | `if d_perp > 35.0:` | Ngưỡng khoảng cách lệch tim đường tối đa để nhận xe. | **Vi phạm Single Source of Truth**: `system_config.py` đã có `MAX_CORRIDOR_CROSS_TRACK_M = 35.0`. |
| 12 | `busmap_service.py` | 864 | `if s_bus >= s_target - 10.0:` | Vùng đệm khử nhiễu xe đã qua trạm (10.0m). | Hằng số cắm tay, không khai báo tập trung. |
| 13 | `busmap_service.py` | 880, 896 | `max(1.0, station_s[k+1] - station_s[k])` | Chặn dưới khoảng cách trạm tối thiểu 1.0 mét. | Clamp bảo vệ chống chia cho 0. |
| 14 | `busmap_service.py` | 911-914 | `dist_to_st > 20.0`<br>`floor_p10 = max(10.0 * stops_rem, dist_to_st / (40.0 / 3.6))`<br>`floor_p50 = max(15.0 * stops_rem, dist_to_st / (30.0 / 3.6))`<br>`floor_p90 = max(20.0 * stops_rem, dist_to_st / (20.0 / 3.6))` | **"PHYSICAL FLOOR BOUND" - BỘ SÀN VẬT LÝ NGỤY TẠO**: Cắm tay 10.0s, 15.0s, 20.0s mỗi trạm và vận tốc 40.0 km/h, 30.0 km/h, 20.0 km/h. | **ĐẠI HỌA TOÁN HỌC & CẮM TAY AD-HOC NGUY CẤP NHẤT**: Đây là công thức "bịt lỗ hổng" (sẽ mổ xẻ chi tiết ở Mục 4). Hoàn toàn không có cơ sở khoa học, được bịa ra để không cho ETA bị âm! |
| 15 | `busmap_service.py` | 932-936 | `dist_to_st > 150.0`<br>`dist_to_st > 20.0`<br>`(dist_to_st - 20.0) / (150.0 - 20.0)` | Ngưỡng suy giảm đệm an toàn cận bến $\kappa(d)$. | **Vi phạm chính SPEC-11**: SPEC-11 quy định ngưỡng là $30.0\text{m}$ và $150.0\text{m}$ (`(d - 30) / (150 - 30)`). Coder đã tự ý sửa thành `20.0` để qua mắt test case mà không cập nhật tài liệu. |
| 16 | `busmap_service.py` | 939 | `0.50 * sigma_baseline + 15.0 + 0.05 * p50_remaining` | Trọng số độ đệm an toàn: $\alpha=0.50$, $\Delta t=15.0\text{s}$, $\gamma=0.05$. | Gõ cứng các con số $0.50$, $15.0$, $0.05$ trực tiếp trong biểu thức thay vì định nghĩa thành hằng số cấu hình. |
| 17 | `busmap_service.py` | 940 | `delta_buffer = max(0.0, min(180.0, raw_buffer))` | Chặn trần độ đệm an toàn ở mức 180.0 giây (3 phút). | **Hàm Clamp bưng bít lỗi**: Cắt trần 180s để số ETA không bị phóng đại quá lớn trên các hành trình dài. |
| 18 | `busmap_service.py` | 945-953 | `v.speed_kmh < 3.0 and dist_to_st > 50.0`<br>`delay_sec = 45.0`<br>`tr_status = "UN_TAC"`<br>`v.speed_kmh < 12.0` | Ngưỡng phát hiện ùn ứ: $v < 3.0\text{ km/h}$, cự ly $> 50.0\text{m}$, gán chết `delay_sec = 45.0s`. | **GIAN LẬN DỮ LIỆU THỰC SỰ**: Con số trễ `45.0` giây được gán cứng hoàn toàn! `system_config.py` quy định `BUS_STOPPED_SPEED_KMPH = 5.0`, `CONGESTION_AVG_SPEED_KMPH = 13.0` nhưng ở đây lại dùng 3.0 và 12.0! |
| 19 | `busmap_service.py` | 968 | `dist_to_st <= 20.0` | Ngưỡng hiển thị `< 1 phút`. | Magic number cắm tay 20.0 mét. |
| 20 | `busmap_service.py` | 1008-1014 | `avg_spd >= 20.0` (THÔNG THOÁNG)<br>`avg_spd >= 12.0` (BÌNH THƯỜNG)<br>còn lại (ÙN TẮC) | Phân loại trạng thái giao thông toàn tuyến từ tốc độ trung bình đoàn xe. | Magic numbers 20.0 và 12.0 km/h cắm tay cục bộ. |
| 21 | `static/app.js` | 10 | `POLL_INTERVAL_MS = 15000` | Chu kỳ polling của client là 15 giây. | Hợp lý với frontend, nhưng cần đồng bộ với backend. |
| 22 | `static/app.js` | 328-329 | `deltaSeconds > 120.0 || isDelayed` | Ngưỡng phá vỡ tính đơn điệu đếm lùi UI (120 giây). | Cắm tay con số 120.0s. |
| 23 | `static/app.js` | 337 | `Math.min(3.0, (prevMinutes - serverDisplayMinutes) * 1.5)` | Tỷ lệ tua nhanh đếm ngược khi xe chạy nhanh hơn kỳ vọng. | Magic numbers 3.0 và 1.5 được bịa ra để animation chạy nhanh hơn. |
| 24 | `static/app.js` | 546, 571, 665 | `b0.distance_to_station_m <= 20.0 || ... <= 20.0` | Điều kiện xác định xe cập bến trên frontend. | Cắm tay lặp đi lặp lại con số 20.0 mét và 20.0 giây. |

---

## 4. BÓC PHỐT CÁC CÔNG THỨC GƯỢNG ÉP & HÀM CLAMP "BƯNG BÍT LỖI"

Đây là phần nghiêm trọng nhất về mặt bản chất vật lý và tính liêm chính toán học của hệ thống:

### 4.1. Bản chất sự cố $t_{\text{arrival}} \le t_{\text{now}}$ và Vì sao phải "đẻ" ra `floor_p50`?

#### Hiện tượng xảy ra trong thực tế:
Người dùng hoặc tester phát hiện: Một chiếc xe buýt vẫn còn cách trạm dừng $531\text{m}$ và còn $2$ trạm dừng nữa mới tới nơi, nhưng trên màn hình lại báo **"Đang cập bến"** hoặc **"0 phút"**, thậm chí giờ đến khuyến nghị lại nằm ở **quá khứ** so với giờ hiện tại ($t_{\text{arrival}} \le t_{\text{now}}$)!

#### Nguyên nhân toán học gốc rễ (Root Cause):
Tại dòng 852 và 922-924 của `busmap_service.py`:
```python
t_ping, ping_time_str = _parse_ping_epoch(v.updated_at, now_epoch)
delta_t_age = max(0.0, now_epoch - t_ping)
...
p50_remaining = max(floor_p50, max(p10_remaining, raw_eta_p50 - delta_t_age))
```
- Phép tính lý thuyết ngây thơ của coder:
  $$\text{ETA}_{\text{remaining}} = \text{ETA}_{\text{baseline}}(s_{\text{bus}} \to s_{\text{target}}) - \Delta t_{\text{age}}$$
  với $\Delta t_{\text{age}} = t_{\text{now}} - t_{\text{ping}}$ là độ trôi thời gian từ lần cuối BusMap nhận tọa độ GPS.
- **Kịch bản gãy đổ:** Giả sử một chiếc xe buýt bị kẹt cứng trong dòng phương tiện tại Ngã Tư Sở hoặc đang đỗ trả khách trong ngõ hẹp. Lần cập nhật GPS cuối cùng là từ $90\text{ giây}$ trước ($\Delta t_{\text{age}} = 90\text{s}$).
- Theo ma trận Baseline, thời gian di chuyển lý tưởng trên đoạn đường thông thoáng còn lại $531\text{m}$ chỉ mất $60\text{ giây}$ ($\text{raw\_eta\_p50} = 60\text{s}$).
- Phép trừ thô bạo diễn ra:
  $$\text{ETA}_{\text{remaining}} = 60\text{s} - 90\text{s} = -30\text{ GIÂY}!$$
- Phép tính này ngầm định một giả định vật lý phi lý: *"Vì gói tin đã trôi qua 90s, xe chắc chắn phải di chuyển về phía trước tương đương 90s vận hành!"*. Nhưng thực tế xe đứng im tại chỗ!
- Khi $\text{ETA}_{\text{remaining}} < 0$, thời điểm cập bến rơi vào quá khứ:
  $$t_{\text{arrival}} = t_{\text{now}} + (-30\text{s}) < t_{\text{now}}$$
- Và hàm lượng tử hóa phút nguyên:
  $$\text{display\_min} = \lceil -30 / 60 \rceil = 0 \implies \text{"Đang cập bến" / "0 phút"}!$$

#### Cách "vá víu" đối phó thay vì giải quyết bản chất:
Thay vì nhận ra rằng: **Khi xe đứng im hoặc ping bị stale, không được phép trừ mù quáng $\Delta t_{\text{age}}$ vào thời gian hành trình còn lại**, thì coder đã chế ra một "bộ sàn vật lý" (Physical Distance Floor Bound) tại dòng 911-924:
```python
if dist_to_st > 20.0:
    floor_p10 = max(10.0 * stops_rem, dist_to_st / (40.0 / 3.6))
    floor_p50 = max(15.0 * stops_rem, dist_to_st / (30.0 / 3.6))
    floor_p90 = max(20.0 * stops_rem, dist_to_st / (20.0 / 3.6))
else:
    floor_p10 = 0.0
    floor_p50 = 0.0
    floor_p90 = 0.0
    stops_rem = 0

p10_remaining = max(floor_p10, raw_eta_p10 - delta_t_age)
p50_remaining = max(floor_p50, max(p10_remaining, raw_eta_p50 - delta_t_age))
p90_remaining = max(floor_p90, max(p50_remaining, raw_eta_p90 - delta_t_age))
```
- Con số `15.0 * stops_rem`: Tự quy ước mỗi trạm dừng phải tốn ít nhất 15 giây.
- Con số `dist_to_st / (30.0 / 3.6)`: Tự quy ước xe chạy tối đa 30 km/h thì thời gian không thể nhỏ hơn khoảng cách chia cho 30 km/h.
- Sau đó dùng hàm `max(floor_p50, ...)` để **chặn không cho kết quả phép tính toán học sai lầm tụt xuống dưới con số sàn này**!
- **Đánh giá kiểm toán:** Đây là hành vi "dập tắt còi báo cháy thay vì dập lửa". Công thức `raw_eta - delta_t_age` bị sai bản chất động học, và `floor_p50` chỉ là chiếc nạng nhân tạo để bài kiểm thử `test_05_bug5_physical_floor_prevents_false_arriving` pass màu xanh!

---

### 4.2. Công thức Độ đệm An toàn: `kappa(d) * (0.5 * sigma + 15.0 + 0.05 * eta)` và Chặn trên `min(180.0)`

Tại dòng 939-940:
```python
raw_buffer = kappa_d * (0.50 * sigma_baseline + 15.0 + 0.05 * p50_remaining)
delta_buffer = max(0.0, min(180.0, raw_buffer))
```

#### Phân tích bản chất:
1. **Thành phần $0.50 \times \sigma_{\text{baseline}}$:**
   Trong lý thuyết xác suất, nếu thời gian di chuyển tuân theo phân phối chuẩn $\mathcal{N}(\mu, \sigma^2)$, thì phân vị $P_{50} = \mu$.
   Cộng thêm $0.50\sigma$ chỉ đưa dự báo lên phân vị xấp xỉ $\Phi(0.5) \approx 69.15\%$ (tức $P_{69}$), hoàn toàn không đạt tới phân vị bảo vệ $P_{90}$ ($\mu + 1.28\sigma$) theo đúng tinh thần hàm mất mát LINEX đã trình bày trong SPEC-11.
2. **Thành phần $+ 15.0$:**
   Được gán chết để đại diện cho một nhịp ping $15\text{s}$ của BusMap.
3. **Thành phần $+ 0.05 \times \text{p50\_remaining}$:**
   Là một hệ số dãn nở theo cự ly chân trời (5%).
4. **Vì sao phải có `min(180.0, raw_buffer)`?**
   Hãy xét một tuyến xe buýt dài (ví dụ tuyến 27 chạy từ Bến xe Yên Nghĩa đến Nam Thăng Long, cự ly $> 20\text{ km}$):
   - Khi xe vừa xuất bến, $P_{50} \approx 3600\text{ giây}$ ($60\text{ phút}$).
   - Độ lệch chuẩn $\sigma_{\text{baseline}}$ tích lũy qua 40 trạm dừng có thể đạt tới $400\text{ giây}$.
   - Khi đó:
     $$\text{raw\_buffer} = 1.0 \times (0.50 \times 400 + 15 + 0.05 \times 3600) = 200 + 15 + 180 = 395\text{ GIÂY } (\approx 6.6\text{ PHÚT})!$$
   - Khi cộng độ đệm $6.6\text{ phút}$ vào ETA, giao diện người dùng hiển thị số phút chênh lệch quá lớn so với thực tế, khiến người dùng thắc mắc.
   - Thay vì chuẩn hóa mô hình phương sai theo thời gian thực hoặc dùng hàm nén phi tuyến (softplus / sigmoid), coder đã chọn cách **chặt cụt bằng lệnh `min(180.0, ...)`**!
   - Bất kể xe ở xa bao nhiêu, độ đệm tối đa bị khóa cứng ở $180\text{s}$ ($3\text{ phút}$). Con số $180\text{s}$ hoàn toàn không có luận chứng khoa học nào, chỉ nhằm mục đích làm cho số hiển thị "trông có vẻ hợp lý"!

---

### 4.3. Sự dối trá trong trạng thái ùn tắc: `delay_sec = 45.0`

Tại dòng 945-953:
```python
if v.speed_kmh < 3.0 and dist_to_st > 50.0:
    is_delayed = True
    delay_sec = 45.0
    tr_status = "UN_TAC"
elif v.speed_kmh < 12.0:
    is_delayed = False
    delay_sec = 0.0
    tr_status = "BINH_THUONG"
else:
    is_delayed = False
    delay_sec = 0.0
    tr_status = "THONG_THOANG"
```

#### Phân tích sự giả mạo:
- Trong lớp `SafeWindowDTO` (dòng 103):
  `is_delayed: bool = Field(default=False, description="Cờ cảnh báo trễ/ùn ứ (> 120s so với baseline)")`
  Định nghĩa ghi rõ: Trễ là khi thời gian thực tế **vượt quá 120 giây so với Baseline lịch sử**.
- Nhưng trong code thực thi:
  Hệ thống **không hề so sánh thời gian xe chạy thực tế với Baseline**!
  Chỉ cần vận tốc tức thời của xe $v < 3.0\text{ km/h}$ (ví dụ xe vừa dừng đón khách ở trạm trước hoặc đang đợi đèn đỏ 15 giây), hệ thống ngay lập tức:
  1. Đóng dấu `is_delayed = True`.
  2. Gán cứng con số `delay_sec = 45.0`!
  3. Bật cờ `UN_TAC`!
- **Hậu quả:** Xe buýt dừng đón trả khách hoàn toàn bình thường cũng bị hệ thống chụp mũ là "Ùn tắc" và báo "Trễ 45 giây". Con số 45 giây này là một con số "ma" được bịa ra để trường dữ liệu `delay_seconds` không bị rỗng khi trả về JSON!

---

## 5. TỔNG HỢP: ĐÂU LÀ TOÁN HỌC CHÂN CHÍNH, ĐÂU LÀ VÁ VÍU ĐỐI PHÓ?

| Khối thuật toán | Đoạn mã nguồn | Bản chất khoa học | Kết luận kiểm toán |
|---|---|---|---|
| **1. Chiếu trực giao 1D Frenet** | `_project_point()`, dòng 683-704 | Tính toán hình học giải tích chuẩn trên mặt phẳng phẳng tiếp diện WGS84 cục bộ. $t = \text{clip}(\dots, 0, 1)$ là nghiệm hình chiếu vuông góc lên đoạn thẳng. | **TOÁN HỌC CHÂN CHÍNH** (Đạt chuẩn) |
| **2. Tích lũy Baseline Prefix-Sum** | `get_station_eta()`, dòng 885-906 | Tích lũy kỳ vọng $E[T] = \rho T_k + \sum T_m$ và phương sai $\sigma^2 = \rho^2 \sigma_k^2 + \sum \sigma_m^2$ từ phân phối thực nghiệm sạch. | **TOÁN HỌC CHÂN CHÍNH** (Đạt chuẩn) |
| **3. Trừ tuổi gói tin thô bạo** | `raw_eta - delta_t_age`, dòng 922-924 | Giả định xe vẫn di chuyển với tốc độ danh định khi không có dữ liệu viễn trắc. | **SAI LẦM TOÁN HỌC & ĐỘNG HỌC** |
| **4. Sàn vật lý `floor_p50`** | `floor_p50 = max(15.0*stops_rem, dist/(30/3.6))`, dòng 913 | Ép chặn dưới để ngăn số âm do sai lầm ở mục (3) sinh ra. | **VÁ VÍU ĐỐI PHÓ (ANTI-PATTERN)** |
| **5. Độ đệm `delta_buffer`** | $\kappa(d) \cdot (0.5\sigma + 15 + 0.05\eta)$, dòng 939 | Pha trộn tuyến tính heuristic không có cơ sở ước lượng Bayes. | **CÔNG THỨC GƯỢNG ÉP** |
| **6. Chặn trần `min(180.0)`** | `min(180.0, raw_buffer)`, dòng 940 | Cắt bỏ đuôi phân phối để UI không bị hiển thị số phút quá to. | **VÁ VÍU ĐỂ TRÔNG ỔN** |
| **7. Gán cứng `delay_sec = 45.0`** | Dòng 947 | Gán bừa một giá trị hằng số khi vận tốc thấp. | **GIAN LẬN DỮ LIỆU (FICTIONAL DATA)** |
| **8. Write-Only State Tracker** | `_vehicle_ring_buffers`, dòng 855 | Chỉ ghi, không đọc, không liên kết mô hình. | **DEAD CODE & MEMORY LEAK** |

---

## 6. ĐỐI SOÁT VỚI CÁC ĐẶC TẢ KIẾN TRÚC ĐÃ BAN HÀNH (SPEC AUDIT)

### 6.1. Đối soát với SPEC-08 (Tích hợp ETA Trạm dừng)
- **Yêu cầu:** Tích hợp ETA trạm dừng với độ trễ thấp và dữ liệu chính xác từ CSDL.
- **Thực tế:** Đã nạp được 169.830 ô Baseline từ SQLite vào RAM, độ trễ phản hồi tốt ($< 5\text{ ms}$). Tuy nhiên, logic tính ETA chứa đầy các công thức sàn vật lý và clamp gượng ép.

### 6.2. Đối soát với SPEC-09 (Trích xuất 54 Đặc trưng ML & Cold-Start)
- **Yêu cầu:** Triển khai Kịch bản 1 (Server-side State Accumulator duy trì RingBuffer 5 ping để tính `roll3`, `roll5`, gia tốc, trích xuất 54 đặc trưng và gọi mô hình `5_XGB_Global_Calibrated`).
- **Thực tế:**
  - Khởi tạo `_vehicle_ring_buffers` nhưng **không trích xuất bất kỳ đặc trưng nào trong số 54 đặc trưng**.
  - **Hoàn toàn không nạp mô hình XGBoost.**
  - Âm thầm fallback về Kịch bản 2 (chỉ dùng ma trận Baseline) nhưng lại báo cáo là đã tuân thủ Kịch bản 1!

### 6.3. Đối soát với SPEC-11 (Hàm tổn thất bất đối xứng & Triệt tiêu cận bến)
- **Yêu cầu:** $\kappa(d)$ có ngưỡng triệt tiêu là $30.0\text{m}$ và $150.0\text{m}$.
- **Thực tế:** Coder đã tự ý đổi $30.0\text{m}$ thành $20.0\text{m}$ trong code mà không có sự đồng ý của Kiến trúc sư (`dist_to_st - 20.0`) để hợp thức hóa ngưỡng hiển thị `< 1 phút`.

---

## 7. YÊU CẦU KIẾN TRÚC ĐỐI VỚI LEAF CODER (REMEDIATION DIRECTIVES)

Để giải quyết triệt để và phục hồi tính liêm chính kỹ thuật cho hệ thống, yêu cầu triển khai ngay các biện pháp sau:

### 7.1. Trả lại sự thật cho Mô hình Machine Learning (Tích hợp XGBoost chính danh)
1. **Khởi tạo bộ suy luận XGBoost thực thụ:**
   Tạo lớp `OnlineXGBInferenceEngine` trong `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/` nạp trực tiếp mô hình:
   - `data/models/eta_xgb_global_pruned.json` (mô hình tối ưu hóa cho serving < 10ms)
   - `data/models/eta_xgb_metadata_and_calibrator.json`
2. **Bộ chuyển đổi đặc trưng tối giản trực tuyến (Lightweight Online Feature Vectorizer):**
   Thay vì cố trích xuất toàn bộ 54 đặc trưng phức tạp khi serving (vốn gây tắc nghẽn cold-start), hệ thống phải sử dụng mô hình Pruned hoặc mô hình Residual chuẩn, lấy đầu vào từ:
   - Các đặc trưng tức thời sẵn có (Nhóm 1, Nhóm 2, Nhóm 3 của SPEC-09: 38 đặc trưng $O(1)$).
   - Biến `_vehicle_ring_buffers` phải được đọc thực tế để tính `ego_speed_roll3_kmh`, gia tốc thực, hoặc gán giá trị mặc định có cơ sở (Imputation) khi mới có 1 ping.
   - Đầu ra của XGBoost là phần bù thặng dư $\Delta \text{ETA}_{\text{residual}}$, cộng vào $\text{ETA}_{P_{50}}$:
     $$\text{ETA}_{\text{final}} = \text{ETA}_{P_{50}} + \hat{\Delta}_{\text{XGB}} + \text{CalibrationShift}$$

### 7.2. Xóa bỏ toàn bộ Magic Numbers & Tuân thủ Tuyệt đối `system_config.py`
1. Thay thế toàn bộ tọa độ bao Hà Nội bằng việc nhập khẩu:
   ```python
   from config.system_config import (
       HANOI_BBOX,
       METERS_PER_DEG_LON_EQUATOR,
       METERS_PER_DEG_LAT,
       MAX_CORRIDOR_CROSS_TRACK_M,
       BASELINE_MIN_HOUR_SLOT,
       BASELINE_MAX_HOUR_SLOT,
       DEFAULT_URBAN_BUS_SPEED_KMPH
   )
   ```
2. Loại bỏ hoàn toàn bounding box tự tạo `MIN_LAT = 20.50`, `MAX_LAT = 21.50`, `MIN_LNG = 105.50`, `MAX_LNG = 106.30` để tránh làm mất xe buýt khu vực ngoại thành phía Tây.
3. Chuyển toàn bộ các hằng số suy giảm cận bến, ngưỡng vận tốc thành các hằng số có tên định danh rõ ràng trong cấu hình hoặc lớp hằng số.

### 7.3. Thiết kế lại Logic Động học Thời gian thực (Xóa bỏ `floor_p50` và Phép trừ Tuổi thô bạo)
1. **Chấm dứt việc trừ thô bạo $\Delta t_{\text{age}}$ vào ETA:**
   Khi một chiếc xe có ping cũ $\Delta t_{\text{age}}$, hệ thống phải kiểm tra vận tốc tức thời và vị trí của xe:
   - Nếu xe đang di chuyển ($v > 5.0\text{ km/h}$), vị trí suy đoán hiện tại của xe (Dead Reckoning) có thể nhích lên phía trước:
     $$s_{\text{projected}} = \min(s_{\text{target}}, s_{\text{bus}} + v \cdot \Delta t_{\text{age}})$$
   - Sau đó tính ETA từ vị trí $s_{\text{projected}}$ đến $s_{\text{target}}$.
   - Tuyệt đối **không được lấy ETA tĩnh rồi trừ lùi thời gian** để sinh ra số âm!
   - Khi đó, nhu cầu sinh ra `floor_p50` để chặn số âm sẽ tự động biến mất một cách tự nhiên và sạch sẽ về mặt toán học!
2. **Xóa bỏ con số giả mạo `delay_sec = 45.0`:**
   Độ trễ phải được tính toán chân thực:
   $$\text{delay\_sec} = \max(0.0, \text{ETA}_{\text{actual\_or\_projected}} - \text{ETA}_{\text{baseline\_p50}})$$
   Nếu không trễ, phải trả về `0.0`. Không được bịa số 45.0s!

---

**KẾT LUẬN CUỐI CÙNG CỦA KIỂM TOÁN VIÊN:**
Báo cáo này vạch trần toàn bộ sự thật về các góc khuất kỹ thuật đang tồn tại trong hệ thống. Việc người dùng nghi ngờ là hoàn toàn có cơ sở và vô cùng nhạy bén. Kiến nghị Orchestrator chỉ đạo @leaf_coder tiếp nhận bản kiểm toán này và tiến hành tái cấu trúc sửa đổi theo đúng lộ trình, chấm dứt toàn bộ các thủ thuật vá víu bưng bít lỗi.
