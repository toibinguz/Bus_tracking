# SPEC-39: Biên bản Kiểm toán Lỗi Bước 3.4 & 3.5 và Danh mục "Sửa Nhanh"

**Document ID:** `39_STEP_3_4_3_5_DEFECT_AUDIT_AND_QUICK_WINS`
**Ngày ban hành:** 2026-11-12
**Tác giả:** `@orchestrator` (kiểm toán read-only, hợp nhất từ các nhánh kiểm toán song song)
**Trạng thái:** ACCEPTED AS TECHNICAL DEBT + QUICK-WIN BACKLOG — **UNFREEZE ĐƯỢC CHẤP THUẬN** (chỉ thị chủ sở hữu, 2026-11-12)
**Phạm vi:** `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/` và `step_3_5_web_demo/`.
**Ngoài phạm vi:** Module HDFS (`step_2_4_hdfs_history`) — không chạm tới.

---

## 1. Quyết định (Decision)

Kiểm toán read-only bước 3.4/3.5 kết luận: **không có lỗi mức CAO**. Các nghi vấn CAO ban đầu
đều được bác bỏ (xem §5): chúng hoặc là mã tuân thủ SPEC-24, hoặc là mã chết, hoặc đã được
khắc phục trước đó.

Toàn bộ khuyết điểm còn lại **chưa gây lỗi chức năng quan sát được**; theo chỉ thị người dùng,
chúng được **kết nạp vào Sổ cái Nợ Kỹ thuật** thay vì sửa ngay. Lý do ràng buộc:
SPEC-19 §15-16 **đóng băng** "Module 3.4 public serving facade và các phụ thuộc" cùng
"Module 3.5 FastAPI adapter, launcher contract, static client" — mọi sửa đổi cần
**một quyết định unfreeze tường minh**; riêng Module 3.5 còn bị chặn bởi **SPEC-22 §5
change gate** (chỉ được sửa sau khi có *reproducible failure* chỉ ra vi phạm hợp đồng quan sát được).

Vì mục tiêu giai đoạn này là chuyển sang việc khác, tài liệu này phân loại mỗi khuyết điểm thành:

- **§3 SỬA NHANH (Quick Win)** — sửa được bằng vài dòng, ngữ nghĩa không mơ hồ, không rủi ro
  hành vi. Sẵn sàng gộp vào **một** task sửa duy nhất khi có quyết định unfreeze.
- **§4 BỎ QUA GIAI ĐOẠN NÀY (Skip)** — cần dữ liệu/quyết định thiết kế/artifact tái hiện; ghi nợ, không đụng.

Mã nợ dùng tiền tố `TD-34-xx` / `TD-35-xx`; mã việc nhanh dùng `QW-xx` (không đụng dải
`TD-01..TD-64` của SPEC-07 và `TD-M1-xx` của SPEC-38).

**Định dạng mỗi mục:** `[MỨC ĐỘ] file:line — mô tả — bằng chứng — tác động`.

---

## 2. Sổ cái Nợ Kỹ thuật 3.4 / 3.5

### 2.1. Mức TRUNG BÌNH

#### TD-35-01 — Đua dữ liệu chéo tuyến: marker/ETA của tuyến cũ render lại trên bản đồ đã xóa
- **Định vị:** `step_3_5_web_demo/static/app.js:633` (`pollVehicles`, guard `if (!currentRouteId || isPolling) return;`),
  `:689` (`startPolling`), `:765` (`setDirection`).
- **Mô tả:** Khi đổi tuyến/chiều, `currentRouteId` cập nhật → `clearAllMarkers()` → `startPolling()`
  → lời gọi `pollVehicles()` mới bị bỏ qua vì `isPolling` vẫn `true`. Trong lúc đó request
  cũ đang bay vẫn chạy `updateMarkers`/`renderVehicleList` bằng dữ liệu tuyến cũ, sau `finally`
  mới nhả `isPolling=false`.
- **Bằng chứng:** Đọc trực tiếp 3 điểm trên; cửa sổ đua = độ trễ fetch (~100–300 ms).
- **Tác động:** Vi phạm hợp đồng quan sát được **SPEC-22 L-04** ("đổi chiều/tuyến → marker và
  lựa chọn trạm cũ bị xóa, không replay/không giá trị bịa"). Kết quả: bản đồ trống nhưng
  danh sách xe/ETA nhấp nháy dữ liệu tuyến cũ.

#### TD-35-02 — Endpoint không có biên lỗi: ngoại lệ → HTTP 500 thô, UI hiển thị sai nguyên nhân
- **Định vị:** `step_3_5_web_demo/app.py:87,108,137,166,206` (5 endpoint, không `try/except`);
  `service = BusMapServingService()` tại `:57`.
- **Mô tả:** Mọi ngoại lệ (BusMap timeout, lỗi parse, DB lock) nổi lên thành HTTP 500 raw;
  phía client (`app.js`) quy mọi lỗi fetch về thông điệp "Mất kết nối GPS".
- **Bằng chứng:** Đọc 5 handler; SPEC-20/SPEC-22 **không** định nghĩa error envelope cho 5xx.
- **Tác động:** Người dùng cuối nhận chẩn đoán sai (tưởng lỗi mạng, thực chất lỗi server).
  Chưa biểu hiện lỗi trong demo tĩnh vì endpoint không bị ném ngoại lệ.

#### TD-35-03 — Nhãn chiều có nguy cơ đảo ngược giữa UI và quy ước BusMap
- **Định vị:** `step_3_5_web_demo/static/index.html:57-64` (UI: `0` = "Chiều đi (A→B)")
  so với `step_1_1_busmap_crawler_and_relay/catalog_refresher.py:70` (`0` = "Chiều về / B->A").
- **Bằng chứng:** SPEC-04:51 (`0` = Chiều về) mâu thuẫn SPEC-05:91 (`0` = 'go' = Chiều đi);
  pipeline dữ liệu tự nhất quán (`ingest_busmap_canonical.py:219` ánh xạ BusMap dir 0 → `"go"`),
  nên overlay bản đồ vẫn đúng — nghi vấn nằm ở **chuỗi nhãn hiển thị**.
- **Tác động:** Người dùng có thể chọn sai nhãn chiều nếu quy ước BusMap thực tế ngược với UI.
  Chưa kết luận là lỗi: cần dữ liệu BusMap thật để xác nhận chiều trước khi sửa.

#### TD-34-01 — `THONG_THOANG` thiếu điều kiện trễ hạn `delay < 30`
- **Định vị:** `step_3_4_eta_serving_and_evaluation/eta_policy.py:196-201`.
- **Mô tả:** Mã hiện tại: `if v_obs < CONGESTION(10.0) or is_delayed → UN_TAC; elif v_obs < FREEFLOW(20.0) → BINH_THUONG;
  else → THONG_THOANG`. Nhánh `else` không kiểm tra độ trễ, trong khi đặc tả yêu cầu
  `THONG_THOANG` chỉ khi `v_obs ≥ 20.0` **và** `delay < 30`.
- **Bằng chứng:** SPEC-16:368 (định nghĩa trạng thái giao thông); hằng số tại `config/system_config.py:371-372`
  (10.0 / 20.0); **không tồn tại** hằng số ngưỡng 30 trong config.
- **Tác động:** Xe chạy nhanh nhưng đang trễ `30 ≤ delay < 120` giây bị gán nhãn "Thông thoáng"
  → nhãn trạng thái lạc quan sai so với hợp đồng SPEC-16 §2.10.

#### TD-34-02 — Lệch train/serve thứ tư: `ego_cum_delay` luôn đóng băng 0.0 khi phục vụ
- **Định vị:** `step_3_4_eta_serving_and_evaluation/online_features.py:280` (`ego_cum_delay = 0.0`).
- **Mô tả:** Lúc huấn luyện, đặc trưng `ego_cum_delay_vs_baseline_sec` mang giá trị thật;
  lúc phục vụ luôn bằng 0.0.
- **Bằng chứng:** SPEC-09 §4.2 "Phương án A (Bảo thủ - Khuyến nghị)" **đề xuất đúng** `D_cum = 0.0`
  cho cold-start → **không** phải vi phạm rõ ràng; nhưng SPEC-16 §2.11 chỉ liệt kê đúng 3 sai lệch
  M1/M2/M3, đây là sai lệch **thứ tư chưa được ghi nhận**.
- **Tác động:** Phân phối đặc trưng vào booster lệch giữa train và serve ở một chiều cố định;
  ảnh hưởng bậc hai lên ETA, không gây lỗi quan sát được.

### 2.2. Mức THẤP

#### TD-34-03 — `live_cache` cấp module không khóa (race đọc/ghi giữa thread)
- **Định vị:** `step_3_4_eta_serving_and_evaluation/live_feed.py:69`.
- **Mô tả:** `live_cache: Dict[Tuple[int,int], Tuple[float, RouteLiveResponse]] = {}` được đọc/ghi
  không có `threading.Lock`.
- **Bằng chứng:** Dòng 69 (khai báo) và vùng truy cập trong `fetch_live_vehicles_for_route`.
- **Tác động:** Với `uvicorn` nhiều worker/thread có thể ghi đè cache đồng thời → phục vụ dữ liệu
  cũ tối đa thêm `LIVE_CACHE_TTL_SEC` (8.0 s). Chưa biểu hiện lỗi dữ liệu.

#### TD-34-04 — Cache cả phản hồi rỗng từ BusMap trong TTL
- **Định vị:** `step_3_4_eta_serving_and_evaluation/live_feed.py:95-97`.
- **Mô tả:** Khi BusMap trả rỗng/lỗi, kết quả rỗng vẫn được ghi vào `live_cache` với TTL 8.0 s.
- **Bằng chứng:** `live_cache[cache_key] = (now_mono, empty_res)`; TTL tại `config` (`LIVE_CACHE_TTL_SEC = 8.0`,
  quy định SPEC-16:526). SPEC-23:59 chỉ cấm *bịa/replay ETA*, không cấm cache rỗng.
- **Tác động:** Trạng thái "không có xe" bị giữ thêm tối đa 8 s sau khi upstream hồi phục.
  Đúng thiết kế bảo vệ upstream → **không đề xuất sửa**.

#### TD-34-05 — `_connect` chưa thực sự read-only
- **Định vị:** `step_3_4_eta_serving_and_evaluation/data_access.py:125-132`.
- **Mô tả:** `sqlite3.connect(str(self._db_path))` mở ở chế độ đọc-ghi dù docstring ghi "SQLite read-only".
- **Bằng chứng:** Dòng 125-132; toàn bộ 4 lượt dùng `_connect()` (dòng 140, 183, 255, 305) chỉ là
  truy vấn đọc; **không có** `INSERT/UPDATE/DELETE/CREATE/commit` trong file.
- **Tác động:** Nếu một ngày có lỗi/logic mới vô tình ghi vào DB 3 GB (`data/hanoi_bus_system.db`),
  sẽ hỏng nguồn chuẩn. Hiện chưa có đường ghi nào.

#### TD-35-04 — CSS chết `.focus-eta-val.arriving-now`
- **Định vị:** `step_3_5_web_demo/static/style.css:424-427`.
- **Bằng chứng:** `grep -rn "arriving-now" static/` chỉ trả về đúng rule CSS này — không phần tử nào mang class đó.
- **Tác động:** Dư thừa sau khi SPEC-24 bỏ trạng thái `ARRIVING_NOW`. Không ảnh hưởng hiển thị.

#### TD-34-06 — Hằng số mô phỏng hard-code trong trích xuất đặc trưng
- **Định vị:** `step_3_4_eta_serving_and_evaluation/online_features.py:43-65`.
- **Bằng chứng:** Các hằng số ước lượng tốc độ/độ trễ đặt inline thay vì trong `config/system_config.py`.
- **Tác động:** Khó truy vết nguồn gốc số liệu; rủi ro trôi khỏi tham số huấn luyện.

#### TD-34-07 — `busmap_service.py` là mã chết
- **Định vị:** `step_3_4_eta_serving_and_evaluation/busmap_service.py`.
- **Bằng chứng:** `app.py` không import; ghi chú trong `__init__.py` nêu "đang ImportError… sẽ retire ở task 10".
- **Tác động:** Không có đường thực thi từ runtime → mọi phát hiện trong file này **không thể chạm tới**.
  Thanh lý như dọn dẹp, không phải sửa lỗi.

---

## 3. Danh mục SỬA NHANH (Quick Win Backlog)

Tiêu chí vào danh mục: (a) khuếch tán thay đổi ≤ vài dòng trong ≤ 2 file, (b) ngữ nghĩa không mơ hồ,
(c) không đổi hợp đồng công khai ngoài việc **khôi phục đúng** đặc tả đã ký. Tất cả **vẫn cần
một quyết định unfreeze** (SPEC-19) trước khi `@leaf_coder` chạm mã.

| ID | Nợ | Địa chỉ | Thay đổi | Kiểm chứng |
|----|----|---------|----------|------------|
| QW-01 | TD-34-01 | `config/system_config.py` + `eta_policy.py:201` | Thêm hằng `THONG_THOANG_MAX_DELAY_SEC = 30.0`; đổi nhánh cuối thành `elif v_obs_kmh < FREEFLOW… : BINH_THUONG` / `else` chỉ khi `delta_delay < THONG_THOANG_MAX_DELAY_SEC`, còn lại `BINH_THUONG`. | Đối chiếu SPEC-16:368; test biên `delay = 30` và `delay = 0` |
| QW-02 | TD-34-05 | `data_access.py:125` | `sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)`. | 4 truy vấn đọc (140/183/255/305) chạy lại không đổi kết quả; không có mã ghi |
| QW-03 | TD-35-04 | `static/style.css:424-427` | Xóa block rule chết `.focus-eta-val.arriving-now`. | `grep -rn "arriving-now" static/` → rỗng; UI không đổi |
| QW-04 | TD-34-02 | `online_features.py:280` | **Chỉ khi** có quyết định mô hình: khôi phục `ego_cum_delay` thật hoặc ghi chính thức sai lệch thứ tư vào SPEC-16 §2.11. | Không sửa mã nếu chọn Phương án A (SPEC-09 §4.2) — khi đó **chỉ cập nhật SPEC-16 §2.11** |

### 3.1. Quyết định unfreeze & chốt ngữ nghĩa cho đợt sửa (2026-11-12)

**Unfreeze:** Chủ sở hữu ra chỉ thị trực tiếp "Sửa" đối với danh mục Quick Win ở §3.
Đây là quyết định unfreeze tường minh theo SPEC-19 §22/§86 cho phạm vi hẹp: **chỉ QW-01, QW-02, QW-03**.
Không có mục nào khác trong tài liệu này được unfreeze.

**Miễn trừ gate SPEC-22 §5 (owner waiver):** QW-03 chạm `step_3_5_web_demo/static/style.css`.
SPEC-22 §5 yêu cầu *reproducible failure* của hợp đồng L-01..L-05 trước khi sửa Module 3.5;
QW-03 là **gỡ CSS chết** (không phần tử nào mang class, không thay đổi hành vi tương tác) nên không
có failure để tái hiện. Việc sửa được thực hiện **theo miễn trừ trực tiếp của chủ sở hữu** và được
ghi nhận tại đây làm căn cứ truy vết; có thể hoàn nguyên độc lập bằng cách khôi phục 4 dòng CSS.

**Chốt ngữ nghĩa QW-01 (lấp lỗ hổng đặc tả):** SPEC-16:368 định nghĩa
`UN_TAC` (v<10 hoặc delay≥120), `BINH_THUONG` (10≤v<20 và delay<120), `THONG_THOANG` (v≥20 và delay<30)
nhưng **không phủ** trường hợp `v ≥ 20` và `30 ≤ delay < 120`. Quyết định: gán trường hợp này về
`BINH_THUONG` (xe chạy nhanh nhưng đang trễ 30–120 s ⇒ "bình thường", không "thông thoáng").
Phân hoạch sau khi sửa — **đầy đủ và không chồng lấn**:

| Điều kiện | Nhãn |
|---|---|
| `v < 10.0` **hoặc** `delay ≥ 120` | `UN_TAC` |
| `v ≥ 20.0` **và** `delay < 30` | `THONG_THOANG` |
| còn lại (`10 ≤ v < 20`, hoặc `v ≥ 20` và `30 ≤ delay < 120`) | `BINH_THUONG` |

Ngưỡng 30 **không** được viết dạng magic number: thêm hằng `THONG_THOANG_MAX_DELAY_SEC = 30.0`
vào `config/system_config.py` (nhóm "Ngưỡng trạng thái giao thông"). Việc hợp nhất bảng trên vào
văn bản SPEC-16 §2.10 là **việc đặc tả riêng, không thuộc đợt sửa này**.

**QW-04:** được hạ xuống "chỉ cập nhật đặc tả" — không sửa mã (`ego_cum_delay = 0.0` giữ nguyên
theo SPEC-09 §4.2 Phương án A).

**Bị chặn bởi gate (không nằm trong đợt sửa nhanh):**

- **TD-35-01 (đua chéo tuyến)** — bản vá cơ học nhỏ (thêm `AbortController`/request-token ~10-15 dòng tại
  `app.js:633`), **nhưng** là mã Module 3.5 nên theo **SPEC-22 §5** phải có *reproducible failure*
  chỉ ra vi phạm L-04 trước khi `@leaf_coder` được phép sửa. Đây chính là "artifact tái hiện" cần tạo.
- **TD-35-02 (biên lỗi endpoint)** — SPEC-20/22 chưa định nghĩa error envelope 5xx; tự thêm envelope
  là mở rộng đặc tả ngoài yêu cầu → **không sửa nhanh**; cần một SPEC lỗi mới nếu muốn làm.

### 3.2. Biên bản kiểm tra lại sau khi sửa (2026-11-12)

Đợt sửa QW-01/QW-02/QW-03 đã hoàn tất. Diff thực tế: `config/system_config.py` (+2),
`eta_policy.py` (+4/−3), `data_access.py` (+4/−2), `static/style.css` (−5) — đúng 4 tệp trong
phạm vi được unfreeze, không tệp nào ngoài phạm vi.

**Audit hộp trắng (`@whitebox_auditor`) — PASS cả 3 hạng mục:**
- QW-01: phân hoạch khớp đúng bảng §3.1, không chồng lấn/không hở; biên v=10.0/v=20.0/delay=30/120
  đúng; `THONG_THOANG_MAX_DELAY_SEC` đọc từ config (không magic number); `delta_delay` tái dùng
  (định nghĩa `eta_policy.py:180`), `is_delayed` vẫn gắn `REALTIME_DELAY_ALERT_SEC` (`:181`).
- QW-02: URI `file:` + `quote(path.replace("\\","/"), safe="/:")` + `?mode=ro`, gọi `uri=True`;
  `_connect` (`data_access.py:131`) là điểm kết nối **duy nhất**; 4 call site (`:142/:185/:257/:307`)
  chỉ SELECT; không có `commit`/`INSERT`/`UPDATE`/`DELETE` trong tệp.
- QW-03: `.focus-eta-val.arriving-now` đã xóa; không còn tham chiếu `arriving-now` trong toàn bộ
  `step_3_5_web_demo/`; `.focus-eta-val` gốc (`style.css:873`, `app.js:471`) còn nguyên; ngoặc CSS cân bằng.
- `python -m py_compile` 3 tệp `.py`: OK. Không có import chéo 3.4↔3.5↔HDFS phát sinh.

**Blind test hộp đen (`@blind_tester`, không đọc mã nguồn) — PASS:**
- T1 phân hoạch trạng thái: 30/30 ca đúng, 0 phản ví dụ (kể cả quét biên 29.999/30.0001/119.999/120.001).
- T2 DB canonical chỉ đọc: `get_routes()` 176 tuyến, `load_baseline_matrix()` 339.660 khóa trong 2,11 s;
  size+mtime `data/hanoi_bus_system.db` không đổi trước/sau; ghi thử → `sqlite3.OperationalError:
  attempt to write a readonly database` (xác nhận cơ chế là `mode=ro`, không phải `query_only`).
- T3 CSS chết: 0 tham chiếu `arriving-now`; xóa đúng 5 dòng.
- Lưu ý truy vết: `SafeWindowDTO.delay_seconds` được làm tròn hiển thị 1 chữ số thập phân
  (`eta_policy.py:217`), nhưng so sánh trạng thái dùng `delta_delay` **chưa làm tròn** → không dùng
  trường phản hồi này làm mốc biên khi kiểm thử.

Kết luận: cả hai biên bản kiểm tra đều ĐẠT; đợt sửa nhanh khép kín. Chưa commit (chờ quyết định).

---

## 4. Danh mục BỎ QUA GIAI ĐOẠN NÀY (Skip)

| ID | Nợ | Lý do bỏ qua |
|----|----|--------------|
| SKIP-01 | TD-35-01 | Cần artifact tái hiện theo SPEC-22 §5; ưu tiên thấp hơn việc hiện tại |
| SKIP-02 | TD-35-02 | Thiếu đặc tả error envelope → nằm ngoài yêu cầu, không tự phát minh |
| SKIP-03 | TD-35-03 | Nhãn chiều: cần dữ liệu BusMap thật xác nhận quy ước trước khi kết luận |
| SKIP-04 | TD-34-02 (mã) | Thuộc quyết định mô hình/khoa học dữ liệu, không phải "sửa nhanh" |
| SKIP-05 | TD-34-03, TD-34-04, TD-34-06 | Không gây lỗi quan sát được; sửa rủi ro > lợi ích (khóa cache, cache rỗng, hằng số mô phỏng) |
| SKIP-06 | TD-34-07 | Xóa mã chết cần quyết định thanh lý riêng (task 10 đã định) |
| SKIP-07 | `app.py:215` `uvicorn.run(reload=True)` | Hành vi launcher theo SPEC-22 L-01/L-05; không sửa |

---

## 5. Bảng bác bỏ nghi vấn (False Positives — KHÔNG tái nêu)

| Nghi vấn | Phán quyết | Căn cứ |
|----------|-----------|--------|
| `eta_policy.py:86` (`if s_now > s_target: return None`) bỏ dải ARRIVING_NOW | KHÔNG phải lỗi | SPEC-24 §3 xóa `ARRIVING_NOW`/`status` |
| `dto.py` thiếu trường `status` | KHÔNG phải lỗi | SPEC-24 bắt buộc xóa `status` |
| `model_runtime.py` "nuốt ngoại lệ im lặng" | KHÔNG phải lỗi | Có `logger.error` (load) và `logger.warning` (predict) |
| `serving_service.py:113-114` day_type/hour_slot | KHÔNG phải lỗi | Tính từ `datetime.now(TZ_HANOI)` |
| `eta_policy.py:217 recommended_arrival_time` | KHÔNG phải lỗi | Khớp SPEC-15:592 |
| SPEC-21 P0 XSS / P1 CORS | ĐÃ khắc phục | `escapeHtml` tại `app.js:55-58`; `LOCAL_DEMO_ORIGINS`, `allow_credentials=False` |
| `app.py` static health payload | KHÔNG phải lỗi | Là hợp đồng SPEC-20 I2 |
| Sai lệch so với pseudocode SPEC-15 §8 | KHÔNG phải lỗi | Bị thay thế bởi SPEC-24 + SPEC-16 §2.10 |
| Phát hiện trong `busmap_service.py` | KHÔNG thể chạm tới | Mã chết (xem TD-34-07) |

---

## 6. Rủi ro nghiêm trọng nhất

**TD-35-01 — đua dữ liệu chéo tuyến tại `static/app.js:633/689/765`.**

Đây là khuyết điểm **duy nhất vi phạm một hợp đồng quan sát được đã ký** (SPEC-22 L-04), và nó
đúng loại *reproducible failure* mà SPEC-22 §5 yêu cầu để mở quyền sửa Module 3.5. Mọi mục còn lại
hoặc không quan sát được, hoặc là mã chết, hoặc cần một quyết định thiết kế/mô hình vượt ra ngoài
phạm vi "sửa nhanh".

**Rủi ro cấp hai:** TD-35-02 — 5 endpoint không có biên lỗi biến mọi sự cố server thành
HTTP 500 thô, trong khi UI diễn giải thành "Mất kết nối GPS" → chẩn đoán sai cho người vận hành
trong buổi demo.

---

## 7. Việc tiếp theo

1. Không hành động mã cho tới khi có quyết định unfreeze (SPEC-19).
2. Nếu ưu tiên "sửa nhanh": gộp **QW-01, QW-02, QW-03** vào **một** task duy nhất và chỉ cập nhật
   đặc tả cho QW-04 (SPEC-16 §2.11) nếu chọn giữ nguyên `ego_cum_delay = 0.0`.
3. Nếu muốn chứng minh TD-35-01: tạo artifact tái hiện vi phạm L-04 → khi đó mới hợp lệ để sửa 3.5.
