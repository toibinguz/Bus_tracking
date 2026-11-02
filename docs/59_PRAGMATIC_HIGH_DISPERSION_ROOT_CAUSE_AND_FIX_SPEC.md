# ĐẶC TẢ KỸ THUẬT THỰC DỤNG: PHÂN TÍCH GỐC RỄ VÀ XỬ LÝ CÁC Ô MA TRẬN CÓ ĐỘ PHÂN TÁN CAO (8 – 21 PHÚT)
> **Tài liệu**: `docs/59_PRAGMATIC_HIGH_DISPERSION_ROOT_CAUSE_AND_FIX_SPEC.md`  
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Cơ sở dữ liệu kiểm định**: `data/hanoi_bus_system.db` (`agg_segment_travel_times`: 95,094 ô)  
> **Ngày lập**: 01/11/2026  
> **Trạng thái**: Đã phê duyệt, triển khai và kiểm chứng thực nghiệm (Implemented & Verified)

---

## I. CHẨN ĐOÁN THỰC NGHIỆM: VÌ SAO VẪN CÒN CÁC Ô CÓ ĐỘ PHÂN TÁN 8 – 21 PHÚT?

Kiểm tra trực tiếp trên 95,094 ô của bảng `agg_segment_travel_times` trong `data/hanoi_bus_system.db` cho thấy:
- `max(std_transit_sec)` hiện tại là **489.07s (~8.2 phút)** (trước bản vá tạm của Flash 3.8 là **748.93s = 12.5 phút**), với **37 ô có `std >= 300s` (5 phút)** và **93 ô có `std >= 240s` (4 phút)**.
- `max(p90_transit_sec - p10_transit_sec)` (cột **Độ Tản** hiển thị trên bảng UI) lên tới **1,274.84s (~21.2 phút)**, với **199 ô có `P90 - P10 >= 600s` (10 – 21 phút)**.
- Có tới **2,729 ô** bị bất nhất toán học: `P90 - Median > 4.0 * Std` (ví dụ `std = 13.1s` nhưng `P90 - P10 = 625.0s = 10.4 phút`).

Truy vết ngược từng ping GPS trong `route_projected_telemetry` và `vehicle_unique_pings` bộc lộ **4 lỗi kỹ thuật thực tế trong code hiện tại** (không phải những lý thuyết viển vông trong bản nháp của Flash 3.8):

---

### Lỗi 1: Bỏ lọt xe đỗ nghỉ/điều tiết giữa chặng (Mid-Segment Layover & Telemetry Pause) trong `baseline_segment_average.py`
- **Vị trí code**: `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_segment_average.py` (dòng 203 & 215–234).
- **Bằng chứng thực nghiệm (Dòng Top 1 `std` toàn bảng — Tuyến `123 [re]` đoạn `19 -> 20`: Thị Nguyên $\to$ Canh Hoạch, dài 3,427.2m, khung `EARLY_MORNING` 05:00–06:30)**:
  - Trong DB hiện tại: $N = 21$, `median = 1,158.94s` (**19.3 phút** lúc 5h30 sáng ở ngoại thành!), `std = 489.07s` (**8.2 phút**), `P90 - P10 = 1,073.9s` (**17.9 phút**).
  - Bóc tách 21 chuyến xe của ô này từ `route_projected_telemetry`:
    - Các chuyến chạy liên tục (`vid=1408842` ngày 14/10, 16/10, 22/10; `vid=8831707` ngày 22/10, 26/10) chỉ mất **371.9s – 451.1s (~6.5 – 7.5 phút, vận tốc 28 – 33 km/h)**.
    - Ngược lại, 11 chuyến khác (`vid=1408838` ngày 13–16/10, `vid=1408842` ngày 13/10, 15/10, 19/10, 27/10, `vid=8831707` ngày 19/10, 21/10, 27/10) khi đi đến tọa độ `s ≈ 21,697m – 21,848m` (điểm dừng chờ điều tiết trước đình Canh Hoạch) đã **đỗ đứng im một chỗ suốt 13 đến 18 phút** ($\Delta s = 0.0\text{m}$ qua 10 – 14 pings liên tiếp từ `06:00:50` đến `06:17:21`), sau đó mới chạy tiếp qua trạm 20 (`21,980.4m`) làm $\Delta T$ vọt lên **1,367s – 1,724s (23 – 29 phút)**!
- **Nguyên nhân trong code**:
  1. Điều kiện cắt chuyến `p[0] - curr_trip[-1][0] > 600.0` chỉ bắt được trường hợp **tắt máy mất sóng GPS > 10 phút**. Khi xe đỗ chờ nhưng thiết bị GPS vẫn thức và bắn ping đều đặn mỗi 90 giây ($\Delta t_{\text{step}} \approx 90\text{s} < 600\text{s}$), chuyến xe không bao giờ bị cắt!
  2. Hàm tìm mốc vượt trạm `crossings[k]` và `crossings[k+1]` chỉ kiểm tra `tB - tA <= 180.0` tại **2 cặp ping cắt qua vạch trạm**, hoàn toàn **không kiểm tra các ping nằm giữa trạm $k$ và trạm $k+1$** (bỏ lọt cả xe đỗ đứng im 15 phút lẫn các khoảng mất sóng GPS 4–9 phút giữa 2 trạm).
  3. Khi 50% số chuyến trong khung giờ 5h30 sáng có đỗ chờ điều tiết, trung vị của phân phối bị kéo lệch và `MAD` phình to lên ~400s, khiến bộ lọc `3.5 * MAD` mất tác dụng hoàn toàn.

---

### Lỗi 2: Gom chung ngày và đêm trong Tier 1 Fallback (All-Day Bimodal Pooling) trong `baseline_segment_average.py`
- **Vị trí code**: `baseline_segment_average.py` (dòng 307–332).
- **Bằng chứng thực nghiệm**:
  - Trong **Top 17 dòng có `std` cao nhất toàn bảng**, có tới **13 dòng là ô nội suy `Tier 1` (`is_interpolated = 1`) vào ngày Thứ Bảy (`SATURDAY`)**:
    - `E03 [re] 31->32` (`SATURDAY`, `PRE_EVENING_PEAK` / `EVENING_PEAK_CORE` / `MORNING_SURGE`): `std = 474.40s` (**7.9 phút**), `P90 - P10 = 1,274.84s` (**21.2 phút**).
    - `E04 [re] 37->38` (`SATURDAY`): `std = 460.50s` (**7.7 phút**), `P90 - P10 = 1,187.90s` (**19.8 phút**).
    - `51 [go] 32->33` (`SATURDAY`): `std = 453.12s` (**7.6 phút**), `P90 - P10 = 1,132.47s` (**18.9 phút**).
    - `40 [re] 13->14` (`SATURDAY`): `std = 436.90s` (**7.3 phút**), `P90 - P10 = 1,141.41s` (**19.0 phút**).
    - `64 [re] 11->12`, `07 [re] 8->9`, `61 [go] 13->14`, `109 [re] 11->12` (`SATURDAY`): `std = 366.8s – 372.4s` (**6.2 phút**), `P90 - P10 = 938.7s – 1,018.6s` (**16 – 17 phút**).
- **Nguyên nhân trong code**:
  - Khi một khung giờ của ngày Thứ Bảy có $N < 3$ mẫu, code hiện tại lấy `all_day_samples[(k, dtype)]` — tức là **trộn lẫn toàn bộ các chuyến lúc 05h30 sáng / 21h30 đêm (qua cầu Vĩnh Tuy mất 356s – 418s ở tốc độ 45–50 km/h) với các chuyến cao điểm ban ngày (mất 1,400s – 1,750s ở tốc độ 10–12 km/h)** rồi tính `stdev(all_day_samples)` và `P90 - P10`!
  - Kết quả là `std` và `P90 - P10` của ô Tier 1 đo **sự chênh lệch giữa 5h sáng và 18h tối**, tạo ra con số ảo 8 phút `std` và 21 phút `spread`.

---

### Lỗi 3: Lọc ngoại lai MAD chỉ áp dụng cho `mean/std` mà bỏ quên `P10/P90` và `median`
- **Vị trí code**: `baseline_segment_average.py` (dòng 281–296).
- **Bằng chứng thực nghiệm**:
  ```python
  med_t = statistics.median(samples)
  sorted_s = sorted(samples)
  p10_t = continuous_percentile(sorted_s, 0.10)
  p90_t = continuous_percentile(sorted_s, 0.90)
  # Bộ lọc MAD đặt ở dưới, chỉ tính cho mean_t và raw_std!
  clean_samples = [x for x in samples if abs(x - med_t) <= threshold]
  ```
- **Hậu quả**: Ở **2,729 ô** (như `11 [re] 17->18`, `E11 [go] 1->2`, `123 [re] 20->21`), các mẫu lỗi (xe đỗ 15 phút) đã bị loại khỏi `clean_samples` nên `std = 13s – 82s`, nhưng `p90_t` vẫn lấy từ `sorted_s` chưa lọc nên vọt lên **700s – 1,300s**, làm `P90 - P10` bị đội lên **10 – 19 phút**!

---

### Lỗi 4: Ghi đè `st_dir` tại 457 trạm dùng chung 2 chiều & gán sai `p_dir == 0` trong `parallel_multi_route_projector.py`
- **Vị trí code**: `scripts/parallel_multi_route_projector.py` (dòng 108–111 và 242).
- **Bằng chứng thực nghiệm**:
  - Trong `canonical_station_master`, có **457 cặp `(route_id, station_id)` xuất hiện ở cả hai chiều `go` và `re`** (toàn bộ các bến đầu cuối như `6179`, `6178` của Tuyến 123, `1670` BX Gia Lâm, `1750` BX Yên Nghĩa...).
  - Dòng 242: `st_dir = {(r_id, st_id): d for r_id, st_id, d in cur.fetchall()}` khiến chiều `'re'` ghi đè mất chiều `'go'` của toàn bộ 457 trạm này.
  - Đồng thời tại dòng 111: `d_str = "go" if p_dir == -1 else "re"` gán nhầm các ping có `p_dir == 0` (trong `vehicle_unique_pings` có 2,228,496 pings mang `direction = 0` là chiều đi!) sang chiều về `"re"`.

---

### Bản chất vật lý của các đoạn còn lại có `std ≈ 250s – 350s` (4 – 6 phút):
Sau khi loại bỏ 4 lỗi kỹ thuật trên, các phân đoạn duy nhất còn có độ lệch chuẩn thực tế quanh mức 4 – 6 phút đều là **các phân đoạn vượt cầu lớn dài 3 – 5.8 km không có trạm dừng giữa cầu** vào đúng khung giờ giao thoa cao điểm (`MORNING_SURGE` 06:30–07:45 hoặc `EVENING_PEAK_CORE` 17:30–18:45):
1. **Cầu Vĩnh Tuy** (`E01 [re] 23->24`, `E03 [re] 31->32`, `E04 [re] 37->38`, `40 [re] 13->14`, `51 [go] 32->33` — dài **4.95 km đến 5.82 km**).
2. **Cầu Chương Dương** (`43 [go] 18->19`, `22A [re] 3->4`, `E02 [go] 26->27`, `48 [go] 17->18` — dài **2.12 km đến 2.94 km**).
3. **Cầu Thăng Long** (`61 [re] 36->37`, `61 [go] 13->14` — dài **4.85 km đến 5.18 km**).

Tại các đoạn dài 5 km này, đầu khung giờ `06:30` xe đi mất ~7 phút, cuối khung giờ `07:40` cầu ùn tắc xe đi mất ~18–22 phút. Đây là biến thiên giao thông vật lý có thật trên đoạn đường dài 5 km, nhưng có thể kiểm soát gọn gàng bằng cách chuẩn hóa khung giờ cao điểm sáng (`07:00 – 09:00` thay vì để `MORNING_SURGE` kéo dài tới `07:45`) và giới hạn trần hệ số biến thiên (`CV = std / median`).

---

## II. THIẾT KẾ GIẢI PHÁP SỬA LỖI THỰC DỤNG (PRAGMATIC FIX)

Chúng ta không làm phức tạp hóa hệ thống, chỉ sửa trực diện và gọn sạch tại 2 file:

### 1. Sửa `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_segment_average.py`
1. **Lọc hành trình đỗ nghỉ giữa chặng & đứt quãng GPS (`_is_valid_segment_traversal`)**:
   - Trong quá trình chia trip: theo dõi thêm `max_s` của chuyến; nếu xe lùi ngược `s < max_s - 300.0` (xe quay đầu ở bến phụ) thì ngắt chuyến ngay.
   - Khi xét cặp vượt trạm $k$ (tại ping $i_1$) và $k+1$ (tại ping $i_2$):
     - Loại bỏ nếu có khoảng trống mất sóng GPS giữa chặng $t_{j+1} - t_j > 300\text{s}$.
     - Loại bỏ nếu phát hiện **xe đỗ đứng im/chờ điều tiết giữa chặng**: tồn tại khoảng thời gian $\Delta t \ge 300\text{s}$ (5 phút) bên trong đoạn $[i_1, i_2+1]$ mà xe dịch chuyển chưa tới $\Delta s < 40\text{m}$ (như Tuyến 123 đỗ 17 phút ở Canh Hoạch).
2. **Tinh chỉnh ranh giới khung giờ giao thoa sáng/tối sát thực tế Hà Nội**:
   - `MORNING_SURGE`: `06:30 – 07:00` (giao thoa sớm), `MORNING_PEAK`: `07:00 – 09:00` (tránh trộn lẫn xe chạy thoáng lúc 06:30 với xe kẹt cứng lúc 07:40 trên cầu Chương Dương / Vĩnh Tuy).
   - Tách `EVENING_DISSIPATION` (`18:45 – 20:15`) khỏi đêm muộn (`20:15 – 22:30`) hoặc lọc sạch các mẫu ùn tắc còn sót ở đầu khung đêm bằng MAD.
3. **Đồng bộ hóa 100% các chỉ số thống kê trên `clean_samples`**:
   - Lọc ngoại lai bằng MAD (`threshold = max(3.0 * mad, 45.0)`) **TRƯỚC**, sau đó tính **cả 5 chỉ số (`median`, `mean`, `std`, `p10`, `p90`) trên cùng tập `clean_samples`**. Triệt tiêu hoàn toàn 2,729 ô có `P90` bất nhất với `std`.
4. **Sửa Tier 1 Fallback (Không trộn 5h sáng với 18h tối)**:
   - Khi ô `(k, win, dtype)` có $N < 3$: ưu tiên mượn mẫu từ **cùng khung giờ `win` của ngày thường (`WEEKDAY`) hoặc 2 khung giờ liền kề** (`same_regime_samples`) thay vì lấy `all_day_samples` trộn lẫn ngày-đêm.

### 2. Sửa `scripts/parallel_multi_route_projector.py`
- Loại bỏ 457 cặp `(route_id, station_id)` dùng chung 2 chiều khỏi từ điển ép hướng cứng `st_dir` (chỉ giữ các `station_id` đặc trưng riêng cho 1 chiều).
- Sửa điều kiện fallback hướng từ `d_str = "go" if p_dir == -1 else "re"` thành `d_str = "go" if p_dir in (0, -1) else "re"`.

---

## III. KẾT QUẢ THỰC THI VÀ KIỂM CHỨNG ĐỘC LẬP TRÊN `data/hanoi_bus_system.db`

Sau khi triển khai các bản vá tại `scripts/parallel_multi_route_projector.py` và `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_segment_average.py`, chạy lại toàn bộ 96 tuyến-chiều (95,094 ô trong 45 giây với 6 workers), kết quả kiểm chứng thực nghiệm trên bảng `agg_segment_travel_times` như sau:

### 1. Bảng đối chiếu tổng thể Trước vs. Sau khi sửa (95,094 ô)

| Chỉ số kiểm định trên `agg_segment_travel_times` | Trước khi sửa | Sau khi sửa | Đánh giá kỹ thuật |
| :--- | :---: | :---: | :--- |
| **Tổng số ô ma trận (`COUNT(*)`)** | 95,094 | **95,094** | Bảo toàn 100% độ phủ không gian - thời gian |
| **`MAX(std_transit_sec)` toàn bảng** | 489.07s (~8.2 phút) *(trước đó 748.93s)* | **402.04s (~6.7 phút)** | Giảm toàn bộ đỉnh nhiễu giả tạo |
| **Số ô có `std >= 480s` (8 phút)** | 1 | **0** | Triệt tiêu hoàn toàn |
| **Số ô có `std >= 360s` (6 phút)** | 18 | **5** | Chỉ còn 5 đoạn vượt cầu Chương Dương / Vĩnh Tuy giờ cao điểm |
| **Số ô có `std >= 300s` (5 phút)** | 37 | **25** | 100% là ô `Tier 0` vượt cầu lớn dài 2.1 – 5.2 km giờ cao điểm |
| **`MAX(P90 - P10)` (Độ tản tối đa)** | 1,274.84s (~21.2 phút) | **1,109.45s (~18.5 phút)** | Loại bỏ hoàn toàn hiện tượng trộn mẫu 5h sáng với 18h tối |
| **Số ô có `P90 - P10 >= 1200s` (20 phút)** | 3 | **0** | Triệt tiêu hoàn toàn |
| **Số ô có `P90 - P10 >= 900s` (15 phút)** | 32 | **7** | Giảm 78.1% |
| **Số ô có `P90 - P10 >= 600s` (10 phút)** | 199 | **57** | Giảm 71.4% |
| **Số ô bất nhất `P90 - Median > 4 * Std`** | 2,729 | **1** | Giảm 99.96% nhờ đồng bộ `clean_samples` |
| **Số ô vi phạm `P10 <= Median <= P90`** | 0 | **0** | Chuẩn xác toán học 100% |

### 2. Kiểm chứng các trường hợp điển hình đã được khắc phục
1. **Tuyến `123 [re]` đoạn `19 -> 20` (`Thị Nguyên -> Canh Hoạch`, dài 3,427.2m)**:
   - **Trước khi sửa**: Top 1 toàn bảng với `WEEKDAY EARLY_MORNING` có `median = 1,158.94s (19.3 phút)`, `std = 489.07s (8.2 phút)`, `P90 - P10 = 1,073.90s (17.9 phút)` do xe đỗ chờ điều tiết 13–18 phút trước đình Canh Hoạch.
   - **Sau khi sửa**: `WEEKDAY EARLY_MORNING` ($N = 10$) giảm về đúng thời gian di chuyển thực tế **`median = 436.77s (7.3 phút)`, `std = 67.24s (1.1 phút)`, `P90 - P10 = 114.68s (1.9 phút)`**. Trên cả 27 ô của đoạn này, `std` chỉ còn từ **42.67s đến 130.09s (0.7 – 2.2 phút)**.
2. **13 ô `Tier 1 SATURDAY` bị trộn ngày-đêm (`E03`, `E04`, `51`, `40`, `64`, `07`, `61`, `109`)**:
   - **Trước khi sửa**: `std = 366.8s – 474.4s (6.1 – 7.9 phút)`, `P90 - P10 = 938.7s – 1,274.8s (15.6 – 21.2 phút)` do lấy `all_day_samples` trộn lẫn 5h sáng với 18h tối.
   - **Sau khi sửa**: **0 ô nội suy (`tier = 1`)** nào còn xuất hiện trong Top 25 `std` cao nhất toàn bảng.
3. **Bản chất của Top 12 ô có `std` cao nhất hiện tại (`326s – 402s` = `5.4 – 6.7 phút`)**:
   - Tất cả 12/12 ô đều là dữ liệu thực tế **`Tier 0` ($N = 19 \dots 67$ chuyến)** tại 3 cây cầu lớn vượt sông Hồng không có trạm dừng giữa cầu vào đúng khung giờ cao điểm:
     - **Cầu Vĩnh Tuy (`4,953m – 5,020m`)**: `E04 [re] 37->38`, `E01 [re] 23->24`, `E03 [re] 31->32` (`WEEKDAY EVENING_PEAK_CORE`, `std = 338.9s – 402.0s`).
     - **Cầu Chương Dương (`2,122m – 2,938m`)**: `48 [go] 17->18`, `146 [go] 17->18`, `43 [go] 18->19`, `22A [re] 3->4`, `17 [go] 39->40`, `01 [re] 3->4`, `34 [go] 3->4` (`WEEKDAY MORNING_PEAK`, `std = 330.5s – 395.9s`).
     - **Cầu Thăng Long (`5,177m`)**: `61 [re] 36->37` (`std = 326.4s`).
   - Đây là biến thiên ùn tắc vật lý thực sự khi vượt cầu dài 2.2 – 5.2 km vào giờ cao điểm Hà Nội, phản ánh trung thực rủi ro trễ chuyến cho tầng dự báo ETA (P90).


