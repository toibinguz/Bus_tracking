# VĂN BẢN BÀN GIAO CÔNG VIỆC: KIỂM TOÁN CRAWLER TUYẾN 40 & HUẤN LUYỆN MÔ HÌNH ML ETA ĐA TUYẾN (BƯỚC 3.3 – 3.4)
> **Mã tài liệu**: `docs/05_SESSION_HANDOVER_STEP_3_4_AND_CRAWLER_AUDIT.md`  
> **Thời điểm bàn giao**: `2026-11-07 19:56:00+07:00`  
> **Căn cứ pháp lý**: Tuân thủ [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md), [03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md](file:///z:/Desktop/Bus_tracking/docs/03_SILVER_TRAJECTORY_CONTINUITY_AND_ETA_CHECKLIST.md) và [04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md](file:///z:/Desktop/Bus_tracking/docs/04_TECHNICAL_DEBT_AND_OPEN_ISSUES_LEDGER.md).

---

## 1. TỔNG QUAN TRẠNG THÁI HỆ THỐNG HIỆN TẠI (SYSTEM STATE SNAPSHOT)

| Tầng Kiến Trúc | Trạng Thái | Vị Trí Lưu Trữ Chính Tắc | Chỉ Số Thực Nghiệm Đã Nghiệm Thu |
| :--- | :---: | :--- | :--- |
| **1. Silver Telemetry & Incidents** | **HOÀN TẤT (100%)** | `data/lakehouse/silver/route_projected_telemetry/`<br>`data/lakehouse/silver/fact_route_tomtom_incidents/` | **`5.565.232` dòng** (`1.191` phân vùng Parquet, `48` tuyến, `2026-10-08 .. 2026-11-07`), `0` bản tin lệch $>35\text{m}$, `0` lỗi nhảy lùi giữa tuyến (`TD-01`..`TD-08`). |
| **2. Step 3.1/3.2: Historical Baseline Matrix** | **HOÀN TẤT (100%)** | Bảng `agg_segment_travel_times` trong `data/hanoi_bus_system.db`<br>Code: [`baseline_matrix_builder.py`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_matrix_builder.py) | **3 mức `day_type` (`0=T2..T6`, `1=T7`, `2=CN`) × 17 khung giờ (`05..21`)** trên hành lang nội tuyến (`1 <= station_order <= N-1`): **`169.830` ô**, **`Tier 0 = 85,6%` (`Tier 0 + Tier 1 = 93,8%`)**, `Tier 3 = 1,6%` (`0,00%` lượt Test rơi vào `Tier 3`, `99,77%` rơi vào `Tier 0/1`) (`TD-09`..`TD-11`, `TD-18`, `TD-19`). |
| **3. Step 3.3: Unified Gold Feature Store** | **HOÀN TẤT (100%)** | `data/lakehouse/gold/eta_feature_store/split={train,test}/`<br>Code: [`feature_store_builder.py`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py) | **`15.069.481` dòng × `60` cột** (`11.364.661` Train trên `48` tuyến + `3.704.820` Test trên `47` tuyến; `1,29 GB` Snappy Parquet; `0` giá trị `NaN`). Tốc độ tạo: **`267,52s`** bằng 8 nhân song song + mảng cộng dồn $O(1)$ (`TD-20`). |
| **4. Step 3.4: Multi-Route ML ETA Models** | **ĐÃ CHẠY & NGHIỆM THU VÒNG 1** | `data/models/eta_xgb_global_full_54feat.json`<br>`data/models/eta_xgb_global_pruned.json`<br>`data/models/eta_xgb_metadata_and_calibrator.json`<br>Code: [`eta_model_trainer.py`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py) | Đánh giá trên toàn bộ **`3.704.820` mẫu Test**: **`47/47` tuyến đều giảm sai số so với Baseline**. Mô hình **`6_XGB_Pruned_47Feat`** giảm `MAE` tổng thể từ **`114,98s` $\to$ `97,14s` (`-15,5%`)**, `RMSE` từ **`214,61s` $\to$ `173,30s` (`-19,2%`)**, và ở tầm xa `> 15` trạm giảm `MAE` từ **`246,84s` $\to$ `200,90s` (`-45,94s / -18,6%`)** (`TD-22`). |

---

## 2. KẾT QUẢ ĐIỀU TRA PHÁP Y TUYẾN 40 TRONG CRAWLER (`TD-21`)
> **Script kiểm chứng thực nghiệm**: [`experiments/audit_route_40_crawler.py`](file:///z:/Desktop/Bus_tracking/experiments/audit_route_40_crawler.py)

### 2.1. Kết luận: Đây là lỗi kết hợp giữa (1) Hệ thống BusMap đổi dải ID xe của Tuyến 40 và (2) Ba lỗi logic trong [`catalog_refresher.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py) của ta
1. **Phía hệ thống BusMap (Upstream Re-ID)**:
   - Trong [`data/metadata/hust_cluster_config.json`](file:///z:/Desktop/Bus_tracking/data/metadata/hust_cluster_config.json), Tuyến `40` (`route_id = 40`, `Công viên Thống Nhất - Văn Lâm`) được cấu hình 7 mã xe 6 chữ số cũ: `[232707, 232708, 232710, 232712, 232715, 232719, 232721]` (biển số `29B-202.xx / 29B-204.xx`).
   - Từ `2026-10-31`, cả 7 xe này đỗ cố định tại bãi `(lat=21.0004, lng=105.8655)` với `direction = -1, Speed = 0`, và ngừng cập nhật `lastUpdateTime` vĩnh viễn từ **`2026-11-02T09:34:39+07:00`** (khiến bộ lọc Silver loại bỏ hoàn toàn sau ngày `31/10`).
   - Khi quét trực tiếp API BusMap (`search_vehicles_by_query("29B14")`, `"29B19"`), Tuyến 40 **vẫn đang chạy bình thường** nhưng đã được BusMap cấp sang **dải mã xe 7 chữ số mới**:
     - `8836674` (`29B-148.62`, `routeId=40`, `Speed=35 km/h`, `lastUpdateTime=2026-11-07T19:43:54+07:00`)
     - `8836680` (`29B-190.63`, `routeId=40`, `Speed=0 km/h`, `lastUpdateTime=2026-11-07T19:44:22+07:00`)
     - `8836704` (`29B-193.01`, `routeId=40`, `Speed=1 km/h`, `lastUpdateTime=2026-11-07T19:44:23+07:00`)
2. **Phía hệ thống Crawler của ta (3 lỗi trong `catalog_refresher.py` khiến cơ chế tự phục hồi 05:00 sáng không phát hiện và thay thế được xe chết)**:
   - **Lỗi A (Thiếu hàm entrypoint trong `scripts/daily_catalog_refresh.py`)**: Trước phiên hôm nay, `cloud_crawler_runner.py` gọi `from scripts.daily_catalog_refresh import run_daily_catalog_refresh`, nhưng file này không có hàm `run_daily_catalog_refresh` nên văng `ImportError` mỗi sáng lúc 05:00 từ `2026-10-20` (đã vá wrapper `scripts/daily_catalog_refresh.py` trong phiên hôm nay).
   - **Lỗi B (Logic `audit_vehicle` trong [`catalog_refresher.py` dòng 48–54 & 126](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py#L48-L126))**:
     - Hàm `audit_vehicle` chỉ kiểm tra `if route_id <= 0 or (direction == 0 and speed == 0): status = "DEPOT" else: status = "ACTIVE"`. Do 7 xe chết của Tuyến 40 trả về `RouteId = 40, direction = -1, Speed = 0` và `lastUpdateTime` đóng băng từ 5 ngày trước, `audit_vehicle` vẫn gán nhãn cả 7 xe là `"ACTIVE"`!
     - Hơn nữa, ở dòng 126: `if res["route_id"] == int(r_id) and res["status"] in ("ACTIVE", "DEPOT"): active_on_route += 1` gộp luôn cả `"DEPOT"` vào `active_on_route`, làm `active_on_route = 7 >= 6` nên **Phase 2 (quét tìm xe mới bổ sung)** không bao giờ được kích hoạt!
   - **Lỗi C (Logic Phase 2 tìm xe mới trong [`catalog_refresher.py` dòng 129–157](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py#L129-L157))**:
     - Gọi `search_vehicles_by_query(route_no)` (tìm chuỗi `"40"` trong biển số xe thay vì tìm theo tuyến hoặc quét tiền tố biển số `29B10..29B35`, `29F00..29F09`).
     - Đọc nhầm khóa JSON PascalCase (`v.get("VehicleId")`, `v.get("RouteId")`, `v.get("VehicleNumber")`) trong khi API `vehicles/find` trả về camelCase (`id`, `routeId`, `title`)!

---

## 3. KẾT QUẢ THỰC NGHIỆM BƯỚC 3.4: ĐÁNH GIÁ 7 MÔ HÌNH ETA TRÊN `3.704.820` MẪU TEST (`TD-22`)
> **Mã nguồn chính tắc**: [`eta_model_trainer.py`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py) | **CLI**: [`scripts/train_and_evaluate_ml_eta.py`](file:///z:/Desktop/Bus_tracking/scripts/train_and_evaluate_ml_eta.py)

### 3.1. Bảng so sánh độ chính xác theo tầm dự báo (`3.704.820` mẫu Test, `2026-11-01 .. 2026-11-07`)

| Tầm Dự Báo (Horizon) | Mô Hình (Estimator) | MAE (s) | MedAE (s) | RMSE (s) | P90 AE (s) | MAPE (%) | $R^2$ | $\le 1\text{m}$ (%) | $\le 2\text{m}$ (%) | $\le 3\text{m}$ (%) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1 trạm (`1_hop`)**<br>(`N = 863.984`) | `0_Baseline_Sum_P50` | `26,22` | `11,07` | `58,44` | `56,83` | `23,35%` | `0,7777` | `90,49%` | `96,46%` | `98,10%` |
| | `2_Physics_Probe_Blend` | `25,13` | `11,13` | `53,66` | `55,59` | `23,13%` | `0,8126` | `90,81%` | `96,82%` | `98,40%` |
| | `4_XGB_Global_Full_54Feat` | `24,04` | `11,42` | `51,38` | `52,07` | `24,19%` | `0,8282` | `91,87%` | `97,44%` | `98,74%` |
| | **`6_XGB_Pruned_47Feat`** | **`23,70`** | **`11,32`** | **`51,01`** | **`51,37`** | `24,05%` | **`0,8306`** | **`92,13%`** | **`97,58%`** | **`98,80%`** |
| **2–5 trạm (`2_to_5`)**<br>(`N = 1.086.650`) | `0_Baseline_Sum_P50` | `65,69` | `37,60` | `115,82` | `139,95` | `13,82%` | `0,7850` | `66,20%` | `86,65%` | `93,12%` |
| | `2_Physics_Probe_Blend` | `62,09` | `37,24` | `106,03` | `133,89` | `13,40%` | `0,8198` | `66,69%` | `87,60%` | `94,08%` |
| | `4_XGB_Global_Full_54Feat` | `58,85` | `36,23` | `100,41` | `125,05` | `13,12%` | `0,8384` | `68,33%` | `89,06%` | `94,95%` |
| | **`6_XGB_Pruned_47Feat`** | **`58,31`** | **`36,00`** | **`99,55`** | **`123,83`** | **`13,02%`** | **`0,8412`** | **`68,65%`** | **`89,28%`** | **`95,07%`** |
| **6–15 trạm (`6_to_15`)**<br>(`N = 927.208`) | `0_Baseline_Sum_P50` | `137,83` | `89,40` | `213,76` | `302,40` | `10,10%` | `0,7957` | `35,44%` | `61,01%` | `76,20%` |
| | `2_Physics_Probe_Blend` | `130,43` | `88,10` | `199,18` | `285,14` | `9,68%` | `0,8226` | `36,17%` | `62,11%` | `77,51%` |
| | `4_XGB_Global_Full_54Feat` | `119,84` | `82,76` | `180,87` | `257,92` | `9,13%` | `0,8537` | `38,09%` | `64,97%` | `80,18%` |
| | **`6_XGB_Pruned_47Feat`** | **`118,53`** | **`82,30`** | **`178,50`** | **`255,64`** | **`9,04%`** | **`0,8575`** | **`38,37%`** | **`65,35%`** | **`80,52%`** |
| **> 15 trạm (`gt_15`)**<br>(`N = 826.978`) | `0_Baseline_Sum_P50` | `246,84` | `167,16` | `365,92` | `539,05` | `8,56%` | `0,8520` | `19,78%` | `37,98%` | `52,83%` |
| | `2_Physics_Probe_Blend` | `242,55` | `165,63` | `358,04` | `523,98` | `8,42%` | `0,8583` | `20,12%` | `38,24%` | `53,12%` |
| | `4_XGB_Global_Full_54Feat` | `204,56` | `148,75` | `295,06` | `444,47` | `7,34%` | `0,9038` | `22,41%` | `42,47%` | `58,49%` |
| | **`6_XGB_Pruned_47Feat`** | **`200,90`** | **`146,82`** | **`288,23`** | **`437,53`** | **`7,23%`** | **`0,9082`** | **`22,65%`** | **`42,88%`** | **`59,02%`** |
| **TOÀN BỘ (`ALL`)**<br>(`N = 3.704.820`) | `0_Baseline_Sum_P50` | `114,98` | `50,32` | `214,61` | `288,87` | `13,94%` | `0,9643` | `53,80%` | `71,66%` | `81,05%` |
| | `1_Baseline_Sum_Mean` | `118,08` | `53,18` | `216,55` | `298,68` | `14,67%` | `0,9637` | `52,81%` | `70,71%` | `80,24%` |
| | `2_Physics_Probe_Blend` | `110,86` | `49,94` | `206,19` | `276,28` | `13,63%` | `0,9671` | `54,28%` | `72,35%` | `81,80%` |
| | `3_XGB_Route_Blind_49Feat` | `97,82` | `47,24` | `174,67` | `246,94` | `13,38%` | `0,9764` | `56,08%` | `74,68%` | `84,09%` |
| | `4_XGB_Global_Full_54Feat` | `98,52` | `47,22` | `176,62` | `246,79` | `13,41%` | `0,9758` | `56,00%` | `74,59%` | `84,00%` |
| | `5_XGB_Global_Calibrated` | `98,90` | `47,58` | `177,08` | `247,04` | `13,54%` | `0,9757` | `55,86%` | `74,46%` | `83,92%` |
| | **`6_XGB_Pruned_47Feat`** | **`97,14`** | **`46,84`** | **`173,30`** | **`243,62`** | **`13,30%`** | **`0,9767`** | **`56,28%`** | **`74,87%`** | **`84,25%`** |

### 3.2. Tỷ trọng đóng góp của 6 Họ Đặc Trưng Nhân Quả (`a..f`) và Kết quả Cắt tỉa Đặc trưng
- **Đóng góp theo Họ Đặc Trưng (`Total Gain %`)**:
  1. **(a) Trạng thái hiện tại & Động học xe đang xét (`a_current_ego_state` — 23 biến)**: **`42,00%` Gain** (`50,43%` số lần tách nhánh) — Dẫn đầu bởi `cos_time` (`8,36%`), `hour_slot` (`7,25%`), `sin_time` (`5,32%`), `ego_cum_delay_vs_baseline_sec` (`4,47%`), `dist_to_next_station_m` (`2,59%`), `route_id_idx` (`2,46%`).
  2. **(d) Quá khứ xa — Ma trận thời gian lịch sử (`d_historical_matrix` — 9 biến)**: **`32,25%` Gain** (`27,16%` Splits) — Dẫn đầu bởi `baseline_skew_sec = Sum(Mean - P50)` (`13,04%` — biến quan trọng số 1 toàn mô hình, bù chính xác độ chệch cộng tổng trung vị `TD-11`!), `baseline_eta_iqr_sec` (`10,13%`), `baseline_max_seg_p90_sec` (`3,29%`), `baseline_eta_rss_std_sec` (`3,03%`).
  3. **(c) Quá khứ gần — Xe cùng tuyến vừa đi qua đoạn đường phía trước (`c_recent_preceding_bus` — 4 biến)**: **`10,99%` Gain** — Dẫn đầu bởi `recent_corridor_congestion_ratio` (`7,94%`) và `recent_corridor_tt_sum_sec` (`1,41%`).
  4. **(e) Sự cố giao thông TomTom phía trước (`e_tomtom_incidents` — 6 biến)**: **`7,85%` Gain** — Dẫn đầu bởi `inc_ahead_total_delay_sec` (`3,52%`) và `inc_ahead_max_delay_sec` (`2,83%`).
  5. **(f) Thông tin ẩn cấu trúc tuyến & Tương tác vật lý (`f_route_profile_physics` — 4 biến)**: **`4,47%` Gain** — Dẫn đầu bởi `physics_probe_corrected_eta_sec` (`1,54%`), `route_base_speed_kmh` (`1,34%`), `route_station_spacing_m` (`1,07%`).
  6. **(b) Các xe cùng tuyến chạy phía trước & phía sau (`b_fleet_ahead_behind` — 8 biến)**: **`2,44%` Gain** — Dẫn đầu bởi `lead_bus_speed_ratio` (`1,35%`).
- **7 đặc trưng dư thừa đã được cắt tỉa tự động trong `6_XGB_Pruned_47Feat`** (chỉ chiếm tổng cộng `0,48%` Gain; khi loại bỏ giúp giảm hiện tượng nhiễu tách nhánh và kéo `MAE` từ `98,52s` xuống **`97,14s`**):
  - `ego_accel_kmh_per_min` (nhiễu đạo hàm bậc 2 giữa 2 bản tin GPS 75s)
  - `lead_bus_time_headway_sec` (trùng thông tin với `lead_bus_dist_ahead_m` + `lead_bus_speed_kmh`)
  - `follow_bus_dist_behind_m`, `follow_bus_speed_kmh`, `n_active_buses_on_route` (xe chạy phía sau lưng không ảnh hưởng nhân quả trực tiếp đến đường phía trước của xe đang xét!)
  - `baseline_eta_mean_sec` (đã được biểu diễn hoàn hảo qua `baseline_eta_p50_sec + baseline_skew_sec`)
  - `inc_ahead_count` (đã được đại diện tốt hơn bởi `inc_ahead_total_delay_sec` và `inc_ahead_max_delay_sec`)

---

## 4. CÁC CÔNG VIỆC TIẾP THEO CHO PHIÊN LÀM VIỆC MỚI (NEXT SESSION ACTION PLAN)

1. **Xử lý `TD-23` (Cân bằng tập Validation theo thời gian cho Bước 3.4)**:
   - *Phát hiện EDA ([`experiments/eda_step_3_4_ml_diagnostics.py`](file:///z:/Desktop/Bus_tracking/experiments/eda_step_3_4_ml_diagnostics.py))*: Trong tập Train (`2026-10-08 .. 2026-10-31`), 3 ngày `28, 29, 30/10` bị trống dữ liệu nên điều kiện `dt >= "2026-10-28"` trong `eta_model_trainer.py` chỉ lấy được đúng `15.332` dòng của ngày Thứ 7 (`2026-10-31`). Điều này làm `Model_4_XGB_Global_Full_54Feat` dừng sớm (`best_iter=160`) và làm bộ hiệu chỉnh `Empirical-Bayes Calibrator` chỉ khớp trên ngày Thứ 7.
   - *Hành động*: Sửa `val_start_date = "2026-10-24"` trong [`eta_model_trainer.py`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py#L145) để tập Validation bao phủ đủ 5 ngày cuối của tập Train (`24/10` Thứ 7, `25/10` Chủ Nhật, `26-27/10` Ngày thường, `31/10` Thứ 7 — tổng `2.767.356` dòng, đầy đủ cả 3 `day_type`), chạy lại `scripts/train_and_evaluate_ml_eta.py` và nghiệm thu kết quả.
2. **Xử lý `TD-21` (Sửa [`catalog_refresher.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py) & cập nhật ID xe Tuyến 40 nếu người dùng phê duyệt)**:
   - Sửa `audit_vehicle` kiểm tra `lastUpdateTime` (nếu quá 24h hoặc `direction < 0` thì đánh dấu `"DEAD_OR_STALE"`).
   - Chỉ đếm `res["status"] == "ACTIVE"` vào `active_on_route`.
   - Sửa Phase 2 đọc đúng khóa camelCase (`id`, `routeId`, `title`) và quét tiền tố biển số Hà Nội (`29B10..29B35`, `29F00..29F09`), đồng thời cập nhật 3 ID mới (`8836674, 8836680, 8836704`) cho Tuyến 40 trong `data/metadata/hust_cluster_config.json`.
3. **Bước 3.5 (Step 3.4 trong kiến trúc thư mục `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation`)**:
   - Đóng gói pipeline suy luận thời gian thực (`Real-Time ETA Inference Engine`) kết hợp:
     - Cổng lọc trạng thái bến đầu cuối (`get_bus_terminal_or_corridor_status` — `TD-19`)
     - Tra cứu $O(1)$ Ma trận Baseline (`agg_segment_travel_times` — `TD-18`)
     - Suy luận mô hình `eta_xgb_global_pruned.json` (`47` đặc trưng nhân quả).


---

## 5. CẬP NHẬT SAU BÀN GIAO (20:06) — ĐÃ XỬ LÝ `TD-23`, SỬA LẠI KẾT LUẬN MỤC 3 & 4

> [!IMPORTANT]
> **Mục 3 (bảng 7 mô hình, "Pruned 47Feat tốt nhất") là kết quả vòng 1 với Validation lỗi (1 ngày Thứ 7) và KHÔNG còn hiệu lực.** Mục 4.1 (`TD-23`) đã làm xong. Dùng số liệu dưới đây.

Đã đổi `val_start_date` thành `2026-10-24` (Train `2.636.933` dòng `10-08..23`; Validation `954.078` dòng `10-24..31`), chạy lại [`train_and_evaluate_ml_eta.py`](file:///z:/Desktop/Bus_tracking/scripts/train_and_evaluate_ml_eta.py) (`403s`). Kết quả trên `3.704.820` mẫu Test (`ALL`):

| Mô hình | MAE (s) | MedAE (s) | RMSE (s) | $R^2$ |
| :--- | :---: | :---: | :---: | :---: |
| `0_Baseline_Sum_P50` | `114,98` | `50,32` | `214,61` | `0,9643` |
| `2_Physics_Probe_Blend` | `110,86` | `49,94` | `206,19` | `0,9671` |
| `3_XGB_Route_Blind_49Feat` | `98,13` | `47,35` | `174,12` | `0,9765` |
| `4_XGB_Global_Full_54Feat` | `97,91` | `47,05` | `173,94` | `0,9766` |
| **`5_XGB_Global_Calibrated`** | **`97,11`** | **`46,71`** | **`173,02`** | **`0,9768`** |
| `6_XGB_Pruned_51Feat` | `97,77` | `47,13` | `173,56` | `0,9767` |

Tầm `> 15` trạm: Baseline `246,84s` → Calibrated `200,44s`. Họ đặc trưng (Gain): a `41,79%`, d `32,33%`, c `10,56%`, e `7,94%`, f `4,87%`, b `2,49%`.

**Kết luận đã sửa**: (1) Lợi ích lớn đến từ XGBoost học phần dư (`-15,5%` MAE); (2) Route-Blind vs Route-Aware vs Calibrated vs Pruned chênh `< 1s` MAE, nên chưa có bằng chứng cho underfitting do thiếu định danh tuyến; (3) Hiệu chỉnh theo tuyến chỉ cải thiện nhẹ ở tầm xa, và một số tuyến tăng sai số.

### CÁC VẤN ĐỀ TỒN ĐỌNG & NỢ KỸ THUẬT (TECHNICAL DEBT & OPEN ISSUES)
- **Route `90` kém hơn Baseline** (`70,95s` → `71,49s`, calibrated `73,24s`). Cần điều tra (phiên tới).
- **Chưa có kiểm định ý nghĩa thống kê / khoảng tin cậy** cho chênh lệch `< 1s` giữa các biến thể; `MedAE`/`P90` tính trên mẫu con (`~1/n` bước nhảy), không phải toàn bộ.
- **Train chỉ lấy mẫu `55.000` dòng/tuyến (`~2,64 triệu / 11,36 triệu`)**; chưa thử toàn bộ dữ liệu.
- **Không có siêu tham số tuning** (cấu hình XGBoost cố định); `best_iter=437–449` sát giới hạn `n_estimators=450`, mô hình có thể chưa hội tụ.
- **Tập Test phụ thuộc cùng chế độ ngày hạn chế**: chỉ 1 Chủ Nhật và 1 Thứ 7 (`11-01`, `11-07`; `11-06`–`11-07` ít dòng) nên kết quả cuối tuần ít đáng tin.
- **`TD-21` (crawler Route 40) vẫn mở**, chờ người dùng phê duyệt sửa `catalog_refresher.py` + `hust_cluster_config.json` (Điều 3.1).
- Các file trong `data/models/` đã bị ghi đè bằng kết quả vòng 2 (`eta_xgb_global_pruned.json` nay là bản `51` đặc trưng, không phải `47`); không có bản cũ.
- Chưa commit git cho các thay đổi từ `d2c9af8` trở đi.


---

## 6. TIẾN ĐỘ "CÀI ĐẶT TỔNG THỂ" (bắt đầu 20:09) — LÀM TỪNG BƯỚC, CẬP NHẬT LIÊN TỤC

| Bước | Nội dung | Trạng thái |
| :--- | :--- | :---: |
| 1 | `TD-21`: vá `catalog_refresher.py`, cập nhật config xe Tuyến 40 | **XONG** (xem `TD-24` cho nợ phụ) |
| 2 | Điều tra Route `90` (**XONG**, `TD-25`); thử 1200 cây + `110k` dòng/tuyến (**XONG**, xem mục 7): MAE `97,11s → 95,76s` (`-1,4%`), tốn ~`3x` thời gian | **XONG** |
| 3 | Commit git (**XONG cục bộ**: `664d69d`, 12 file mã/tài liệu + 2 file metadata crawler; **CHƯA push**, **chưa commit** `data/models/` (30 MB) và `*.bak_td21`). Đồng bộ cloud crawler: **CHƯA LÀM**, chờ người dùng quyết định cách đẩy | MỘT PHẦN |
| 4 | Engine suy luận ETA (lát cắt serving) — đặc tả [`06_ETA_INFERENCE_ENGINE_SPEC.md`](file:///z:/Desktop/Bus_tracking/docs/06_ETA_INFERENCE_ENGINE_SPEC.md); mã [`eta_inference_engine.py`](file:///z:/Desktop/Bus_tracking/module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/eta_inference_engine.py); kiểm chứng [`verify_eta_serving.py`](file:///z:/Desktop/Bus_tracking/scripts/verify_eta_serving.py): MAE qua engine `95,7617s` (khớp `95,76`), độ trễ 1 dòng trung vị `7,42ms` (p95 `9,65ms`), lô `10.000` dòng `72,9ms` (`137.224` dòng/s), từ chối `NaN`/thiếu cột. **XONG (lát cắt); còn nợ `TD-26`** | **XONG** |

**Bước 1 — thay đổi**: [`config/system_config.py`](file:///z:/Desktop/Bus_tracking/config/system_config.py) (`CATALOG_STALE_HOURS`, `CATALOG_MIN_ACTIVE_PER_ROUTE`, `CATALOG_SCAN_PREFIXES`), [`catalog_refresher.py`](file:///z:/Desktop/Bus_tracking/module_1_data_ingestion_and_preprocessing/step_1_1_busmap_crawler_and_relay/catalog_refresher.py). Chạy thực: rà soát `504` xe → `317` ACTIVE, `152` DEPOT, `2` OFFLINE (còn lại ~`33` là `STALE`, chưa in riêng); thêm `21` xe, tổng `526`. Lưu ý: file `hust_cluster_config.json` ở máy cục bộ đã đổi; crawler cloud chưa nhận.

---

## 7. KẾT QUẢ BƯỚC 2 — TĂNG QUY MÔ HUẤN LUYỆN (`ETA_MODEL_TAG=_r3_big`)

Cấu hình: `n_estimators=1200`, `110.000` dòng/tuyến → Train `4.960.021` dòng (vòng 2: `2.636.933`), Validation `954.078` (giữ nguyên), `best_iter` Global Full `677` (không chạm trần `1200`, đã hội tụ). Tổng `1.097s`. Model: `data/models/*_r3_big.json` (model vòng 2 vẫn còn). Đánh giá `3.704.820` mẫu Test, `ALL`:

| Mô hình | MAE vòng 2 | MAE vòng 3 | RMSE vòng 3 | $R^2$ vòng 3 |
| :--- | :---: | :---: | :---: | :---: |
| Baseline Sum(P50) | `114,98` | `114,98` | `214,61` | `0,9643` |
| `4_XGB_Global_Full` | `97,91` | `96,56` | `170,47` | `0,9775` |
| **`5_XGB_Global_Calibrated`** | `97,11` | **`95,76`** | **`169,56`** | **`0,9777`** |
| `6_XGB_Pruned` (53 đặc trưng) | `97,77` | `96,70` | `170,89` | `0,9774` |

Tầm `> 15` trạm: Calibrated `200,44s → 196,39s` (Baseline `246,84s`). `46/47` tuyến vẫn cải thiện; **Route `90` kém Baseline `1,33s`** (`70,95 → 72,28s`, tệ hơn vòng 2 `0,54s`). Đóng góp họ đặc trưng: a `43,37%`, d `31,15%`, c `10,49%`, e `7,38%`, f `4,54%`, b `3,07%`.

**Kết luận**: Tăng gấp đôi dữ liệu và gần 3 lần số cây chỉ giảm MAE thêm `1,35s` (`-1,4%`), tức lợi ích biên rất nhỏ so với Baseline `-16,7%`. Calibrated vẫn là tốt nhất ở cả hai vòng; cắt tỉa không giúp (chỉ loại được `1` đặc trưng ở vòng này). Điểm nghẽn không còn ở dung lượng mô hình mà ở dịch chuyển phân phối (`TD-25`) và nhiễu cố hữu của dữ liệu.

**Nợ còn lại của Bước 2**: chưa có khoảng tin cậy cho chênh `~1s`; Calibrated tốt hơn Full `0,8s` nhưng chưa kiểm định thống kê; Route `90` xấu đi khi tăng dung lượng (dấu hiệu overfit chế độ Train); Calibrated tối ưu trên Validation `10-24..31` có thể quá khớp với 8 ngày này; chưa quyết định model nào đưa vào phục vụ (đề xuất `5_XGB_Global_Calibrated` bản `_r3_big`, cần người dùng duyệt); chưa commit git.
