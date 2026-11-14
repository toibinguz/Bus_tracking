# SPEC-38: Biên bản Kiểm toán Lỗi Module 1 & Kết nạp Nợ Kỹ thuật

**Document ID:** `38_MODULE_1_DEFECT_AUDIT_AND_TECHNICAL_DEBT`
**Ngày ban hành:** 2026-11-12
**Tác giả:** `@orchestrator` (kiểm toán read-only, hợp nhất từ 3 nhánh kiểm toán song song)
**Trạng thái:** ACCEPTED AS TECHNICAL DEBT
**Phạm vi:** `module_1_data_ingestion_and_preprocessing/` (step_1_1, step_1_3, step_1_4, step_1_5).
**Ngoài phạm vi:** Module HDFS (`step_2_4_hdfs_history`) — không chạm tới.

---

## 1. Quyết định (Decision)

Audit xác nhận Module 1 **vẫn vận hành đúng chức năng** trên dữ liệu thực tế hiện tại.
Tuy nhiên tồn tại một số khuyết điểm có mức độ nghiêm trọng tiềm ẩn về bảo mật,
độ chính xác và khả năng bảo trì, nhưng **chưa gây lỗi hoạt động quan sát được**.

Theo chỉ thị người dùng, các khuyết điểm này được **kết nạp vào Sổ cái Nợ Kỹ thuật**
thay vì sửa ngay trong giai đoạn này (các module thượng nguồn đang bị "freeze"
theo SPEC-19). Việc sửa cần một quyết định bãi bỏ freeze riêng.

Mã nợ dùng tiền tố `TD-M1-xx` để không đụng độ dải `TD-01..TD-64` của SPEC-07.

**Định dạng mỗi mục:** `[MỨC ĐỘ] file:line — mô tả — bằng chứng — tác động`.

---

## 2. Sổ cái Nợ Kỹ thuật Module 1

### 2.1. Mức CAO (High)

#### TD-M1-01 — Vô hiệu hóa kiểm tra chứng chỉ TLS trên 5 client mạng
- **Định vị:**
  - `step_1_1_busmap_crawler_and_relay/socket_client.py:15-16`
  - `step_1_1_busmap_crawler_and_relay/catalog_manager.py:14-15`
  - `step_1_1_busmap_crawler_and_relay/incident_client.py:28-29`
  - `step_1_1_busmap_crawler_and_relay/hf_lake_sync.py:28-29`
  - `step_1_1_busmap_crawler_and_relay/catalog_refresher.py:49`
- **Mô tả:** Mọi kết nối ra ngoài (BusMap socket, TomTom, HuggingFace, catalog)
  dựng `ssl.SSLContext` với `check_hostname = False` và `verify_mode = ssl.CERT_NONE`
  (hoặc `ssl._create_unverified_context()`), tức chấp nhận mọi chứng chỉ.
- **Bằng chứng:** `grep -rn "CERT_NONE\|_create_unverified_context"` trả về đúng 5 vị trí trên.
- **Tác động:** Kẻ tấn công MITM có thể giả mạo phản hồi API → **đầu độc dữ liệu viễn trắc**
  (tọa độ/tốc độ sai) và **đánh cắp token HuggingFace** khi đồng bộ hồ. Chưa biểu hiện
  lỗi chức năng vì môi trường hiện tại chưa bị tấn công.

#### TD-M1-02 — Salt của BusMap bị hard-code trong mã nguồn
- **Định vị:** `step_1_1_busmap_crawler_and_relay/catalog_refresher.py:48,54`
- **Mô tả:** `BUSMAP_SALT = ":Bus2019M@p_"` là hằng chuỗi cố định dùng để sinh token:
  `raw_token = f"{epoch_ms}{BUSMAP_SALT}"`.
- **Bằng chứng:** Xem dòng 48 & 54.
- **Tác động:** Bí mật xác thực nằm trong VCS; nếu kho mã rò rỉ, kẻ khác có thể giả mạo
  token truy cập và ghi dữ liệu giả vào luồng BusMap. Không ảnh hưởng vận hành thường.

#### TD-M1-03 — Dùng giờ tường (naive `datetime.now()`) để tính ranh giới ngày/tháng quota
- **Định vị:** `step_1_1_busmap_crawler_and_relay/local_production_crawler.py:68-69,90`
- **Mô tả:** `current_day = datetime.now().day`, `current_month = datetime.now().month`,
  `now = datetime.now()` — không kèm timezone, dùng giờ hệ điều hành.
- **Bằng chứng:** Xem dòng 68, 69, 90.
- **Tác động:** Nếu tiến trình chạy trên máy đặt UTC (khác GMT+7), ranh giới ngày quota
  TomTom bị lệch 7 giờ → reset quota sai thời điểm, dẫn lệch sổ cái quota. Hiện tại máy
  chạy giờ local nên chưa biểu hiện.

### 2.2. Mức TRUNG BÌNH (Medium)

#### TD-M1-04 — Sai đơn vị: so sánh khoảng cách (mét) với ngưỡng tốc độ (km/h)
- **Định vị:** `step_1_3_telemetry_kinematic_sanitizer/telemetry_sanitizer.py:75`
- **Mô tả:** `if dist < BUS_STOPPED_SPEED_KMPH:` — `dist` là khoảng cách **mét** (từ `haversine_distance`),
  nhưng `BUS_STOPPED_SPEED_KMPH = 5.0` là **tốc độ km/h**. So sánh khác thứ nguyên.
- **Bằng chứng:** Dòng 74 (`dist = haversine_distance(...)`) và dòng 75; hằng số tại `config/system_config.py:180`.
- **Tác động:** Hiện chỉ vô tình đúng vì cả hai đều nhỏ; nếu hằng số tốc độ được chỉnh theo
  ngữ nghĩa km/h, logic "xe dừng" sẽ sai → tính sai `smoothed_speed`. Không gây lỗi chức năng
  với giá trị hiện hành.

#### TD-M1-05 — Kiểm tra biên hộp Hà Nội bất đối xứng trong bulk ingester
- **Định vị:** `step_1_3_telemetry_kinematic_sanitizer/bulk_ping_ingester.py:128`
- **Mô tả:** `if lat < HANOI_BBOX["min_lat"] or lon < HANOI_BBOX["min_lon"]: continue` —
  chỉ loại điểm dưới biên dưới, **bỏ qua** biên trên (`max_lat`/`max_lon`).
- **Bằng chứng:** So sánh với `telemetry_sanitizer.py:105-106` (kiểm tra đủ 4 biên).
- **Tác động:** Điểm GPS nằm trên/dưới biên trên (phía bắc/đông) lọt vào DB ở luồng bulk,
  gây `OUT_OF_BOUNDS` không nhất quán giữa hai luồng nạp. Chưa thấy dữ liệu ngoài biên trên.

#### TD-M1-06 — Điểm GPS nhảy (drift) chỉ bị gán nhãn, không bị loại
- **Định vị:** `step_1_3_telemetry_kinematic_sanitizer/telemetry_sanitizer.py:80-83,110-111`
- **Mô tả:** Khi `v_derived > GPS_DRIFT_MAX_SPEED_KMPH`, code đặt `is_drift_jump = True` và
  dùng lại tốc độ làm mịn cũ, nhưng **vẫn ghi điểm** với tọa độ nhảy và nhãn `GPS_DRIFT_JUMP`.
- **Bằng chứng:** Dòng 80-83 (không `continue`/không loại) và dòng 110 (chỉ gán nhãn).
- **Tác động:** Chấp nhận được về thiết kế (downstream lọc theo nhãn), nhưng nếu có consumer
  bỏ qua trường `quality_status` thì tọa độ nhảy sẽ vào pipeline vị trí. Rủi ro phụ thuộc consumer.

#### TD-M1-07 — Xử lý hình dạng đặc thù tuyến hard-code (E11 / E11CT / 123)
- **Định vị:** `step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py:224-242`
- **Mô tả:** Logic đảo/ghép polyline đặc biệt cho đúng 3 mã tuyến `"E11"`, `"E11CT"`, `"123"`
  bằng nhánh `if r_code in (...)`, `if r_code == "123"`. Có magic-number mô tả "65km", "23.7km, 250 pts".
- **Bằng chứng:** Dòng 227-242.
- **Tác động:** Nợ bảo trì: tuyến mới lỗi tương tự sẽ không được xử lý; dữ liệu BusMap thay đổi
  sẽ âm thầm sai. Hiện đúng với 3 tuyến đang có.

#### TD-M1-08 — Nuốt ngoại lệ âm thầm (`except Exception: pass`)
- **Định vị:** `step_1_4_frenet_spatial_projection/tomtom_incident_projector.py:266-267`
- **Mô tả:** Bao ngoài khối parse bản ghi sự cố TomTom rồi `except Exception: pass`, không log.
- **Bằng chứng:** Dòng 266-267. (Có tiền lệ tương tự `multi_route_projector.py:24` nhưng đó là
  `sys.stdout.reconfigure` — chấp nhận được.)
- **Tác động:** Bản ghi sự cố hỏng bị bỏ qua im lặng → khó phát hiện suy giảm chất lượng dữ liệu
  sự cố. Không gây crash.

### 2.3. Mức THẤP (Low)

#### TD-M1-09 — Cache DNS toàn cục không an toàn đa luồng
- **Định vị:** `step_1_1_busmap_crawler_and_relay/socket_client.py:19-34`
- **Mô tả:** Dict cache DNS dùng chung toàn cục, không khóa; có thể bị race khi đa luồng.
- **Tác động:** Hiếm khi sai; cùng lắm là tra cứu lại DNS. Không ảnh hưởng dữ liệu.

#### TD-M1-10 — Sàn cửa sổ quét tiến 1500 m cố định
- **Định vị:** `step_1_4_frenet_spatial_projection/multi_route_projector.py:103`
- **Mô tả:** `max_forward = max(FRENET_MIN_FORWARD_WINDOW_M, dt * FRENET_MAX_SPEED_MPS)`
  (`FRENET_MIN_FORWARD_WINDOW_M = 1500.0`). Có nhánh theo tốc độ, nhưng luôn bị sàn 1500 m.
- **Tác động:** Về lý thuyết một ping có thể khớp tiến xa tới 1500 m so với ping trước nếu
  hành lang uốn gần chính nó; tuy nhiên đã có ngưỡng ngang `MAX_CORRIDOR_CROSS_TRACK_M=35 m`
  và fallback quét toàn cục nên rủi ro thấp.

#### TD-M1-11 — Chưa xác minh khớp hướng trạm ↔ hình dạng cho E11/E11CT/123
- **Định vị:** `step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py:344-345`
- **Mô tả:** Trạm dùng `StationDirection` (`0→"go"`, khác `1→"re"`), trong khi hình dạng E11/E11CT
  đã được đảo nhãn hướng ở dòng 227-232. Cần đối chiếu bằng dữ liệu thật để chắc chắn `d_str`
  của trạm khớp `d_str` của hình dạng cho mọi tuyến đặc biệt.
- **Tác động:** Nếu lệch, chiếu trạm lên hình dạng sẽ sai thứ tự/khoảng cách. Chưa quan sát sai lệch.

---

## 3. Các nghi vấn đã được loại trừ (False positives ruled out)

| Nghi vấn | Kết luận | Căn cứ |
| --- | --- | --- |
| `projection_boundary.py:125-133` đánh khóa theo `event_id` có thể trùng | **AN TOÀN** | `event_id=f"legacy:{ping_id}"`, `ping_id` là rowid SQLite duy nhất |
| `tomtom_incident_projector.py` hard-code TTL | **SAI** | Import `TOMTOM_DEFAULT_TTL_SEC=900`, `TOMTOM_MAX_BATCH_GAP_SEC=1200` từ config |
| Tồn tại `except:` trần | **KHÔNG** | Chỉ có `except Exception` |
| Tồn tại `TODO`/`FIXME` | **KHÔNG** | grep không tìm thấy |
| Quota TomTom tăng khi fetch lỗi (crawler:179-180, 205-206) | **CHẤP NHẬN ĐƯỢC** | Đếm theo *lần gọi* API là thận trọng; nếu lỗi xảy ra trước khi gửi thì chỉ *giảm* sử dụng (an toàn) |

---

## 4. Rủi ro nghiêm trọng nhất (Top risk)

**TD-M1-01 (TLS bị vô hiệu hóa trên cả 5 client).** Đây là điểm yếu gốc: nó biến mọi
kênh thu thập dữ liệu thành kênh không xác thực, cho phép đầu độc dữ liệu viễn trắc và
đánh cắp token HuggingFace đồng thời. Mọi nợ khác chỉ ảnh hưởng cục bộ.

---

## 5. Đề xuất (không thực thi trong giai đoạn freeze)

1. Bật lại xác thực TLS (`verify_mode = CERT_REQUIRED`) cho tất cả client; nếu cert BusMap
   tự ký, đính kèm CA riêng thay vì tắt kiểm tra.
2. Chuyển `BUSMAP_SALT` và token HF sang biến môi trường / secret store.
3. Chuẩn hóa mọi mốc thời gian sang `datetime.now(timezone.utc)` + quy đổi GMT+7 khi cần.
4. Đồng bộ logic kiểm tra bbox giữa `bulk_ping_ingester` và `telemetry_sanitizer`.
5. Thay magic-number tuyến trong `ingest_busmap_canonical` bằng bảng ánh xạ dữ liệu cấu hình.
