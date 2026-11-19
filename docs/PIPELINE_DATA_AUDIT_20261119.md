# Kiểm toán Pipeline Dữ liệu End-to-End: Crawler / Live Feed → App Demo (2026-11-19)

Tài liệu này truy vết toàn bộ đường đi của một gói dữ liệu xe buýt từ nguồn upstream (`BusMap` / `TimBus`) qua từng tầng xử lý (`live_feed` → `serving_service` → `route_matcher` → `MacroSpeedTracker` → `CausalFeatures` → `ModelRuntime / ResidualETA` → `eta_policy` → `app.js`), liệt kê từng nhánh `if-else`, công thức toán học, magic number, cơ chế fallback che giấu lỗi và các lỗi logic phát hiện được.

---

## Phần A: Giả lập luồng dữ liệu qua các tầng

Giả sử tại `now_epoch = 1795003787.3`, người dùng mở tuyến `32` chiều đi (`dir_int = 0`) và xem trạm `station_order = 20` (`s_target = 11520.0m`):

1. **`live_feed.py` (`fetch_live_vehicles_for_route`):**
   - Nhận JSON thô từ BusMap (`Lat`, `Lng`, `Speed`, `Deg`, `UpdatedAt`, `VehicleId`, `Plate`).
   - Chuẩn hóa `parse_ping_epoch`, kiểm tra `HANOI_BBOX`, làm tròn `deg` (2 chữ số), `speed` (1 chữ số).
2. **`serving_service.py` (`_sync_route_both_directions` → `_sync_and_merge_timbus`):**
   - Chiếu thô toàn bộ xe BusMap bằng `ShapeProjectionModel.project_point` để lấy `(s_bm, ct_bm)`.
   - Gọi `TimBusClient.query_central_vehicles` (timeout `3s`), lấy tọa độ TimBus, đặt `telemetry_source = "timbus"` và `deg` theo tiếp tuyến đường.
   - Chạy `_prepare_vehicle` → `OnlineFeatureExtractor.project_vehicle` → `RouteHMM.update(...)` để xác định lý trình `s` ổn định trên nhánh tuyến.
   - Chạy `MacroSpeedTracker.observe_and_estimate` để tính `speed_kmh` hiển thị cho UI/traffic status.
3. **`serving_service.py` (`_observe_causal_snapshot` → `CausalFeatures.observe`):**
   - Đẩy `Observation(route_id, direction, vehicle, source, epoch, received, lat, lng, signature)` vào `CausalFeatures` (chạy một bản `RouteHMM(window=128, horizon=360)` **riêng biệt** với `OnlineFeatureExtractor`!).
4. **`serving_service.py` (`get_station_eta`):**
   - Chạy `project_filter_extrapolate` lọc xe quá hạn / lệch hành lang / ngược chiều / đã qua trạm (`s_now > s_target`).
   - Gọi `CausalFeatures.features(...)` sinh vector 36 feature (`ego_speed_avg_3min_kmh`, `lead_bus_*`, `baseline_*`, ...).
   - Gọi `ModelRuntime.predict_p50(features)` → `ResidualETA.predict` → `max(5.0, baseline_eta_p50_sec + residual)`.
   - Gọi `compute_station_eta` tính `delta_buffer`, `optimistic_eta`, `conservative_eta`, `p10/p90`, `traffic_status`.
   - Gọi `compute_proximity_capped_etas` kẹp trần ETA các xe cách nhau `< 120m` và tính lại `compute_station_eta` nếu bị kẹp.
5. **`app.js` (`pollVehicles` → `updateStationFocusCard` / `renderStationPopupEta`):**
   - Nhận JSON từ `/api/live-vehicles` và `/api/station-eta`, đối chiếu `routeGeneration` / `focusRequestId` / `popupRequestId` và cập nhật marker + thẻ hiển thị.

---

## Phần B: Chi tiết từng bước, `if-else`, công thức và Magic Number

### Tầng 1: `live_feed.py` — Lấy dữ liệu BusMap & chuẩn hóa thời gian

1. **`parse_ping_epoch(ts_val, default_epoch)` (`live_feed.py:25-65`)**
   - `if ts_val is None` → trả `default_epoch`.
   - `if isinstance(ts_val, (int, float))`: nếu `epoch > 1e11` → `epoch /= 1000.0` (magic number phân biệt ms vs s), gọi `datetime.fromtimestamp(epoch, tz=TZ_HANOI)`.
   - Nếu là chuỗi số (`float(s)`): cũng kiểm tra `val > 1e11` → chia `1000.0`.
   - Nếu là chuỗi ISO: `s.replace("Z", "+00:00")`, `datetime.fromisoformat`; nếu `dt.tzinfo is None` → gán `TZ_HANOI`.
   - `except Exception: pass` → rơi về `default_epoch`.
   - **Lỗi kỹ thuật / logic:**
     - `isinstance(True, (int, float))` là `True` trong Python → truyền `bool` sẽ trả về epoch `0.0` hoặc `1.0` (năm 1970) thay vì `default_epoch`.
     - `float("1e20")` hoặc số âm/quá lớn không được bọc `try/except (OverflowError, OSError)` quanh `datetime.fromtimestamp(...)` ở dòng `38` và `50`.
     - Nuốt mọi `Exception` ở dòng `61` và trả về `default_epoch` khiến ping lỗi format biến thành "ping mới tinh tại `now_epoch`".

2. **`fetch_live_vehicles_for_route(route_id, direction=0)` (`live_feed.py:72-174`)**
   - `if direction not in (0, 1): direction = 0` (im lặng ép về chiều đi).
   - Kiểm tra `live_cache` (TTL `LIVE_CACHE_TTL_SEC = 8.0s`).
   - `if not raw_items or not isinstance(raw_items, list)`: **vẫn cache response rỗng `[]` trong `8.0s`**.
   - Trong vòng lặp từng xe:
     - `if not vehicle_id or not isinstance(vehicle_id, int) or vehicle_id <= 0: continue`
     - `if vehicle_id in seen_ids: continue` (giữ bản ghi đầu tiên).
     - Kiểm tra `HANOI_BBOX` (`lat ∈ [20.50, 21.40]`, `lng ∈ [105.20, 106.15]`).
     - `if not plate: plate = f"BUS-{vehicle_id}"` (biển số giả).
     - `deg = float(...) % 360.0` (lỗi → `0.0`), `speed = max(0.0, float(...))` (lỗi → `0.0`).
     - `current_station_id` / `next_station_id`: chỉ kiểm tra `<= 0` nếu `isinstance(..., int)` (chuỗi hoặc float lọt qua).
   - **Lỗi kỹ thuật / logic:**
     - `live_cache` là `dict` toàn cục dùng chung giữa nhiều luồng `ThreadPoolExecutor` nhưng **không có lock** và không giới hạn kích thước.
     - Cache luôn cả kết quả lỗi/rỗng từ upstream trong `8s` làm mất dữ liệu tạm thời kéo dài thành `8s`.

---

### Tầng 2: `serving_service.py` — Hợp nhất TimBus & Quản lý trạng thái

1. **`_sync_route_both_directions` (`serving_service.py:472-515`)**
   - Nếu chiều ngược lại (`other_dir = 1 - primary_dir`) cũng hỗ trợ TimBus → chạy song song `ThreadPoolExecutor(max_workers=2)`.
   - `try: fut_other.result() except Exception as e: logger.warning(...)` → nuốt lỗi đồng bộ chiều ngược.

2. **`_collect_bm_proj_and_plates` (`serving_service.py:404-420`)**
   - Chiếu mọi xe BusMap bằng `shape_model.project_point(v.lat, v.lng)` (stateless global nearest!).
   - `if p_norm not in bm_proj or s_bm > bm_proj[p_norm][1]: bm_proj[p_norm] = (v, s_bm, ct_bm)`.
   - **Lỗi logic:** Chọn bản ghi trùng biển số dựa trên `s_bm` lớn nhất mà bỏ qua `updated_at` và `ct_bm` (có thể chọn bản ghi cũ hơn hoặc ở nhánh sai có `s_bm` lớn hơn).

3. **`_sync_and_merge_timbus` (`serving_service.py:517-636`)**
   - Cache TimBus (`TIMBUS_LIVE_CACHE_TTL_SEC = 4.0s`):
     - Nếu `bm_ts > cached_ts and s_bm > cached_s and ct_bm <= MAX_CORRIDOR_CROSS_TRACK_M (35.0m)` → bỏ cache TimBus, không query TimBus và fallback về BusMap.
   - Query TimBus (`timeout_s = max(1, ceil(TIMBUS_QUERY_TIMEOUT_SEC = 2.5)) = 3s`): nếu lỗi → `except Exception` fallback im lặng về `tb_map = {}`.
   - Với mỗi xe TimBus trả về:
     - Chiếu thô `s_tb, ct_tb, seg_idx_tb = shape_model.project_point(...)`.
     - Nếu `ct_tb <= 35.0m`:
       - `tb_ts = float(getattr(tb_rec, "fetch_timestamp", None) or now_epoch)`.
       - Chạy `_prepare_vehicle(...)` (chiếu lại bằng `RouteHMM`). Nếu `tb_dto.matched_projection is None` → **`continue` (bỏ qua luôn cả Tier 2 hold!)**.
       - So sánh `bm_ahead_newer = bm_ping_epoch > tb_ts and s_bm > s_tb and ct_bm <= 35.0`. Nếu `not bm_ahead_newer` → lưu `_tb_last_valid` và dùng TimBus.
   - Tier 2 Monotonicity Guard (`617-623`): Nếu TimBus không có hoặc bị loại, kiểm tra cache trong `TIMBUS_HOLD_FRESH_SEC (20.0s)`: `if within_limit and s_bm < last_s_tb: dùng lại last_dto`.
   - **Lỗi logic nghiêm trọng:**
     - **So sánh lệch hệ tọa độ (`s_bm` vs `s_tb`):** `s_bm` đến từ `project_point` toàn cục (không có lịch sử HMM), còn `s_tb` / `last_s_tb` đến từ `RouteHMM`! Trên tuyến có nhánh lặp/giao cắt, `s_bm` nhảy nhánh sai sẽ kích hoạt nhầm `bm_ahead_newer` hoặc phá hỏng Tier 2 hold.
     - **Lỗ hổng ở dòng `598-599`:** Khi `ct_tb <= 35.0m` nhưng `RouteHMM` từ chối (`matched_projection is None`), lệnh `continue` nhảy thẳng qua khối Tier 2 (`617-623`), làm mất cơ chế giữ vị trí `20s` đáng lẽ phải dùng.

4. **`_prepare_vehicle` (`serving_service.py:284-299`)**
   - `key = (route_id, plate)` (**không có `dir_int`**!).
   - Khi `vehicle.projection_generation != previous`: xóa `_speed_tracker`, `_tb_last_valid`, `_passed_station_plates` cho mọi chiều của `(route_id, plate)`.
   - **Lỗi logic:** Nếu đồng bộ song song 2 chiều (`_sync_route_both_directions`) hoặc có xe `plate == ""` (collision vào `(route_id, "")`), hai chiều/hai xe có thể xóa sạch cache của nhau.

5. **`_filter_station_vehicles` & `_is_recently_passed_locked` (`serving_service.py:638-685`)**
   - Loại xe nếu `matched_projection is None`, `cross_track > 35.0m`, hoặc `s_cur > s_target` (ghi vào `_passed_station_plates` với TTL `PASSED_STATION_TTL_SEC = 180.0s`).
   - Chỉ reset trạng thái đã qua trạm khi quá `180s` hoặc `s_cur < s_target - PASSED_NEW_TRIP_RESET_M (150.0m)`.

---

### Tầng 3: `route_matcher.py` — Chiếu Frenet & `RouteHMM`

1. **`ShapeProjectionModel` (`route_matcher.py:13-105`)**
   - Hệ số quy đổi phẳng cục bộ: `kx = 111320.0 * cos(mean_lat)`, `ky = 110540.0`.
   - `safe_lens_sq = np.maximum(seg_lens_sq, 1e-6)`; `t = np.clip(..., 0.0, 1.0)`; `best_s` làm tròn `0.1m`.
   - `segment_unit_tangent`: nếu `seg_len < 1e-9` → trả về hướng Đông `(1.0, 0.0)`.
   - **Lỗi kỹ thuật:** Nếu `build` nhận `< 2` điểm, `project_point` văng `ValueError` ở `np.argmin` và `segment_unit_tangent` văng `IndexError`.

2. **`RouteHMM` (`route_matcher.py:122-219`)**
   - Mặc định: `sigma = 15.0m`, `max_candidates = 10`, `window = 24`, `horizon = 120.0s` (nhưng `CausalFeatures` truyền `window = 128, horizon = 360`).
   - `candidates`: lọc `d <= 35.0m` (`MAX_CORRIDOR_CROSS_TRACK_M`), khử trùng trong bán kính **`10m`** dọc theo `s`, lấy tối đa 10 ứng viên.
   - `update`:
     - Cổng `awaiting_direction`: chặn tối đa `STALE_DELTA_T_MAX_SEC (300.0s)` rồi mới tự mở khóa.
     - Trùng / trễ epoch (`epoch <= last[0]`): trả về điểm cuối `best_path[-1]`.
     - Emission: `-0.5 * (cross_track / 15.0)^2`. Nếu tọa độ giống hệt bước trước (`lat == old[1] and lng == old[2]`) → **`emission[:] = 0`** (làm mất độ ưu tiên cross-track giữa các ứng viên trên bước đứng yên!). Nếu `dt <= 30s` và `move >= 15.0m` → phạt hướng lệch `2 * (1 - cos_heading)` (magic number `30`, `2`).
     - Khởi tạo hoặc đứt quãng (`dt > 300.0s`): reset chuỗi Viterbi.
     - Chuyển tiếp `terminal` (`total_len > 1000` & `a.s >= total_len - 800` & `b.s <= 800`): `distance = total_len - a.s + b.s`, `penalty = 4.0` (magic number `1000`, `4.0`). **Lỗi logic:** Ở tuyến ngắn (`1000 < total_len <= 1600`), hai vùng `>= total_len - 800` và `<= 800` chồng lấn lên nhau, nên dù xe chạy tiến (`b.s >= a.s`) vẫn có thể kích hoạt nhánh `terminal` nếu không kiểm tra `b.s < a.s`!
     - Lùi GPS (`-20.0m <= ds < 0`): `distance = 0`, `penalty = -ds / 15.0`.
     - Cổng tốc độ: `distance > dt * 22.222 + 45.0` (`FRENET_MAX_SPEED_MPS = 80 km/h` + `3*sigma`) → `-inf`.
     - Nếu không có chuyển tiếp hợp lệ (`no_feasible_transition`) gần đầu/cuối tuyến (`<= 800m`) và `nearest.s < prior.s - 20.0` và `move >= 8m` (magic number `8`, `count >= 2`) → kích hoạt `direction_change_pending` (khóa `300s`).

---

### Tầng 4: `MacroSpeedTracker` (`serving_service.py:106-247`) — Vận tốc hiển thị

- Cửa sổ mục tiêu: `MACRO_SPEED_MIN_DT_SEC (120s)` đến `MACRO_SPEED_MAX_DT_SEC (240s)`.
- `_trim_leading_dwell`: cắt phần đứng yên đầu chuỗi nếu `dwell_dt >= 30.0s` và `s_bus - s_dwell >= 25.0m` (`TERMINAL_STATIONARY_TOL_M` dùng kiểm tra đứng yên).
- **Magic numbers & ép logic:**
  - Nếu chưa đủ `30s` lịch sử và `bm_speed_kmh > 0` → ghi đè `seed = bm_speed_kmh` (`206-207`).
  - Nếu `used_dt < 15.0s` → trả thẳng `seed` (`233-234`); nếu `15s <= used_dt < 120s` → trộn tuyến tính `weight = used_dt / 120.0` giữa `v_partial` và `seed` (`236-238`).
  - Lọc EMA với `MACRO_SPEED_EMA_ALPHA`, kẹp trần `GPS_DRIFT_MAX_SPEED_KMPH`.
  - **Hệ quả:** `v.speed_kmh` hiển thị cho người dùng và đưa vào `traffic_status` là tốc độ **vĩ mô 2–4 phút + EMA + seed BusMap**, hoàn toàn khác với `ego_speed_avg_3min_kmh` / `5min_kmh` của model ML.

---

### Tầng 5: `causal_eta.py` — `CausalFeatures` (Trích xuất 36 feature)

1. **`observe()` (`causal_eta.py:89-150`):**
   - Kiểm tra hợp lệ (`source in ('busmap','timbus')`, tọa độ hữu hạn khác `(0,0)`, `epoch <= received`, `received - epoch <= MAX_POSITION_AGE (90.0s)`).
   - Khử trùng theo `fingerprint_key`: TimBus bị loại nếu `epoch <= prev.epoch` **hoặc** `signature == prev.signature` (signature = `lat:.5f,lng:.5f,round(raw_spd,1)`).
   - **Magic number `8s` (`129-132`):** Nếu ping nguồn khác đến trong vòng `<= 8s` cùng `(lat, lng)` → loại.
   - Giữ lịch sử `observations` trong `390s` (`149`, magic number).
   - Nếu `RouteHMM.resets` tăng → tăng `journey`, xóa sạch `observations` (cold-start lại toàn bộ tốc độ!).
   - **Lỗi kiến trúc:** `serving_service.py` chạy **2 bản `RouteHMM` song song** (`OnlineFeatureExtractor` với `window` mặc định vs `CausalFeatures` với `window=128, horizon=360`) trên cùng 1 xe, dễ lệch nhẹ `s` hoặc thời điểm reset giữa projection hiển thị và projection đưa vào ML.

2. **`speed(state, seconds)` (`causal_eta.py:155-181`):**
   - Dùng cho `ego` (`180s`, `300s`) và `lead` / `follow` (`180s`).
   - Nếu `end.epoch - state.started < seconds` → lấy từ `points[0]` (partial window), miễn `duration >= MIN_SPEED_WINDOW (30.0s)`. Nếu đã chạy lâu hơn `seconds` mà điểm gần nhất lệch quá `WINDOW_TOLERANCE (30.0s)` → trả `None`.
   - Chặn đứt quãng giữa 2 ping: `MAX_GAP = 120.0s`.
   - **Điểm gây lỗi đèn đỏ (`173-174`):** `if abs(distance) <= STATIONARY_TOLERANCE_M (15.0) and max(p.s) - min(p.s) <= 15.0: distance = 0.0` → **ép cứng vận tốc về `0.0 km/h`**.
   - Nếu `distance < 0` → `None`; `kmh > 80` → `None` (magic number `80`).

3. **`_fleet()` & `_lead_ratio()` (`causal_eta.py:241-275`):**
   - Chỉ nhận xe khác nếu `|now - other.last_epoch| <= 90.0s` và `|state.last_epoch - other.last_epoch| <= MAX_FLEET_SKEW (45.0s)`.
   - **Điểm gây nhảy `±150s` (`255-256`):** Ngưỡng cắt cứng `d > 20` và `d < -20` chọn duy nhất `ahead[0]` và `behind[0]` (không kiểm tra `s_other <= target_s`, không hysteresis).
   - **Điểm gây nhảy `+92..+100s` (`261-275`):** `_lead_ratio()` trả về `expected_baseline / speed.seconds`; khi `lead` mới qua `30s` ở trạng thái bò `1–2m`, tỷ số rơi xuống `~0.008` (không chặn sàn, không gắn monotone constraint).

---

### Tầng 6: `model_runtime.py`, `ResidualETA`, `eta_policy.py` & `Proximity Cap`

1. **`ModelRuntime.predict_p50` (`model_runtime.py:82-105`) & `ResidualETA.predict` (`causal_eta_training.py:163-178`):**
   - `int(r_idx)` ở dòng `87` nằm **ngoài** khối `try/except` (nếu non-numeric sẽ crash thay vì fallback).
   - Khối `try/except Exception` (dòng `103-105`) nuốt mọi lỗi suy luận/trace và âm thầm trả `None` (fallback sang `baseline`).
   - `ResidualETA.predict`: kẹp sàn `max(5.0, baseline_eta_p50_sec + residual)`.

2. **`project_filter_extrapolate` (`eta_policy.py:61-101`):**
   - `delta_t_age > MAX_TELEMETRY_STALE_SEC (300.0s)` → loại.
   - `d_perp > 35.0m` → loại.
   - Nếu `speed_kmh >= HEADING_MIN_SPEED_KMPH` và `deg is not None` và `cos < HEADING_COS_SIMILARITY_MIN` → loại.
   - `s_now > s_target` → loại (không dead-reckoning).

3. **`compute_station_eta` (`eta_policy.py:123-258`):**
   - Tính `base_rem_p10/p50/p90` và `sigma_accum` bằng nội suy tuyến tính `rho = (station_s[k+1] - s_now) / l_k` trên đoạn đầu + cộng dồn các đoạn sau.
   - **Lỗi logic / gượng ép:**
     - **Buffer đối xứng đội lốt LINEX (`187-194`):** `optimistic_eta = max(0, eta_core - delta_buffer)` và `conservative_eta = eta_core + delta_buffer` dùng **cùng một `delta_buffer`**, không hề bất đối xứng.
     - **Hard-code heartbeat `15s` (`188`):** `BUFFER_BETA_TELEMETRY * TELEMETRY_HEARTBEAT_SEC` luôn tính `0.5 * 15.0 = 7.5s` kể cả khi nguồn là `TimBus 5s`.
     - **Báo tắc sai khi dừng đèn đỏ (`203`):** `if v_obs_kmh < 10.0 or is_delayed: traffic_status = "UN_TAC"` — xe đứng trạm/đèn đỏ đúng giờ (`delta_delay == 0`) vẫn bị gắn nhãn `"UN_TAC"`.
     - **Mất đối xứng `p10/p90` (`210-211`):** `p90` dịch theo `delta_delay`, còn `p10 = min(base_rem_p10, eta_core)` có thể co thành `p10 == p50` khi `eta_core < base_rem_p10`.
     - **Quantization `ceil` (`197-199`):** Mọi `0 < eta_core <= 60s` đều thành `1` (`"~1 phút"`), khiến `"0 phút"` không bao giờ xuất hiện khi xe sắp tới nơi.

4. **`compute_proximity_capped_etas` (`serving_service.py:65-102`):**
   - Kẹp `behind <= ahead + gap / 2.5 + 15.0` (chuyển tiếp mượt `80..120m`). Giải quyết tốt triệu chứng 2 xe gần nhau, nhưng là chốt chặn ở ngọn (không xử lý được lỗi gốc ở `ahead`).

---

### Tầng 7: `app.js` — Polling & Hiển thị Client

1. **Quản lý chu kỳ & request race:**
   - `routeTimbusMap` khởi tạo `5s` (`TIMBUS_POLL_MS`) ngay khi chọn tuyến hỗ trợ TimBus; `routeGeneration`, `focusRequestId`, `popupRequestId` chặn response cũ ghi đè UI.
2. **Các lỗi logic / che giấu lỗi còn tồn tại trong `app.js`:**
   - **`syncStationFastPolling` chỉ lên không xuống (`524-529, 980`):** Nếu một chiều không hỗ trợ TimBus, `syncStationFastPolling` không hạ về `15s`; gọi `syncStationFastPolling(null)` ở dòng `980` là vô tác dụng; `refreshOpenPopupEta` (`489-506`) không gọi `syncStationFastPolling`.
   - **Im lặng nuốt lỗi HTTP/mạng ở ETA trạm (`497, 503-505, 553, 558-560`):** `if (!res.ok) return;` khiến UI giữ nguyên số ETA cũ mà không báo lỗi/stale cho người dùng.
   - **Giữ marker cũ khi mất kết nối (`879-881, 905-909`):** `pollVehicles` lỗi chỉ đổi chữ sang `'Mất kết nối GPS'` nhưng giữ nguyên marker cũ trên bản đồ.
   - **`catch (e) {}` rỗng (`224`):** nuốt im lỗi parse `updated_at`.
   - **Truy cập `bus.safe_window.*` không kiểm tra null (`564-565, 603-611`):** sẽ văng lỗi nếu backend trả `safe_window` thiếu/null.
   - **Lệch đồng hồ client vs server (`437-467`):** `updateLiveGpsAge()` tính tuổi bằng `Date.now() - new Date(ping_time)` trên máy khách, dễ lệch với `ping_age_seconds` của server nếu đồng hồ máy người dùng sai giờ.
   - **Hard-code `'traffic-ok'` (`229`):** Dòng `"Vận tốc ổn định:"` luôn gắn class xanh `traffic-ok` bất kể xe đang bò `2 km/h`.

---

## Phần C: Bảng tổng hợp các lỗi logic ưu tiên cao cần thống nhất trước khi sửa ML

| Mức độ | Vị trí | Vấn đề cốt lõi | Tác động thực tế |
|---|---|---|---|
| **Cao** | `causal_eta.py:173-174` + model | Ép `distance <= 15m` thành `0.0 km/h` + nhánh `ego_speed == 0` thiếu `dwell_elapsed` | Dừng đèn đỏ ở `200m` cuối làm ETA vọt `+81.3s` (`38.8s -> 120.1s`, gấp 3.1x) |
| **Cao** | `causal_eta.py:255-275` | Ngưỡng cắt cứng `d > 20m` chọn `ahead[0]` + `lead_bus_speed_ratio` không monotone | Nhảy `±150s` khi vượt nhau và `+92..+100s` lúc warm-up `None -> ~0.008` |
| **Cao** | `serving_service.py:415,549,608,622` | Trộn `s_bm` (chiếu thô toàn cục) với `s_tb` (`RouteHMM`) để quyết định chọn/giữ TimBus | Có thể chọn sai nhánh trên tuyến vòng/giao cắt và bypass Tier 2 hold |
| **Trung bình** | `serving_service.py:286-298` | `_prepare_vehicle` dùng key `(route_id, plate)` thiếu `dir_int` và xóa cache cả 2 chiều | Đồng bộ 2 chiều hoặc xe thiếu biển số (`""`) có thể xóa state của nhau |
| **Trung bình** | `serving_service.py:598-599` | `continue` khi `RouteHMM` từ chối bản ghi TimBus làm bỏ qua luôn Tier 2 hold `20s` | Tụt về BusMap thô dù còn cache TimBus tươi |
| **Trung bình** | `causal_eta.py` vs `online_features.py` | Chạy 2 instance `RouteHMM` độc lập với tham số `window/horizon` khác nhau | Lý trình `s` và thời điểm reset có thể lệch giữa UI và ML |
| **Trung bình** | `eta_policy.py:187-211` | Buffer đối xứng dù ghi LINEX, heartbeat hard-code `15s`, `v < 10` luôn báo `UN_TAC` | Dừng đèn đỏ đúng giờ vẫn bị gắn nhãn `"UN_TAC"`; buffer không phản ánh TimBus `5s` |
| **Thấp** | `live_feed.py` & `app.js` | Cache lỗi rỗng `8s`, `bool` lọt `parse_ping_epoch`, `app.js` giữ số/marker cũ khi lỗi HTTP | Che giấu trạng thái mất kết nối hoặc hiển thị số cũ trên UI |

---

## Phần D: Phản biện & Tái phân loại (Lỗi thật vs. Thỏa hiệp vs. Logic bắt buộc)

Khi xét lại từng điểm theo **đặc trưng thông tin sẵn có ở từng giai đoạn**, nhiều điểm nhìn tưởng là "lỗi code" thực chất là **thỏa hiệp kỹ thuật** hoặc **logic bắt buộc**:

### 1. Những điểm thực chất là **Thỏa hiệp** hoặc **Logic bắt buộc** (không nên sửa vội)

1. **Chạy 2 `RouteHMM` song song (`OnlineFeatureExtractor` vs `CausalFeatures`):**
   - **Bản chất:** **Thỏa hiệp bảo toàn Train–Serve Parity.** `CausalFeatures` bắt buộc phải giữ `RouteHMM(window=128, horizon=360)` đồng nhất 100% với `TrainingReplay` (BusMap `15s`) để không làm lệch phân phối 36 feature đầu vào của XGBoost; trong khi tầng serving/UI cần cập nhật linh hoạt ở nhịp `5s` TimBus.
2. **Dùng `project_point` toàn cục trong `_collect_bm_proj_and_plates` trước khi đưa vào `RouteHMM`:**
   - **Bản chất:** **Logic bắt buộc ở bước tiền xử lý.** Ở thời điểm gom danh sách BusMap để quyết định có gọi/chọn TimBus hay không, chưa thể đẩy tọa độ BusMap vào `RouteHMM` stateful (nếu đẩy vào rồi sau đó chọn TimBus thì trạng thái HMM bị trộn 2 nguồn nhảy qua lại). Đây là giới hạn thông tin bắt buộc phải chịu trừ khi tạo thêm HMM read-only chỉ để so sánh.
3. **Quantization `math.ceil` không bao giờ ra `"0 phút"` (`0 < eta <= 60s` → `"~1 phút"`):**
   - **Bản chất:** **Logic bắt buộc vì an toàn UX** (nhất quán với chủ trương bỏ `ARRIVING_NOW` ở Spec 24 cũ). Khi xe còn `10–50s`, hiển thị `"0 phút"` dễ khiến hành khách hiểu nhầm xe đã đỗ trước mặt và bỏ lỡ chuyến; `"~1 phút"` an toàn hơn.
4. **`v_obs_kmh < 10.0` gán `"UN_TAC"` trong `eta_policy.py:203`:**
   - **Bản chất:** **Thỏa hiệp chấp nhận được (chứ không ngây ngô như nhìn thoáng qua).** `v_obs_kmh` đi vào `eta_policy.py` không phải tốc độ tức thời mà là đầu ra của `MacroSpeedTracker` (`120–240s` + EMA + `_trim_leading_dwell`). Nhờ cửa sổ 2–4 phút, xe dừng đèn đỏ ngắn hạn `30–45s` thường vẫn giữ `v_obs_kmh >= 10 km/h`, chỉ khi kẹt/bò kéo dài nhiều phút mới tụt xuống `< 10 km/h`. Điểm yếu chỉ xảy ra ở tuyến vốn chạy chậm `~9 km/h` giờ cao điểm nhưng vẫn đúng baseline (`delta_delay == 0`).
5. **Giữ nguyên marker cũ trên bản đồ khi `pollVehicles()` rớt 1 nhịp HTTP (`app.js:879-909`):**
   - **Bản chất:** **Thỏa hiệp UX hợp lý.** Nếu vừa rớt 1 gói `5s` đã xóa sạch marker xe thì bản đồ sẽ nhấp nháy trắng rất khó chịu; giữ marker kèm chữ `"Mất kết nối GPS"` tốt hơn (chỉ nên bổ sung nhãn *"cũ/stale"* cho thẻ ETA nếu lỗi kéo dài nhiều nhịp liên tiếp).
6. **`_prepare_vehicle` xóa cache khi `projection_generation` đổi (`serving_service.py:289-298`):**
   - **Bản chất:** **Logic bắt buộc** để không mang `passed_station_plates` và `MacroSpeedTracker` của chuyến cũ sang chuyến mới sau khi xe quay đầu bến (`terminal_reset`). Chỉ có phần thiếu `dir_int` trong key là lỗi biên cần vá nhẹ.
7. **Ép `distance <= 15m` thành `0.0 km/h` trong `causal_eta.py:173-174`:**
   - **Bản chất:** Xuất phát từ **thỏa hiệp chống nhiễu GPS đứng yên** (xe đỗ bến dao động `±5..12m` nếu không cắt sẽ ra tốc độ ảo `0.5–1.5 km/h`). Tuy nhiên khi đi cùng mô hình D6 thiếu `dwell_elapsed`, nó kích hoạt tác dụng phụ `+81.3s` ở `rem = 206m`.

---

### 2. Những điểm thực sự là **Lỗi kỹ thuật / Lỗi logic** (xếp hạng ưu tiên P0 → P3)

| Ưu tiên | Vị trí chính xác | Tên lỗi | Tóm tắt tác động |
|---|---|---|---|
| **P0** | `causal_eta.py:173-174` + Model | Vọt ETA khi dừng đèn đỏ gần trạm | `rem = 206m`: `38.8s -> 120.1s` (`+210%`) khi tụt về `0.0 km/h` |
| **P1** | `causal_eta.py:255-275` | Cụm `lead_bus` ngưỡng cứng `20m` + `lead_bus_speed_ratio` | Nhảy `±150s` lúc vượt nhau và `+92..+100s` lúc warm-up |
| **P1** | `live_feed.py:34-52, 69, 95-100` | Cache rỗng `8s`, thiếu lock, `parse_ping_epoch` (`bool` / `OverflowError`) | Mất xe toàn tuyến 8s khi API chập chờn; nguy cơ race condition |
| **P2** | `route_matcher.py:174` | Điều kiện `terminal` wrap sai trên tuyến ngắn `1000..1600m` | Xe chạy tiến bình thường bị tính nhầm thành nhảy vòng terminal |
| **P2** | `serving_service.py:286-298` & `model_runtime.py:87` | Key `(route_id, plate)` thiếu `dir_int` & `int(r_idx)` ngoài `try` | Va chạm xe không biển số `""`; crash nếu `route_id_idx` lỗi kiểu |
| **P3** | `app.js:229, 564-565` | Hard-code `traffic-ok` và thiếu null-guard `bus.safe_window` | Dễ crash UI nếu `safe_window` null; class trạng thái gây hiểu nhầm |

#### Phân tích chi tiết từng lỗi theo thứ tự ưu tiên

1. **[P0] Vọt ETA khi dừng đèn đỏ ở cự ly gần (`causal_eta.py:173-174` + Spec 42)**
   - **Cơ chế lỗi:** Khi xe đứng yên/nhích `< STATIONARY_TOLERANCE_M (15.0m)` trong cửa sổ tốc độ, `distance` bị ép thành `0.0` → `ego_speed_avg_3min_kmh = 0.0`. Do model thiếu `dwell_elapsed` (đã dừng đèn đỏ bao lâu), tại `rem = 206m` nhánh `0.0 km/h` cộng vọt `+81.3s` (`38.8s -> 120.1s`), rồi sập ngược `-80s` khi đèn xanh.
   - **Hướng sửa:** Xem Spec 42 (làm mượt vùng tốc độ gần `0`, bổ sung/xử lý `dwell_elapsed`, đánh giá lại trên `4,000,961` dòng test).

2. **[P1] Cụm `lead_bus` / `follow_bus` ngưỡng cứng `20m` & `lead_bus_speed_ratio` (`causal_eta.py:255-275`)**
   - **Cơ chế lỗi:** `d > 20` / `d < -20` chọn duy nhất `ahead[0]` / `behind[0]` gây nhảy `±150s` khi vượt nhau; `lead_bus_speed_ratio` không có monotone constraint gây nhảy `+92..+100s` khi vừa qua `30s` warm-up (`None -> ~0.008`).
   - **Hướng sửa:** Giai đoạn 1 (`compute_proximity_capped_etas`) đã chặn tạm ở serving; Giai đoạn 2 sửa khi retrain (thêm tốc độ hành lang phía trước tới `target_s` + gắn `MONOTONE_SPEED_FEATURES = -1` cho `lead_bus_speed_ratio`).

3. **[P1] Lỗi cache & parse timestamp trong `live_feed.py` (`live_feed.py:34-52, 69, 95-100`)**
   - **Cơ chế lỗi:**
     - Dòng `95-100`: Khi `fetch_route_buses_live` thất bại trả `None`/`[]`, code vẫn ghi `empty_res` vào `live_cache` với TTL `LIVE_CACHE_TTL_SEC = 8.0s` (negative caching cho lỗi mạng).
     - Dòng `69, 86, 99`: `live_cache` là `dict` dùng chung giữa các luồng `ThreadPoolExecutor` không có `threading.Lock`.
     - Dòng `34, 38, 50`: `isinstance(True, (int, float))` là `True` nên `bool` trả về epoch `1970`; giá trị số cực lớn (`float("1e20")`) không được bọc `OverflowError`/`OSError` quanh `datetime.fromtimestamp(...)`.
   - **Hướng sửa:** Không cache `empty_res` khi upstream lỗi (hoặc TTL cực ngắn); thêm `Lock` quanh `live_cache`; chặn `isinstance(ts_val, bool)` và bọc `(ValueError, OverflowError, OSError)`.

4. **[P2] Điều kiện `terminal` wrap trên tuyến ngắn `1000 < total_len <= 1600m` (`route_matcher.py:174`)**
   - **Cơ chế lỗi:** `terminal = (total_len > 1000 and a.s >= total_len - 800 and b.s <= 800)` (trong khi dòng `189` kiểm tra thêm `b.s < a.s - 20`). Nếu tuyến dài `1400m` (`total_len - 800 = 600`), xe chạy **tiến** từ `a.s = 650m` → `b.s = 750m` (`ds = +100m`) vẫn thỏa điều kiện `terminal`, bị tính nhầm `distance = 1400 - 650 + 750 = 1500m` và phạt `penalty = 4.0` (dễ bị loại bởi cổng tốc độ!).
   - **Hướng sửa:** Thêm điều kiện `and b.s < a.s - MAX_GPS_BACKWARD_JITTER_M` ngay ở dòng `174` cho đồng bộ với dòng `189`.

5. **[P2] Key `(route_id, plate)` thiếu `dir_int` & `int(r_idx)` ngoài `try` (`serving_service.py:286-298`, `model_runtime.py:87`)**
   - **Cơ chế lỗi:**
     - `serving_service.py:286-298`: Nếu `plate == ""` (xe thiếu biển số), mọi xe không biển số trên cùng tuyến dùng chung key `(route_id, "")` và xóa cache lẫn nhau khi `projection_generation` đổi.
     - `model_runtime.py:87`: `int(r_idx)` nằm ngoài `try/except` (`89-105`), nếu `r_idx` không phải số sẽ raise exception thay vì fallback baseline.
   - **Hướng sửa:** Dùng `TimBusClient.normalize_plate(vehicle.plate) or f"id:{vehicle.id}"` (giống `_observe_causal_snapshot:312`) và đưa `int(r_idx)` vào trong khối `try`.

6. **[P3] Lỗi hiển thị & phòng thủ ở `app.js` (`app.js:229, 564-565`)**
   - **Cơ chế lỗi:** Dòng `229` gắn cứng `valClass: 'traffic-ok'` cho `"Vận tốc ổn định:"` bất kể tốc độ; dòng `564-565` truy cập thẳng `bus.safe_window.*` không kiểm tra null (dễ crash render nếu `safe_window` thiếu).
   - **Hướng sửa:** Bỏ `valClass: 'traffic-ok'` cứng (hoặc tính theo tốc độ) và thêm guard `const sw = bus.safe_window || {};`.

