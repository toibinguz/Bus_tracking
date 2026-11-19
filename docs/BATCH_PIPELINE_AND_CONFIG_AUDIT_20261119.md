# Kiểm toán Batch View Pipeline & Cấu hình Hệ thống `system_config.py` (2026-11-19)

Tài liệu này bổ sung cho [PIPELINE_DATA_AUDIT_20261119.md](PIPELINE_DATA_AUDIT_20261119.md) (luồng Streaming View), bao phủ toàn bộ **luồng Batch View** (`Crawler → Kinematic Sanitizer → Bulk Ingest → Frenet Silver Projection → Lakehouse Parquet → Historical Baseline → TrainingReplay`) và kiểm tra thực tế các hằng số trong `config/system_config.py`.

---

## Phần A: Kiểm tra `config/system_config.py` & `HANOI_BBOX`

### 1. Kiểm tra `HANOI_BBOX` trên dữ liệu thực tế (`data/hanoi_bus_system.db`)
`HANOI_BBOX = {"min_lat": 20.50, "max_lat": 21.40, "min_lon": 105.20, "max_lon": 106.15}`:
- `canonical_shape_master` (`118,563` điểm): `lat = [20.6140, 21.3716]`, `lon = [105.2984, 106.0758]` → **`outside_HANOI_BBOX = 0`**.
- `canonical_station_master` (`13,301` trạm): `lat = [20.6140, 21.3716]`, `lon = [105.2988, 106.0756]` → **`outside_HANOI_BBOX = 0`**.
- **Kết luận:** Giá trị `HANOI_BBOX` trong `system_config.py` bao phủ 100% mạng lưới 176 tuyến hiện tại (`outside = 0`). **Tuy nhiên, về mặt thiết kế:** việc giới hạn cứng theo ranh giới Hà Nội là **tự bắn vào chân** nếu sau này tuyến mở rộng chạy lấn sang tỉnh kế cận (Bắc Ninh, Hưng Yên, Vĩnh Phúc, Hà Nam, Hòa Bình) — mục đích thực sự cần lọc chỉ nên là **chặn tọa độ rác `(0,0)` hoặc đảo ngược `lat/lon`**, còn việc lọc hành lang tuyến đã có `RouteHMM` (`cross_track_m <= 35.0m`) lo. Ngoài ra, `bulk_ping_ingester.py:128-129` và `multi_route_projector.py:69-74` còn viết bất nhất khi chỉ kiểm tra `min_lat`/`min_lon` mà **bỏ sót `max_lat`/`max_lon`**.

### 2. Các tham số khác trong `config/system_config.py` có rủi ro / xung đột
1. **Xung đột quy ước `direction` & `normalize_direction` (`system_config.py:336-349`):**
   - `normalize_direction` ép mọi giá trị lạ (`None`, `"-1"`, `"2"`, `"unknown"`) về `"go"` (`0`). Trong khi `catalog_refresher.py:123` coi `direction < 0` là `"DEPOT"`, `telemetry_sanitizer.py` dùng `direction == 0` cho logic depot, và `multi_route_projector.py:85` chỉ nhận `{0: "go", 1: "re"}`.
2. **Xung đột hằng số giữa SSOT và hard-code cục bộ:**
   - `BRACKET_MAX_DT_SEC = 150.0`, `BRACKET_MAX_DS_M = 1000.0` (`L210-211`, dùng cho Baseline) vs `causal_eta_training.py:22-23` hard-code `MAX_LABEL_BRACKET_SEC = 90.0`, `MAX_LABEL_BRACKET_M = 600.0`.
   - `TERMINAL_STATIONARY_TOL_M = 15.0` (`L173`) & `GPS_DRIFT_MAX_SPEED_KMPH = 80.0` (`L161`) bị hard-code lặp lại trong `causal_eta.py:35, 178`.
   - `STALE_DELTA_T_MAX_SEC = 300.0` (`L190`) trùng nghĩa với `MAX_TELEMETRY_STALE_SEC = 300.0` (`L364`).
3. **`get_database_path()` (`L34-38`):** Nếu `DEFAULT_DB_PATH` thiếu, im lặng fallback về `LEGACY_AUDIT_DB_PATH` (`telemetry_audit_2026_10_17_18.db`), dễ phục vụ dữ liệu cũ âm thầm.
4. **`CATALOG_SCAN_PREFIXES` (`L194-197`):** Hard-code `29B10..39` + `29F00..09`; sẽ sót nếu Hà Nội cấp dải biển mới (`29E`, `29F10+`, v.v.).
5. **Hệ số quy đổi tọa độ (`L155-156`):** `111320.0 * cos(21.0285°) ≈ 103,906 m/deg` (sai số `< 0.06%`) và `110540.0` (sai số `< 0.16%`) — hợp lệ tại Hà Nội.

---

## Phần B: Chi tiết luồng Batch View (`step_1_1` → `step_1_3` → `step_1_4` → `step_2_2` → `step_3_1` → `step_3_3`)

### Tầng 1: Crawler & Catalog (`step_1_1_busmap_crawler_and_relay/`)
- **`socket_client.py`:**
  - Tắt xác thực TLS (`CERT_NONE`, `L14-16`), `_BUSMAP_IP_CACHE` (TTL `600s`, `L28`) mutate không có `Lock` dù gọi từ `ThreadPoolExecutor` 18 workers.
  - Tự parse `HTTP/1.1` bằng `split(b"\r\n\r\n")` (`L63,87`), không hỗ trợ `Transfer-Encoding: chunked`, không check HTTP status code bình thường, nuốt mọi lỗi bằng `except Exception: return None` (`L102-103`).
- **`cloud_crawler_runner.py` & `local_production_crawler.py`:**
  - `cloud_crawler_runner.py:151` đặt `fut.result(timeout=2.5)`, nhỏ hơn tổng timeout retry 429 của `socket_client.py` (`2.2 + 1.5 = 3.7s`), gây `TimeoutError` cắt mất request đang retry.
  - `local_production_crawler.py:69-70, 91` dùng `datetime.now()` naive thay vì `get_hanoi_time()`, và tạo `ThreadPoolExecutor` bên trong vòng lặp micro-batch không có timeout (`L129-134`).
  - Cả hai crawler ghi tất cả bản ghi sau `sanitize_and_validate_telemetry`, kể cả `OUT_OF_BOUNDS`, `GPS_DRIFT_JUMP`, `STALE_PING`, `IDLE_DEPOT`.
- **`catalog_refresher.py`:**
  - `audit_vehicle` (`L123-124`): `route_id <= 0 or direction < 0 or (direction == 0 and speed == 0)` → `"DEPOT"` (xe chiều đi `direction == 0` đang dừng đèn đỏ ở `0 km/h` bị gán nhầm thành `"DEPOT"`).
  - Nhánh prune `"OFFLINE"` (`L225`) là dead code (không bao giờ prune xe lỗi/offline), và xe `reassigned` (`L173-185`) chỉ log chứ không cập nhật `routeId` mới vào catalog.

### Tầng 2: Kinematic Sanitizer, Bulk Ingest & Trip Segmenter (`step_1_3_telemetry_kinematic_sanitizer/`)
- **`telemetry_sanitizer.py`:**
  - **Bug đơn vị (`L75`):** `if dist < BUS_STOPPED_SPEED_KMPH:` so sánh **mét (`dist`)** với **km/h (`5.0`)**.
  - **Cache poisoning (`L91-97`):** Khi `v_derived > 80 km/h` (`is_drift_jump = True`), vẫn ghi đè `kinematic_cache[vid]` bằng tọa độ nhảy lỗi đó, làm sai phép tính ở ping hợp lệ kế tiếp.
  - Ép kiểu `float(Speed)`, `int(direction)`, `int(RouteId)` (`L41-43`) nằm ngoài `try/except`; khi `delta_t < 3.0` không chạy branch nào nên giữ `raw_speed` kể cả lúc stale; `(0.0, 0.0)` với `direction == 0, Speed == 0` bị phân loại `"IDLE_DEPOT"` trước `"OUT_OF_BOUNDS"`.
- **`bulk_ping_ingester.py`:**
  - Bỏ qua cả ngày nếu `existing_count > 100_000` (`L88-91`, magic number); chỉ kiểm tra `min_lat` / `min_lon` (`L128-129`, thiếu `max_lat`/`max_lon`); dùng `speed > 1.0` (`L144`) thay vì `BUS_STOPPED_SPEED_KMPH = 5.0`; nạp cả `GPS_DRIFT_JUMP` / `OUT_OF_BOUNDS` vào SQLite.
- **`trip_segmenter.py`:**
  - `is_terminal_reset` (`L97-100`) thiếu `s < prev_s - MAX_GPS_BACKWARD_JITTER_M` → tuyến ngắn `1000 < shape_len_m <= 1600m` có thể bị cắt chuyến giả khi đang chạy tiến.
  - `trim_terminal_stationary_ends` (`L32-61`) dùng ngưỡng `15.0m < MAX_GPS_BACKWARD_JITTER_M (20.0m)` nên lùi GPS `16–20m` ở cuối chuyến có thể cắt nhầm ping tiến hợp lệ.

### Tầng 3: Silver Projection (`step_1_4_frenet_spatial_projection/`)
- **`multi_route_projector.py`:**
  - SQL lọc `lat > min_lat AND lon > min_lon` (`L69-74`) thiếu `max_lat`/`max_lon`; bỏ qua bộ đếm rejection (`L106`); lỗi worker chỉ in ra rồi bỏ qua (`L261-262`).
- **`projection_boundary.py`:**
  - `station_direction_lookup.get((route_id, current_station_id))` (`L80-85`) ghi đè hoàn toàn `direction_hint` (nếu `current_station_id` bị trễ từ chuyến trước sẽ làm gãy `direction_runs` và reset HMM).

### Tầng 4: Lakehouse Parquet (`step_2_2_parquet_medallion_lakehouse/`)
- **`lakehouse_exporter.py`:**
  - `db_dates` (`L184-192`) không lọc `cross_track_m <= 35.0` → ngày chỉ có ping ngoài hành lang bị quét lại mãi mỗi lần chạy; check `os.path.exists(p_file)` bỏ qua ping bổ sung; ghi Parquet không atomic; `len(existing_inc_files) == 0` (`L241-257`) bỏ qua toàn bộ incident nếu đã có ít nhất 1 tuyến; phân vùng theo `substr(device_update_time, 1, 10)` thay vì `device_epoch`.
- **`silver_lakehouse_auditor.py`:**
  - Chỉ đọc 4 cột (`L46`), không kiểm tra `device_epoch` hay `NaN`; `valid_speeds` (`L82`) kiểm tra nhầm `~dperp_arr.is_null()` và không assert; chia `total_rows` (`L88`) trước khi assert `total_rows >= 5_000_000` (`L98`).

### Tầng 5: Historical Baseline (`step_3_1_historical_baseline_model/baseline_matrix_builder.py`)
- `s_mono = np.maximum.accumulate(s_vals)` (`L131`): 1 cú nhảy GPS tiến sẽ giữ `s_mono` ở mức cao giả tạo cho các ping sau cho tới khi xe đuổi kịp.
- `if is_fit:` (`L309`) vs `is_train` (`L274-275`): nếu `fit_end_date < TRAIN_SPLIT_END_DATE`, các mẫu ở khoảng giữa bị cộng nhầm vào `test_seg_samples` trong thống kê EDA.
- Test 1-segment (`L536`) lọc `[1.5, 65.0] km/h`, loại bỏ các ca tắc nặng `< 1.5 km/h` khỏi MAE đánh giá 1 đoạn.
- Nhánh Tier 2a cho cuối tuần (`L387-392`) là dead code (vì `n_eff < 3 < 8` nên đã gom 3h từ bước trước); `sample_count` (`L432`) ghi `n_eff` thay vì `len(used_vals)`.

### Tầng 6: Training Replay (`causal_eta_training.py` & `scripts/train_causal_eta.py`)
- **`causal_eta_training.py` (`L22-23, 99-109`):** `MAX_LABEL_BRACKET_M = 600.0` và `MAX_LABEL_BRACKET_SEC = 90.0` cố định → trên chu kỳ BusMap ~75s, bất kỳ đoạn nào xe chạy trung bình `> 28.8 km/h` (`ds > 600m`) đều bị **loại khỏi nhãn train**, gây thiên lệch tập train về phía chậm.
- **`scripts/train_causal_eta.py`:**
  - `replay_silver` (`L72`) gán `fleet_valid=True` ngay cả khi mới có vài xe xuất hiện đầu ngày.
  - `L103-104` vẫn trỏ đường dẫn cũ `module_3_bus_eta_prediction/causal_eta.py` và `causal_eta_training.py` (sẽ văng `FileNotFoundError` khi gọi `digest()` ở `L106`).

---

## Phần C: Xếp hạng ưu tiên các lỗi Batch View (P0 → P3)

| Ưu tiên | Vị trí | Vấn đề |
|---|---|---|
| **P0** | `causal_eta_training.py:22-23` | `MAX_LABEL_BRACKET_M = 600.0` cố định làm rơi nhãn của xe chạy `> 28.8 km/h` ở nhịp 75s |
| **P0** | `scripts/train_causal_eta.py:103-104` | Đường dẫn `causal_eta.py` / `causal_eta_training.py` cũ gây `FileNotFoundError` |
| **P1** | `telemetry_sanitizer.py:75, 91-97` | So sánh `dist` (m) với `BUS_STOPPED_SPEED_KMPH` (5.0 km/h) & cache poisoning khi drift jump |
| **P1** | `bulk_ping_ingester.py:88-91, 128-129` & `multi_route_projector.py:69-74` | Thiếu `max_lat`/`max_lon` trong lọc `HANOI_BBOX`, magic `100_000` bỏ sót dữ liệu |
| **P1** | `cloud_crawler_runner.py:151` & `socket_client.py:24-34, 63` | Timeout future `2.5s < 3.7s` retry; DNS cache không lock; tự parse HTTP không hỗ trợ `chunked` |
| **P2** | `trip_segmenter.py:97-100` & `baseline_matrix_builder.py:131` | `is_terminal_reset` thiếu `s < prev_s - 20m` trên tuyến `1000..1600m`; `maximum.accumulate` chốt đỉnh nhiễu |
| **P2** | `catalog_refresher.py:123, 225` | `direction == 0 & speed == 0` bị gán `"DEPOT"`; dead code prune `"OFFLINE"` |
| **P3** | `lakehouse_exporter.py` & `silver_lakehouse_auditor.py` | Ghi non-atomic, `existing_inc_files == 0`, `valid_speeds` kiểm tra sai cột |

---

## Phần D: Phản biện & Tái phân loại (Lỗi thật vs. Thỏa hiệp vs. Logic bắt buộc vs. Thừa)

1. **`HANOI_BBOX` hẹp (`20.50..21.40, 105.20..106.15`) + kiểm tra thiếu `max_lat`/`max_lon`:**
   - Dùng `HANOI_BBOX` chật để loại dữ liệu xe buýt là **ràng buộc thừa (tự bắn vào chân)** với tuyến liên tỉnh mở rộng; chỉ cần chặn `(0,0)` / đảo ngược `lat/lon` (khung Việt Nam/Bắc Bộ rộng), vì `RouteHMM` đã lọc theo tim tuyến. Việc `bulk_ping_ingester` và `multi_route_projector` chỉ check `min_lat/min_lon` là **lỗi code bất nhất**.
2. **`MAX_LABEL_BRACKET_M = 600.0`, `MAX_LABEL_BRACKET_SEC = 90.0` (`causal_eta_training.py:22-23`):**
   - Siết `dt <= 90s` để nội suy tuyến tính nhãn ground-truth sạch hơn `150s` của baseline là **thỏa hiệp hợp lý**, nhưng đặt `600m` cứng với chu kỳ BusMap `75s` làm rơi nhãn xe chạy `> 28.8 km/h` là **lỗi hiệu chỉnh tham số** (cần nới `MAX_LABEL_BRACKET_M` lên ~`1000m`).
3. **`fleet_valid=True` trong `scripts/train_causal_eta.py:72`:**
   - **Thỏa hiệp bắt buộc** do dữ liệu BusMap lịch sử không có cờ báo đã thu đủ toàn tuyến trong 1 snapshot.
4. **`s_mono = np.maximum.accumulate(s_vals)` (`baseline_matrix_builder.py:131`) & `os.path.exists` trong `lakehouse_exporter.py`:**
   - `s_mono` là **thỏa hiệp có chủ đích** để tránh rung lùi GPS tạo nhiều lần cắt trạm giả (nhưng dễ bị kẹt nếu có 1 cú nhảy tiến). Skip theo `os.path.exists` là **thỏa hiệp hiệu năng** cho ngày đã đóng sổ (chỉ sai với ngày đang crawl dở).
5. **Những lỗi thật 100% (không có lý do giữ lại):**
   - `scripts/train_causal_eta.py:103-104` trỏ sai path (`FileNotFoundError`).
   - `telemetry_sanitizer.py:75` so `dist` (m) với `BUS_STOPPED_SPEED_KMPH` (5.0 km/h) và `L91-97` cache poisoning khi drift jump.
   - `catalog_refresher.py:123, 225`: `direction == 0 & speed == 0` bị gán `"DEPOT"`; dead prune `"OFFLINE"`.
   - `cloud_crawler_runner.py:151` (`timeout=2.5s < 3.7s` retry 429) & `socket_client.py` (IP cache không lock, không hỗ trợ `chunked`).
   - `trip_segmenter.py:97-100` (`is_terminal_reset` thiếu `s < prev_s - 20m` trên tuyến `1000..1600m`).
   - `lakehouse_exporter.py` (`db_dates` thiếu `cross_track_m <= 35.0`, `existing_inc_files == 0`, ghi non-atomic) & `silver_lakehouse_auditor.py:82, 88`.
   - `system_config.py:34-38` (`get_database_path` fallback âm thầm sang dump `2026-10-17`).
