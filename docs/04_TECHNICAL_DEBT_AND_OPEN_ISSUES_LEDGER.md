# SỔ CÁI NỢ KỸ THUẬT & CHECKLIST QUẢN TRỊ RỦI RO TOÀN HỆ THỐNG
> **Mã tài liệu**: `docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md`  
> **Căn cứ pháp lý**: Tuân thủ vô điều kiện **Điều 1** (Kỷ luật Thực nghiệm), **Điều 4** (Master Ground Truth), **Điều 5** (Động học dẫn xuất), và **Điều 8** (Nghiệm thu Trung thực & Minh bạch Nợ kỹ thuật) của [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md).  
> **Ngày cập nhật**: 07/11/2026  
> **Trạng thái hệ thống**: **Module 1 & Module 2 ĐÃ ĐÓNG BĂNG (FROZEN)** (`5.336.214` dòng Silver sạch 100%, `1.191` phân vùng Parquet, `0` lỗi trên cả 4 kiểm định vật lý).

---

## I. DANH MỤC NỢ KỸ THUẬT ĐÃ XỬ LÝ TRIỆT ĐỂ (RESOLVED TECHNICAL DEBT — MODULE 1 & MODULE 2)

Bảng dưới đây ghi nhận các lỗi cấu trúc và nợ kỹ thuật từng đe dọa tính đúng đắn của dự án, nay đã được sửa chữa từng bước và nghiệm thu bằng thực nghiệm ([`experiments/verify_frenet_projection_step_by_step.py`](file:///z:/Desktop/Bus_tracking/experiments/verify_frenet_projection_step_by_step.py)):

| Mã Nợ | Mô Tả Nợ Kỹ Thuật Trước Đây | Giải Pháp Kỹ Thuật Đã Áp Dụng | Kết Quả Nghiệm Thu Thực Nghiệm (48 Tuyến) | Trạng Thái |
| :---: | :--- | :--- | :--- | :---: |
| **TD-R01** | **Hardcode 14 hằng số vật lý/hình học rải rác** (`45.0`, `35.0`, `20.0`, `-30.0`, `1500.0`, `300.0`, `80.0`, `2026-10-08`...) gây lệch chuẩn giữa các script. | Tập trung 100% hằng số vào [`config/system_config.py`](file:///z:/Desktop/Bus_tracking/config/system_config.py) và import thống nhất trên toàn bộ `module_1` và `module_2`. | `0` hằng số vật lý hardcode trong các module; đồng bộ ngưỡng `MAX_CORRIDOR_CROSS_TRACK_M = 35.0m` và `MAX_GPS_BACKWARD_JITTER_M = 20.0m`. | ✅ **ĐÃ XÓA SỔ** |
| **TD-R02** | **Cột tàn dư `is_dwell` trong SQLite & Views** từ thời kỳ thử nghiệm tách thời gian dừng đỗ vi mô ở chu kỳ 80s. | Xóa bỏ hoàn toàn cột `is_dwell` khỏi bảng `route_projected_telemetry`, `v_bus_to_next_station` và `v_active_fleet_summary` trong [`db_manager.py`](file:///z:/Desktop/Bus_tracking/module_2_big_data_storage_and_lakehouse/step_2_1_sqlite_operational_store/db_manager.py). | Schema bảng còn đúng **13 cột** (`CLEAN - no is_dwell`); 2 SQL Views truy vấn bình thường. | ✅ **ĐÃ XÓA SỔ** |
| **TD-R03** | **Lỗi `abs(ds)/dt` biến nhiễu giật lùi GPS tại chỗ ($-20\text{m} \le \Delta s < 0\text{m}$) thành vận tốc tiến dương** (`89.435` dòng bị gán sai vận tốc). | Thay bằng `v_mps = max(0.0, ds) / dt` trong [`multi_route_projector.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/multi_route_projector.py#L286). | `[Defect 2] ds<0 with speed>0 = 0` trên toàn bộ `5.336.214` bản ghi. | ✅ **ĐÃ XÓA SỔ** |
| **TD-R04** | **Lỗi tính `derived_speed_kmh` trước khi lọc hành lang $d_\perp \le 35,0\text{m}$** khiến `44.349` bản tin hợp lệ bị mất vận tốc (`NULL`) khi có 1 điểm ngoài hành lang xen giữa. | Lọc giữ các bản tin $d_\perp \le 35,0\text{m}$ trước, sau đó mới tính đạo hàm vận tốc trên chuỗi điểm Silver liên tiếp. | `[Defect 3] False NULL speed = 0` trên toàn bộ `5.336.214` bản ghi. | ✅ **ĐÃ XÓA SỔ** |
| **TD-R05** | **Lỗi `Global Search Fallback` không chặn lùi & gom nhóm `(vid, dir)` xuyên 28 ngày** gây ra `11.219` bước nhảy lùi giữa tuyến ($\Delta s < -20\text{m}$ trong $\Delta t \le 300\text{s}$). | Duyệt dòng thời gian thực của xe, gộp chùm nhiễu lật chiều ngắn hạn (`Direction Run Coalescing` trong $\Delta t \le 300\text{s}$), chỉ cập nhật `prev_s` khi $d_\perp \le 35\text{m}$, và khóa chặt bất biến đơn điệu `ds >= -20.0m` (trừ khi xe quay đầu hợp lệ tại hai đầu bến $s_{\text{prev}} \ge L - 800\text{m} \to s_{\text{new}} \le 800\text{m}$). | `[Defect 4] Mid-route backjump = 0` trên toàn bộ `5.336.214` bản ghi. | ✅ **ĐÃ XÓA SỔ** |
| **TD-R06** | **Chiếu trạm dừng bằng xấp xỉ Định lý Cosin** trong [`ingest_busmap_canonical.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py) thiếu ổn định số học trên đoạn ngắn. | Thay bằng phép chiếu tích vô hướng vector trực giao (Orthogonal Dot-Product) trên mặt phẳng tiếp diện cục bộ $(k_x, k_y)$, đồng nhất 100% với phép chiếu xe buýt và sự cố TomTom. | Đồng nhất toán học toàn cục giữa 3 bộ chiếu trong `module_1`. | ✅ **ĐÃ XÓA SỔ** |
| **TD-R07** | **Tàn dư 6 tuyến test 2 ngày đầu (`E07TC`, `35B`, `31`, `41`, `25`, `03A`), 48 mô hình XGBoost rời rạc & code Module 3 cũ** gây ô nhiễm ngữ cảnh. | Lưu trữ toàn bộ vào `archive/clean_slate_2026_11_07/`, xóa khỏi SQLite và Silver Parquet. | Chỉ giữ đúng **48 tuyến chuẩn cụm HUST** (`2026-10-08` $\to$ `2026-11-07`). | ✅ **ĐÃ XÓA SỔ** |

---

## II. CHECKLIST CÁC NỢ KỸ THUẬT & ĐẶC THÙ VẬT LÝ CÒN TỒN ĐỌNG (OPEN TECHNICAL DEBT CHECKLIST)

Đây là danh sách kiểm soát bắt buộc (Checklist) đối với các giới hạn vật lý của dữ liệu và các điểm đặc thù kỹ thuật còn tồn tại. Khi triển khai **Module 3 (Baseline Matrix, Feature Store, ML Training & Serving)**, mọi thuật toán bắt buộc phải đánh dấu kiểm tra (`[x]`) từng mục dưới đây:

### Nhóm A: Đặc Thù Dữ Liệu Nguồn & Hình Học Tầng Dưới (Module 1 & Module 2)

- [ ] **TD-O01: Ba bản vá hình học đặc thù cho dữ liệu gốc BusMap (`E11`, `E11CT`, `123`) & ngưỡng nâng bậc trạm `+15.0m`**
  * **Vị trí**: [`ingest_busmap_canonical.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py#L123-L239).
  * **Bản chất kỹ thuật**:
    1. Trong file gốc `hanoi_bus_routes.geojson` của BusMap, 2 tuyến vòng `E11` và `E11CT` bị đảo ngược nhãn chiều `Direction 0/1` giữa tim đường và danh sách trạm; tuyến `123` chiều đi bị nối chập cả lượt đi lẫn lượt về (dài 65km thay vì 23,7km).
    2. Dòng 123 áp dụng `best_s = max(min_s + 15.0, best_s)` để đảm bảo các trạm dừng liên tiếp luôn có lý trình tăng chặt ($s_k \ge s_{k-1} + 15\text{m}$), không tạo đoạn trạm có độ dài bằng 0.
  * **Mức độ rủi ro**: **Thấp** (Bảng `canonical_shape_master` và `canonical_station_master` đã được cố định và kiểm chứng 0 lỗi đơn điệu).
  * **Quy tắc kiểm soát**: Giữ nguyên bảng Master hiện tại; chỉ khi nào nạp lại bộ file GeoJSON mới từ BusMap mới cần kiểm tra lại 3 tuyến này.

- [ ] **TD-O02: Lỗ thủng không gian khi xe đi vòng / lên cầu vượt / hầm chui bị cắt bởi ngưỡng $d_\perp > 35,0\text{m}$**
  * **Vị trí**: Bảng `route_projected_telemetry` & [`trip_segmenter.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/trip_segmenter.py).
  * **Bản chất kỹ thuật**: Để giữ độ tinh khiết tuyệt đối của hành lang Silver ($d_\perp \le 35,0\text{m}$), các bản tin khi xe đi vòng tránh tắc đường (detour) hoặc đi trên nhánh cầu vượt/đường gom cách tim đường $> 35\text{m}$ bị cắt bỏ, tạo ra khoảng trống thời gian $300\text{s} < \Delta t \le 1800\text{s}$ (có **22.006 lần** trên 28 ngày).
  * **Quy tắc kiểm soát bắt buộc ở Module 3**:
    1. Luôn sử dụng hàm chuẩn [`segment_trajectory_into_trips`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/trip_segmenter.py#L64) để tự động nối chuyến qua lỗ thủng detour khi xe vẫn tiến về phía trước ($\Delta s > 100\text{m}, \bar{v} \in [2, 60]\text{ km/h}$).
    2. Khi tính thời gian chạy vi mô của **cặp trạm đơn lẻ liền kề $(k \to k+1)$** cho Baseline Matrix, **bỏ qua không nội suy** nếu trạm $k$ hoặc $k+1$ nằm lọt giữa khoảng trống detour ($\Delta t > 150\text{s}$ hoặc $\Delta s > 1.000\text{m}$).
    3. Khi tạo nhãn mục tiêu huấn luyện **ETA đa trạm ($s_{\text{bus}} \to s_{\text{target}}$)**, chỉ cần điểm đích $s_{\text{target}}$ được kẹp chặt bởi 2 bản tin liên tiếp ($\Delta t_{\text{target}} \le 150\text{s}$), tổng thời gian thực tế $\text{ETA}_{\text{actual}} = \hat{t}(s_{\text{target}}) - t_{\text{current}}$ hoàn toàn chính xác 100% bất chấp ở giữa hành trình có đoạn detour bị khuyết bản tin.

- [ ] **TD-O03: Trễ lật chiều ở bến xuất phát ($s \approx 0$) & Treo chiều cũ khi đỗ nghỉ ở bến cuối ($s \approx L$)**
  * **Vị trí**: Thiết bị GPS trên xe buýt & [`trip_segmenter.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_3_telemetry_kinematic_sanitizer/trip_segmenter.py#L32).
  * **Bản chất kỹ thuật**:
    1. **Tại bến cuối ($s \approx L$)**: Xe đã về đích và đỗ nghỉ 5–15 phút nhưng thiết bị vẫn phát nhãn chiều cũ với $v = 0\text{ km/h}$.
    2. **Tại bến đầu ($s = 0$)**: 77,9% số chuyến chỉ cập nhật nhãn chiều mới sau khi xe đã rời bến xuất phát được trung vị $s_{\text{start}} \approx 410\text{m}$.
  * **Quy tắc kiểm soát bắt buộc ở Module 3**:
    1. Luôn bật `trim_terminals=True` trong `segment_trajectory_into_trips` để cắt bỏ toàn bộ phần đuôi xe đứng im tại bến cuối và phần đầu xe đỗ chờ tại vạch xuất phát.
    2. **Tuyệt đối cấm ngoại suy ngược về Trạm 0** nếu bản tin đầu tiên của chuyến có $s_{\text{start}} > s_{\text{station\_0}}$; chỉ trích xuất mẫu cho các trạm từ $s_{\text{start}}$ trở đi.

- [ ] **TD-O04: Hai tuyến ngoại thành (`Route 67` và `Route 92`) nằm ngoài vùng phủ sự cố TomTom (46/48 tuyến có sự cố)**
  * **Vị trí**: Bảng `fact_route_tomtom_incidents`.
  * **Bản chất kỹ thuật**: Bounding Box thu thập sự cố TomTom tập trung vào khu vực nội đô và hành lang Bách Khoa (HUST Cluster). Hai tuyến ngoại thành `67` và `92` không giao cắt với các LineString sự cố trong 28 ngày qua.
  * **Quy tắc kiểm soát bắt buộc ở Module 3**: Khi join đặc trưng sự cố TomTom vào Feature Store, sử dụng `LEFT JOIN` với giá trị mặc định `COALESCE(delay_seconds, 0)` và `COALESCE(magnitude_of_delay, 0)`. Với tuyến `67` và `92`, mô hình sẽ tự động dựa vào tín hiệu động học thực tế của đoàn xe (`recent_speed_kmh`, `speed_ratio_to_baseline`).

- [ ] **TD-O05: Chu kỳ lấy mẫu lịch sử $\Delta t \approx 80\text{s}$ dẫn đến hiện tượng nhảy cóc qua trạm ($\Delta \text{st} \ge 1$) và không tách được Dwell Time vi mô**
  * **Vị trí**: Toàn bộ dữ liệu lịch sử 28 ngày (`5.565.232` bản ghi).
  * **Bản chất kỹ thuật**: Với trung vị $\Delta t = 80\text{s}$ và khoảng cách liên trạm trung vị $579,6\text{m}$, xe buýt thường đi qua 1–2 trạm giữa 2 lần phát tin và không có bản tin phát đúng lúc xe dừng 15–30s tại trạm.
  * **Quy tắc kiểm soát bắt buộc ở Module 3**:
    1. **Cấm xây dựng mô hình tách riêng thời gian dừng trạm (micro-dwell time)**. Thời gian di chuyển vĩ mô qua từng đoạn trạm ($\Delta t_{k \to k+1}$) đã tự động bao gồm cả thời gian chạy trên đường và thời gian dừng đón trả khách tại trạm.
    2. Sử dụng nội suy tuyến tính thời điểm qua trạm $\hat{t}(s_k)$ với điều kiện kẹp chặt $\Delta t \le 150\text{s}, \Delta s \le \max(1.000\text{m},\; 1,35 \times L_{\text{seg}})$ (sai số trung vị đã kiểm chứng thực nghiệm chỉ $\approx 5,5\text{s}$).

- [ ] **TD-O06: Dung lượng trang trống (Freelist Pages) trong tệp SQLite `data/hanoi_bus_system.db`**
  * **Vị trí**: `data/hanoi_bus_system.db`.
  * **Bản chất kỹ thuật**: Sau khi xóa các bảng Gold cũ và nạp lại bảng `route_projected_telemetry`, SQLite giữ lại các trang trống bên trong file `.db` để tái sử dụng thay vì co nhỏ file trên đĩa nếu chưa chạy `VACUUM`.
  * **Quy tắc kiểm soát**: Các tác vụ phân tích và huấn luyện ở Module 3 ưu tiên đọc trực tiếp từ **1.191 phân vùng Silver Parquet** (`data/lakehouse/silver/route_projected_telemetry/`, `5.565.232` dòng, chỉ ~185 MB trên đĩa, tốc độ quét ~204.177 dòng/giây). Có thể chạy `VACUUM` cho SQLite vào cuối dự án khi đóng gói nghiệm thu.

---

### Nhóm B: Checklist 4 Bất Thường Phát Hiện Qua EDA Bước 3.1 – 3.2 (Đã Xử Lý Tuần Tự Step-by-Step)

| Thứ tự | Mã Hạng Mục | Bất Thường Phát Hiện Từ EDA Thực Nghiệm | Giải Pháp Kỹ Thuật & Kết Quả Nghiệm Thu Thực Nghiệm | Trạng Thái |
| :---: | :---: | :--- | :--- | :---: |
| **1** | **TD-B01** | **`HANOI_BBOX` cũ (`lat>=20.80, lon>=105.65`) cắt mất 28–38km lộ trình của 4 tuyến ngoại thành** (`67` Sơn Tây, `92` Ba Vì, `101A` Vân Đình, `107` Hòa Lạc — làm mất ~229.018 bản tin hợp lệ và đẩy `Tier 3` của tuyến 67 lên `98,3%`). | Mở rộng `HANOI_BBOX` trong [`config/system_config.py`](file:///z:/Desktop/Bus_tracking/config/system_config.py) thành `min_lat=20.50, max_lat=21.40, min_lon=105.20, max_lon=106.15` $\to$ Chiếu lại 48 tuyến & tái xuất Silver Parquet (`5.565.232` dòng sạch, tăng `+229.018` bản tin; `0` lỗi trên cả 4 kiểm định Silver). Cả 4 tuyến `67, 92, 101A, 107` khôi phục 100% chiều dài lộ trình $s \in [0, L]$. | ✅ **PASSED** |
| **2** | **TD-B02** | **Ngưỡng cứng `BRACKET_MAX_DS_M = 1000.0m` chặn mất 515 đoạn trạm dài $> 1.000\text{m}$** (như cầu Nhật Tân, cầu Vĩnh Tuy, Đại lộ Thăng Long trên tuyến `90, 107, 123`), khiến tỷ lệ `Tier 3` ở đoạn $> 800\text{m}$ cao gấp đôi (`19,3%` vs `10,0%`). | Thay ngưỡng cứng bằng ngưỡng kẹp không gian thích ứng theo độ dài đoạn trạm: $\Delta s_{\max} = \max(\text{BRACKET\_MAX\_DS\_M},\; 1,35 \times L_{\text{seg}})$ trong `extract_bracketed_station_arrivals`. Tỷ lệ `Tier 3` ở đoạn $> 800\text{m}$ giảm mạnh từ `19,3%` xuống chỉ còn **`4,7%`** (tương đương đoạn ngắn `3,5%`). | ✅ **PASSED** |
| **3** | **TD-B03** | **Bất đối xứng cỡ mẫu giữa 15 ngày thường (Weekday) và chỉ có 6 ngày cuối tuần (Weekend)** trong tập Train (`2026-10-08..31`), khiến áp ngưỡng cứng $N \ge 10$ làm tỷ lệ `Tier 0` cuối tuần chỉ đạt `32,8%` (trong khi ngày thường đạt `75,7%`). | Chuẩn hóa ngưỡng `Tier 0` theo mật độ mẫu trên số ngày quan sát thực tế: Ngày thường (15 ngày) giữ `BASELINE_TIER0_MIN_SAMPLES = 10` (`~0,67 mẫu/ngày`); Cuối tuần (6 ngày) dùng `BASELINE_TIER0_MIN_SAMPLES_WEEKEND = 5` (`~0,83 mẫu/ngày`). Tỷ lệ `Tier 0` toàn mạng tăng vọt từ **`49,7%` $\to$ `71,7%`** (`Tier 0 + Tier 1 = 83,2%`; trong khung giờ chính `06:00..20:00` ngày thường đạt **`84,3% Tier 0` / `93,3% Tier 0+1`**). | ✅ **PASSED** |
| **4** | **TD-B04** | **Cộng tổng trung vị `sum(tt_p50_sec)` trên lộ trình đa trạm gây sai số chệch thiếu hệ thống (`Bias = +66,71s` ở $>15$ trạm)**, trong khi cộng trung bình `sum(tt_mean_sec)` bị kéo lệch âm (`Bias = -36,66s`) do các đuôi phải kẹt đèn đỏ. | Đánh giá song song cả `Sum(tt_p50_sec)` và `Sum(tt_mean_sec)` trên tập Test (`2026-11-01..07`). Lưu trữ đồng thời cả `tt_p50_sec`, `tt_mean_sec`, `tt_p10_sec`, `tt_p90_sec`, `tt_std_sec` trong `agg_segment_travel_times` để cung cấp cả hai đặc trưng nền (Median & Mean) cho tầng Feature Store (Bước 3.3) và mô hình GBDT (Bước 3.4). | ✅ **PASSED** |

---

### Nhóm C: Giải Phẫu 3,80% (`134 / 3.522`) Đoạn Trạm Thuộc `Tier 3` Còn Lại (Định Hướng Cho Bước 3.3)

Qua kiểm toán [`experiments/eda_tier0_and_tier3_root_causes.py`](file:///z:/Desktop/Bus_tracking/experiments/eda_tier0_and_tier3_root_causes.py), toàn bộ `134 / 3.522` (`3,80%`) đoạn trạm thuộc `Tier 3` (tương ứng `4.824 / 126.792` ô ma trận) phân rã chính xác thành 2 nhóm vật lý:
1. **`83 / 134` đoạn (`61,9%`) là đoạn trạm sát vạch xuất phát/đích (`station_order = 0->1` hoặc `N-1->N`)**:
   * Do bộ cắt chuyến bật `trim_terminals=True` (`TD-O03`) để cắt bỏ các bản tin xe đứng im chờ xuất bến trong bán kính $150\text{m}$ quanh hai đầu bến và cấm ngoại suy ngược về `station_order = 0`, nên cặp trạm đầu tiên $0 \to 1$ (khi trạm 1 nằm gần bến xuất phát) được bảo vệ khỏi nhiễu đỗ bến và sử dụng vận tốc trung bình của chính tuyến đó (`route_avg_mps`).
2. **`51 / 134` đoạn (`38,1%`) là các đoạn trạm đi vòng / tránh phố đi bộ vượt quá hành lang `35m` trên đúng 4 tuyến** (`44/48` tuyến còn lại có **`0`** đoạn nội tuyến nào rơi vào `Tier 3`):
   * `Route 67` (`30` đoạn): Xe chạy thực tế trên Quốc lộ 21A / thị xã Sơn Tây đi thẳng trục chính thay vì rẽ vào nhánh đường dân sinh cũ trong hình học BusMap tĩnh ($d_{\perp} > 35\text{m}$).
   * `Route E11` (`17` đoạn): Tuyến xe điện du lịch vòng quanh Hồ Hoàn Kiếm – Hồ Tây thường xuyên phân luồng tránh không gian phố đi bộ vào cuối tuần ($d_{\perp} > 35\text{m}$).
   * `Route 40` (`2` đoạn tại `orders=[23, 24]`) và `Route 42` (`2` đoạn tại `orders=[12, 14]`): Điểm phân luồng rào chắn thi công cục bộ.
   * **Hệ quả thực tế trên Tập Test (`648.778` lượt qua đoạn trạm)**: Chỉ có đúng **`4 / 648.778` (`0,0006%`)** lượt qua trạm trong tập Test rơi vào ô `Tier 3`, trong khi **`99,25%` (`643.898` lượt)** rơi trực tiếp vào `Tier 0` và `Tier 1`!

