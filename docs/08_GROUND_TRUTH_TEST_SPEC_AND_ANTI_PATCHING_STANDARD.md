# ĐẶC TẢ KIỂM TOÁN NỢ KỸ THUẬT, THỨ TỰ ƯU TIÊN & THIẾT KẾ BỘ KIỂM THỬ CHÂN LÝ CHUẨN (GROUND TRUTH TEST SPEC)
> **Mã tài liệu**: `docs/08_GROUND_TRUTH_TEST_SPEC_AND_ANTI_PATCHING_STANDARD.md`  
> **Căn cứ pháp lý**: Tuân thủ vô điều kiện **Điều 1** (Kỷ luật Thực nghiệm), **Điều 2** (Thiết kế trước, duyệt rồi mới triển khai), **Điều 4** (Nguồn chân lý dữ liệu tối thượng), **Điều 5** (Động học dẫn xuất), **Điều 7** (Runtime chuẩn Python 3.14), và **Điều 8** (Nghiệm thu trung thực & Minh bạch nợ kỹ thuật) theo [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md).  
> **Mục tiêu**: (1) Ghi lại thiết kế giải thuật Nội suy ETA vi mô giữa 2 trạm (TD-52); (2) Phân cấp ưu tiên toàn bộ các Tech Debt còn tồn đọng; (3) Xây dựng bộ test case dựa trên Nguồn Chân Lý Chuẩn (Ground Truth Oracle) trước khi viết mã nguồn can thiệp hệ thống.

---

## I. GHI NHẬN THIẾT KẾ KỸ THUẬT MỚI: TD-52 (NỘI SUY ETA VI MÔ TRONG PHÂN ĐOẠN)
> *Ghi nhận theo chỉ thị của người dùng: "Model ETA hiện tại chỉ ước lượng trên 2 trạm liên tiếp với các xe gần tuyến ta có thể ước lượng nội suy dựa trên dữ liệu timbus và kết quả ước lượng ETA để cho kết quả mượt mà nhất. Nhưng để sau, ghi lại".*

### 1.1. Bối Cảnh & Hạn Chế Hiện Tại của Mô Hình
* Hiện tại, mô hình ETA (kết hợp Baseline Matrix và XGBoost Residual) tính toán thời gian chạy vĩ mô theo từng phân đoạn giữa các trạm dừng liên tiếp ($k \to k+1 \to \dots \to m$).
* Khi xe buýt đang di chuyển trong lòng phân đoạn giữa 2 trạm kế cận ($s_{\text{bus}} \in [s_k, s_{k+1}]$), ETA dự báo đến trạm $k+1$ và các trạm sau chỉ được cập nhật mỗi khi có bản tin GPS mới từ BusMap ($30\text{s} - 75\text{s}$). Điều này khiến số phút/giây dự báo có bước nhảy bậc thang (stepped update), chưa đạt độ mượt liên tục theo từng giây.

### 1.2. Kiến Trúc Hợp Nhất Vĩ Mô - Vi Mô (Macro-Micro ETA Fusion Architecture)
Để giải quyết bài toán hiển thị mượt mà mà **hoàn toàn KHÔNG phá vỡ mô hình ML và Ma trận Baseline đã đóng băng**, kiến trúc đề xuất phân tách bài toán thành 2 tầng độc lập:

```
+---------------------------------------------------------------------------------------------------+
|               MÔ HÌNH HỢP NHẤT DỰ BÁO ETA VĨ MÔ - VI MÔ (TD-52 ARCHITECTURE)                      |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [ VỊ TRÍ XE BUÝT HIỆN TẠI ]                                                                      |
|        │                                                                                          |
|        ├──> 1. TẦNG VI MÔ (Micro-ETA Decay via TimBus 5.0s):                                      |
|        │    • Chiếu tọa độ TimBus (Lat_T, Lon_T) lên tim đường BusMap Canonical -> s_bus_m.       |
|        │    • Tính khoảng cách còn lại tới trạm kế cận:                                            |
|        │          Δs_remain = s_{k+1} - s_bus_m                                                   |
|        │    • Vận tốc dẫn xuất thực địa:                                                          |
|        │          v_eff = max(v_min, (0.7 * v_timbus + 0.3 * v_baseline))                        |
|        │    • Thời gian vi mô tiếp cận trạm kế cận:                                               |
|        │          τ_micro = Δs_remain / v_eff                                                     |
|        │                                                                                          |
|        └──> 2. TẦNG VĨ MÔ (Macro-ETA via Frozen Baseline & ML XGBoost):                           |
|             • Tính thời gian chạy từ trạm kế cận k+1 đến trạm đích m:                             |
|                   ETA_macro(k+1 -> m) = Baseline_P50(k+1 -> m) + Δ_XGB(k+1 -> m)                  |
|                                                                                                   |
|  ───────────────────────────────────────────────────────────────────────────────────────────────  |
|  [ KẾT QUẢ HỢP NHẤT ĐẾM LÙI MƯỢT 1 GIÂY (Seamless Blended ETA) ]:                                |
|        • ETA_final(m) = τ_micro + ETA_macro(k+1 -> m)                                             |
|        • Cửa sổ an toàn: [P10_final, P90_final] dịch chuyển tịnh tiến theo τ_micro!                |
+---------------------------------------------------------------------------------------------------+
```

### 1.3. Lợi Ích Cốt Lõi
1. **Bảo tồn 100% tính toàn vẹn của Model**: Mô hình XGBoost và Ma trận Baseline giữ nguyên, không bị Train/Serve Skew do nhịp lấy mẫu khác nhau.
2. **Đếm lùi mượt mà liên tục**: Khi xe nhích từng mét trên đường (qua nhịp TimBus 5s hoặc Tweening Frontend 1s), $\Delta s_{\text{remain}}$ giảm dần làm $\tau_{\text{micro}}$ đếm lùi từng giây tự nhiên, tạo trải nghiệm ứng dụng đẳng cấp.
3. **Kế hoạch thực thi**: Lưu trữ vào Sổ cái Nợ kỹ thuật, triển khai ở pha Serving Nâng cao (Serving Phase 2) sau khi hoàn thiện cơ chế Fallback State Machine.

---

## II. MA TRẬN PHÂN LOẠI & THỨ TỰ ƯU TIÊN CỦA TOÀN BỘ CÁC NỢ KỸ THUẬT

Sau khi rà soát toàn diện `docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`, các vấn đề còn mở (`[ ]`) được phân loại thành 3 nhóm rõ rệt:

| Phân Nhóm | Mã Nợ | Nội Dung Kỹ Thuật | Mức Độ Ưu Tiên | Phương Án Xử Lý Chuẩn Mực |
| :--- | :--- | :--- | :---: | :--- |
| **Nhóm 1: Khuyết tật UX / Chức năng đã được khắc phục & nghiệm thu** | **`TD-30`** | UX thông báo ca đêm sau 22:30 và xe chờ tài tại bến trên Frontend SPA. | **ĐÃ HOÀN THÀNH [x]** | Đã triển khai FSM State Controller (`CORRIDOR_OPERATIONAL_STATE`, `CORRIDOR_UI_THEME`), Node.js kiểm chứng 100% PASS. |
| | **`TD-29`** | Bộ đệm In-Memory TTL Cache đơn tiến trình vs Redis. | **P1** | Đánh giá concurrency test; duy trì Thread-Safe Lock cho Web Demo hiện tại. |
| **Nhóm 2: Ranh giới Đóng băng & Quy tắc Quản trị (KHÔNG PHẢI BUG)** | **`TD-12`** | Bản vá hình học cho E11, E11CT, 123. | **Bảo lưu (Frozen)** | Bảng Master hiện tại đã sạch 100%; giữ nguyên ranh giới. |
| | **`TD-13`** | Lỗ thủng không gian Detour xe tránh tắc đường. | **Bảo lưu (Frozen)** | Quy tắc nối chuyến và kẹp trạm đã hoạt động ổn định. |
| | **`TD-14`** | 4 tuyến có đoạn chạy lệch tim đường tĩnh BusMap $>35\text{m}$. | **Bảo lưu (Frozen)** | Đã có Fallback Tier 3 (`route_avg_mps`), 0% lỗi trên tập Test. |
| | **`TD-15`** | Tuyến 67, 92 ngoài vùng phủ TomTom. | **Bảo lưu (Frozen)** | Đã dùng `COALESCE(0)` an toàn trong Feature Store. |
| | **`TD-16`** | Chu kỳ lấy mẫu lịch sử ~80s không tách micro-dwell time. | **Bảo lưu (Frozen)** | Thời gian vĩ mô qua đoạn trạm đã bao hàm cả thời gian dừng đỗ. |
| | **`TD-17`** | Trang trống Freelist Pages trong SQLite. | **Bảo lưu (P3)** | Chỉ thực hiện `VACUUM` ở bước đóng gói bàn giao cuối cùng. |
| | **`TD-27`** | Bất đối xứng API BusMap `vehicle_hn/get` vs `route_bus_gps`. | **Bảo lưu (Governance)** | Checklist kiểm soát định kỳ, không thay đổi crawler 24/7. |
| | **`TD-33`..`TD-40`** | Cụm phân kỳ danh bạ, mã trạm, rớt sóng và ranh giới TimBus. | **Bảo lưu (Strict Boundary)** | Tuân thủ vô điều kiện Điều 3 Hiến pháp: Đóng băng ranh giới Lakehouse, chỉ dùng TimBus làm Oracle độc lập và tiếp thu giải thuật Tweening. |
| **Nhóm 3: Nghiên cứu & Mở rộng Dài hạn** | **`TD-25`** | Route 90 Covariate Shift giữa Train và Test. | **P2** | Đã phân tích bản chất (mùa hè sang thu), mô hình vòng 2 đã kiểm soát sai số trong ngưỡng an toàn. |
| | **`TD-31`** | Mở rộng huấn luyện XGBoost cho các tuyến ngoài cụm HUST. | **P2** | Các tuyến ngoài HUST đang fallback về Baseline P50 an toàn. |
| | **`TD-32`** | Nâng nhịp cào Crawler BusMap lên 35-40s trên Cloud. | **ĐÃ HỦY BỎ (Wontfix)** | Bảo lưu nhịp cào 75s bảo vệ tuyệt đối ranh giới crawler 24/7 theo Điều 3.1. |
| | **`TD-52`** | Nội suy ETA vi mô giữa 2 trạm bằng TimBus (Macro-Micro Fusion). | **P2 (Ghi nhận để sau)** | Đưa vào kế hoạch nghiên cứu Serving Phase 2 theo chỉ thị người dùng. |

---

## III. NGUYÊN TẮC XÂY DỰNG TEST CASE THEO NGUỒN CHÂN LÝ CHUẨN (GROUND TRUTH ORACLE)

Để triệt tiêu hoàn toàn rủi ro **"sửa 1 lỗi sinh 2 lỗi"** và **"code sai, test cũng sai"**, mọi bài kiểm thử phải được neo chặt vào các nguồn chân lý bất biến:

```
+---------------------------------------------------------------------------------------------------+
|                        HỆ THỐNG NGUỒN CHÂN LÝ CHUẨN (GROUND TRUTH ORACLES)                        |
+---------------------------------------------------------------------------------------------------+
| 1. CHÂN LÝ HÌNH HỌC (Spatial Ground Truth):                                                       |
|    • CSDL SQLite: canonical_station_master (13.301 trạm) & canonical_shape_master (118.563 điểm). |
|    • Bất biến: s_station tăng đơn điệu; d_perp <= 35.0m trên tim đường chính tắc.                 |
|                                                                                                   |
| 2. CHÂN LÝ PHÂN PHỐI THỜI GIAN (Temporal Ground Truth):                                           |
|    • Bảng SQLite: agg_segment_travel_times (169.830 ô, 3 loại ngày x 17 khung giờ).               |
|    • Bất biến: P10 <= P50 <= P90 (Bắt buộc không có ngoại lệ số học).                             |
|                                                                                                   |
| 3. CHÂN LÝ QUY LUẬT VẬN HÀNH (Operational Ground Truth):                                          |
|    • Giờ xe buýt Hà Nội: Chuyến đầu 05:00, Chuyến cuối xuất bến 21:00 - 22:00, kết thúc 22:30.     |
|    • Ca đêm (22:30 - 05:00): Toàn mạng lưới ngừng chạy, 100% xe về bến đỗ an toàn.                |
|    • Giờ ban ngày (05:00 - 22:30) nếu không có xe trên đường: Trạng thái "Xe chờ tài tại bến".    |
|                                                                                                   |
| 4. CHÂN LÝ ĐỒNG HỒ BẤM GIỜ (Wall-Clock Temporal Logic):                                           |
|    • Đổi chuỗi giờ HH:MM sang số phút trong ngày (modulo 1440).                                   |
|    • Chống lỗi Midnight Wrap-around khi chuyến xe vượt qua mốc 00:00.                             |
+---------------------------------------------------------------------------------------------------+
```

---

## IV. NGUYÊN TẮC BÀI TRỪ VÁ LỖI THÔ THIỂN & TIÊU CHUẨN THIẾT KẾ THEO TÍNH CHẤT BẤT BIẾN
> *Chỉ thị tối cao từ người dùng: "Tránh các kĩ thuật vá lỗi thô thiển - dấu hiệu là số lượng if else dày vào tập trung 1 số case cụ thể thay vì tập trung tính chất, còn có là các magic number hard code vụn vặt."*

### 4.1. Nhận Diện & Nghiêm Cấm 4 Dấu Hiệu Vá Lỗi Thô Thiển (Anti-Patterns)
1. **Bắt case cục bộ bằng chuỗi `if-else` dày đặc (Ad-hoc Case Patching)**:
   - *Biểu hiện*: Viết các lệnh `if (route == "02")`, `if (plate == "29B-xxx")`, `if (station_id == 157)` để lách lỗi cho 1 xe hoặc 1 tuyến cụ thể mà bỏ qua tính tổng quát trên toàn mạng lưới 176 tuyến.
   - *Quy chuẩn*: **TUYỆT ĐỐI CẤM**. Mọi logic nghiệp vụ bắt buộc phải áp dụng thống nhất dựa trên **thuộc tính hình học** ($s, d_\perp$), **trạng thái vận hành FSM** (`ACTIVE_IN_TRANSIT`, `AT_ORIGIN_TERMINAL`, `AT_DESTINATION_TERMINAL`), và **hợp đồng kiểu dữ liệu** Pydantic v2.
2. **Magic Numbers và Hằng số Tự chế (Arbitrary Hardcoded Constants)**:
   - *Biểu hiện*: Nhét các con số tùy tiện vào code như `0.85 * eta - 60s`, `1.25 * eta + 90s`, `s > 15832.5`.
   - *Quy chuẩn*: **TUYỆT ĐỐI CẤM**. Mọi ngưỡng vật lý bắt buộc phải được khai báo tập trung trong `config/system_config.py` (như `CORRIDOR_MAX_DEVIATION_METERS = 35.0`), hoặc trích xuất từ dữ liệu phân phối thống kê CSDL ($P_{10}, P_{50}, P_{90}$).
3. **Chắp vá logic "Sửa 1 lỗi đẻ 2 lỗi" (Piecemeal Fixes)**:
   - *Biểu hiện*: Sửa một ngoại lệ biên bằng cách thêm một nhánh rẽ bất đối xứng, phá vỡ tính liên tục của pipeline.
   - *Quy chuẩn*: **BẮT BUỘC quy về Nguyên lý Đầu tiên (First-Principles Thinking)**. Khi phát hiện lỗi biên, phải xem xét toàn bộ không gian trạng thái của đối tượng để giải quyết triệt để tận gốc.
4. **Kiểm thử Hình thức / Test Tự Khớp Code Sai (Tautological Testing)**:
   - *Biểu hiện*: Viết test case sao chép y nguyên logic của code đang bị lỗi, khiến cả code lẫn test đều sai nhưng báo cáo vẫn "xanh" (giả tạo).
   - *Quy chuẩn*: **BẮT BUỘC dùng Nguồn Chân Lý Độc Lập (Ground Truth Oracle)**: Đối soát với CSDL SQLite gốc, công thức hình học Frenet thuần túy, và quy luật đồng hồ thời gian thực.

---

## V. THIẾT KẾ CHI TIẾT BỘ TEST MỚI: `scripts/test_ground_truth_and_night_mode.py`

Trước khi sửa đổi bất kỳ dòng code nào của Frontend/Backend liên quan đến `TD-30` và các kịch bản biên, bộ test kiểm chứng độc lập này phải được viết và chạy để xác nhận các điểm nghẽn hiện tại:

### Test Case 1: Kiểm Chứng Bất Biến Ca Đêm Của Backend REST API
* **Mục tiêu**: Xác thực endpoint `/api/v1/routes/{route_code}/live-eta` phản hồi chính xác trạng thái ca đêm khi giả lập thời điểm sau 22:30.
* **Nguồn chân lý**: Logic quy định vận hành giao thông công cộng Hà Nội ($T \ge 22:30 \lor T < 05:00$).
* **Tiêu chí kiểm định**:
  1. `traffic_condition` phải chứa tiền tố chuỗi `"Ca đêm"`.
  2. `active_in_transit_count == 0`.
  3. Mọi dự báo `predictions` (nếu có xe bến đỗ) phải được gắn cờ `AT_DESTINATION_TERMINAL` hoặc danh sách rỗng, không được trả về thời gian chờ ảo.

### Test Case 2: Kiểm Chứng Trạng Thái "Xe Chờ Xuất Bến" Ban Ngày
* **Mục tiêu**: Phân biệt rành mạch giữa "Ca đêm" và "Xe đang chờ tài tại bến vào ban ngày" ($05:00 \le T < 22:30$).
* **Nguồn chân lý**: Thời gian thực ban ngày khi danh sách xe active rỗng.
* **Tiêu chí kiểm định**:
  1. `traffic_condition` phải là `"Chưa có xe xuất bến trên hành lang (Xe đang chờ tài tại bến)"`.
  2. Tuyệt đối không được gán nhãn sai là "Thông thoáng" hoặc "Ca đêm".

### Test Case 3: Kiểm Chứng Tính Toàn Vẹn Của Ma Trận Phân Vị $P_{10} \le P_{50} \le P_{90}$
* **Mục tiêu**: Đảm bảo không có bất kỳ ô dữ liệu nào trong 169.830 ô bị vi phạm bất biến phân vị.
* **Nguồn chân lý**: Truy vấn SQL trực tiếp trên bảng `agg_segment_travel_times`:
  ```sql
  SELECT count(*) FROM agg_segment_travel_times 
  WHERE tt_p10_sec > tt_p50_sec OR tt_p50_sec > tt_p90_sec;
  ```
* **Tiêu chí kiểm định**: Số lượng bản ghi vi phạm phải bằng chính xác **`0`**.

### Test Case 4: Kiểm Chứng UX Frontend Không Bị Lỗi Logic Khi Ca Đêm
* **Mục tiêu**: Kiểm tra xem khi nhận được payload ca đêm, giao diện người dùng có hiển thị thông báo hướng dẫn giờ mở bến sáng hôm sau (05:00) hay không, thay vì để thẻ trống gây hiểu nhầm app bị lỗi.

---

## VI. KẾ HOẠCH HÀNH ĐỘNG TUẦN TỰ (DoD)

1. [x] **Bước 1**: Xây dựng văn bản đặc tả kiểm toán & thiết kế bộ test chân lý chuẩn `docs/13_TECH_DEBT_AUDIT_AND_GROUND_TRUTH_TEST_SPEC.md` (Tài liệu này).
2. [ ] **Bước 2**: Viết script test độc lập `scripts/test_ground_truth_and_night_mode.py` dựa trên 4 nguồn chân lý chuẩn. Chạy thử nghiệm để quan sát kết quả kiểm toán hiện trạng.
3. [ ] **Bước 3**: Triển khai giải pháp khắc phục triệt để cho `TD-30` trên Frontend SPA (`app.js`, `index.html`) theo đúng thiết kế đã phê duyệt.
4. [ ] **Bước 4**: Tái thực thi toàn bộ test suite:
   - `scripts/test_ground_truth_and_night_mode.py`
   - `scripts/test_anti_cheat_remediation.py`
   - `scripts/verify_web_app_demo.py`
   Đảm bảo 100% test case PASS (exit code 0), Zero Regression.
5. [ ] **Bước 5**: Cập nhật Sổ cái Nợ kỹ thuật `docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`, đánh dấu `[x] TD-30` và bổ sung `[ ] TD-52`.
