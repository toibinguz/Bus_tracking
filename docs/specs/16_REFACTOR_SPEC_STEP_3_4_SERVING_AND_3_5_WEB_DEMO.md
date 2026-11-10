# SPEC-16: ĐẶC TẢ REFACTOR HYBRID (CONTROLLED) — STEP 3.4 SERVING & STEP 3.5 WEB DEMO
> **Status: partially implemented / verification pending (2026-11-10).** Split files exist, but `app.py` still imports `busmap_service.py`; interface inspection therefore fails W-01 and planned tests are absent.

- **Document ID:** `16_REFACTOR_SPEC_STEP_3_4_SERVING_AND_3_5_WEB_DEMO`
- **Tác giả:** `@architect`
- **Người thực thi:** `@leaf_coder`
- **Người nghiệm thu độc lập:** `@blind_tester`
- **Ngày ban hành:** 2026-11-09
- **Trạng thái:** APPROVED / READY FOR IMPLEMENTATION
- **Chiến lược:** HYBRID controlled refactor.

  - `step_3_4`: **KEEP + di chuyển** các phần đúng và khớp hợp đồng đóng băng (SQLite/DuckDB data access, live BusMap fetch + cache, DTO contract, route shape/stations, hình học Frenet hợp nhất được với module 1.4). **REWRITE** tầng ETA composition/policy và **THÊM MỚI** online feature extractor. Full ML integration (XGBoost) là bắt buộc trong scope.
  - `step_3_5`: **CHỈ FIX** (giữ CDN — không vendor offline, hợp nhất health contract, escape HTML/XSS, sửa CORS, dọn dead code). Không rewrite UI.

- **Bất biến upstream:** `step_3_1`, `step_3_2`, `step_3_3`, toàn bộ `module_1`/`module_2` là **FROZEN**. Mọi output của chúng được coi là hợp đồng cố định (xem §1). Không được sửa các file này.
- **Căn cứ:** `AGENTS.md`; `docs/specs/08_STATION_ETA_MAP_INTEGRATION_SPEC.md` (SPEC-08); `docs/specs/09_REALTIME_FEATURE_EXTRACTION_AND_COLD_START_SPEC.md` (SPEC-09); `docs/specs/11_CONSERVATIVE_ASYMMETRIC_ETA_AND_UI_HYSTERESIS_SPEC.md` (SPEC-11); `docs/specs/15_PHYSICAL_KINEMATICS_AND_SERVING_SPEC.md` (SPEC-15).

> **Quy ước bằng chứng:** mọi khẳng định kỹ thuật đều kèm `đường_dẫn:line`. Các suy luận không trích được trực tiếp đều đánh dấu **[SUY LUẬN]**.

---

## 1. HỢP ĐỒNG UPSTREAM ĐÓNG BĂNG (PIN IT)

### 1.1. Nguồn dữ liệu vào (inputs) mà 3.1/3.2/3.3 tiêu thụ

Hai bảng SQLite canonical (đọc trong `baseline_matrix_builder.py:183-197` và `feature_store_builder.py:653-682`):

| Bảng | Các cột được dùng | Bằng chứng |
|---|---|---|
| `canonical_route_master` | `route_id, route_code, route_name` | `busmap_service.py:412-415` |
| `canonical_station_master` | `route_code, direction, station_order, station_id, station_name, cum_distance_m` (và `address, lat, lon` khi serving) | `baseline_matrix_builder.py:189-194`; `busmap_service.py:569-574` |
| `canonical_shape_master` | `route_code, direction, point_order, lat, lon, cum_distance_m` | `baseline_matrix_builder.py:184`; `multi_route_projector.py:367` |

Bảng Silver (Parquet Hive) tiêu thụ:
- `data/lakehouse/silver/route_projected_telemetry/route_code=XX/...` với các cột `route_code, vehicle_id, device_update_time, device_epoch, direction, s_bus_m, derived_speed_kmh` (`baseline_matrix_builder.py:200-203`; `feature_store_builder.py:147-150`).
- `data/lakehouse/silver/fact_route_tomtom_incidents/route_code=XX/...` với các cột `direction, t_start_epoch, t_end_epoch, s_min_m, s_max_m, delay_seconds, magnitude_of_delay, overlap_length_m` (`feature_store_builder.py:159-164`).

### 1.2. Sản phẩm (outputs) mà serving phải tiêu thụ

**(A) Bảng SQLite `agg_segment_travel_times`** — do `baseline_matrix_builder.py:439-468` tạo. Schema chính xác (18 cột, `baseline_matrix_builder.py:441-462`):

```
route_code TEXT, direction TEXT, from_station_order INT, to_station_order INT,
from_station_id INT, to_station_id INT, from_station_name TEXT, to_station_name TEXT,
segment_length_m REAL, day_type INT, hour_slot INT, sample_count INT, quality_tier INT,
tt_p10_sec REAL, tt_p50_sec REAL, tt_p90_sec REAL, tt_mean_sec REAL, tt_std_sec REAL
PRIMARY KEY (route_code, direction, from_station_order, to_station_order, day_type, hour_slot)
```

- `direction ∈ {'go','re'}` (`baseline_matrix_builder.py:331`), `day_type ∈ {0,1,2}` (`:344`), `hour_slot ∈ [5,21]` (`config/system_config.py:216-217`).
- Bất biến: `0 ≤ p10 ≤ p50 ≤ p90` được enforce khi serving (`busmap_service.py:722-724`).
- Lưu ý phạm vi: bảng được dựng trên **active corridor** `st_list = get_active_corridor_stations(full_st_list)` tức `st_list[1:-1]` khi `EXCLUDE_TERMINAL_BOUNDARY_STATIONS=True` và `len>=4` (`baseline_matrix_builder.py:74-84, 237-238, 332`). ⇒ **Không có ô baseline cho các đoạn chạm trạm biên 0 và trạm cuối `N-1`.** Đây là điểm phải phản ánh khi serving (xem §2.6 mismatch M1).
- Bản Gold song song: `data/lakehouse/gold/agg_segment_travel_times/part-00000.snappy.parquet` (`baseline_matrix_builder.py:472-487`).

**(B) Gold Feature Store** — do `feature_store_builder.py` tạo tại `data/lakehouse/gold/eta_feature_store/split={train,test}/route_code=XX/part-00000.snappy.parquet` (`feature_store_builder.py:625-633`). Thứ tự cột chính xác = `FEATURE_COLUMNS` (`feature_store_builder.py:74-102`), gồm 8 cột metadata/target + 54 cột feature:

```
route_code, direction, dt, vehicle_id, device_epoch,
current_station_order, target_station_order, actual_eta_sec,
# (a) 23 cột ... (b) 8 ... (c) 4 ... (d) 9 ... (e) 6 ... (f) 4
```

Kiểu dữ liệu: các cột trong `INT32_COLS` cast `int32`, còn lại cast `float32` (`feature_store_builder.py:104-108, 616-620`).

**(C) Artifact mô hình** `data/models/*.json` — do `eta_model_trainer.py:637-642, 793-806` tạo.

### 1.3. HỢP ĐỒNG MODEL SERVING (KHÔNG NHẬP NHẰNG)

#### 1.3.1. Quyết định artifact chuẩn (CANONICAL)

**CANONICAL = `data/models/eta_xgb_global_full_54feat_r3_big.json`** (54 feature, 708 cây) **+ calibrator** nhúng trong `data/models/eta_xgb_metadata_and_calibrator_r3_big.json` (khóa `"calibrator"`, 384 ô), theo đúng pipeline Model 5 `5_XGB_Global_Calibrated`.

Bằng chứng quyết định:

| Ứng viên | n_trees | n feature (JSON `learner.feature_names`) | MAE ALL (test) | Kết luận |
|---|---|---|---|---|
| `eta_xgb_global_full_54feat.json` | 450 | 54 | 97.91 s | Không ưu tiên (r3_big tốt hơn) |
| **`eta_xgb_global_full_54feat_r3_big.json`** | **708** | **54** | **96.56 s** (calibrated **95.76 s**) | ✅ **CANONICAL** |
| `eta_xgb_global_pruned.json` | 450 | 51 | 97.77 s | ❌ Loại (tập pruned không ổn định) |
| `eta_xgb_global_pruned_r3_big.json` | 635 | 53 | 96.70 s | ❌ Loại (xem dưới) |

- Số cây và `feature_names` đọc trực tiếp từ `learner.gradient_booster.model.tree_info` / `learner.feature_names` trong các file JSON (đã xác minh).
- Điểm MAE lấy từ `summary_metrics[m]["ALL"]` trong metadata (đã xác minh).

**Vì sao KHÔNG chọn pruned (giải quyết dứt điểm câu hỏi "47 vs 54"):**
1. Tập pruned **không ổn định giữa 2 lần chạy**: bản default giữ 51 feature / loại 3 feature; bản `_r3_big` giữ 53 feature / loại 1 feature (nguồn: `pruned_features`/`pruned_out_features` trong 2 file metadata). Tập bị loại thay đổi ⇒ không thể coi là hợp đồng cố định.
2. `feature_names` của model pruned lưu theo **thứ tự Gain giảm dần**, KHÔNG theo thứ tự canonical `ALL_54_FEATURES` (bằng chứng: `feature_names[:6]` của pruned = `['baseline_skew_sec','baseline_eta_iqr_sec','cos_time','recent_corridor_congestion_ratio','hour_slot','sin_time']`).
3. Chênh lệch độ chính xác không đáng kể (MAE pruned 96.70 s vs full 96.56 s) trong khi rủi ro sai thứ tự feature khi serving cao hơn.
4. **[SUY LUẬN]** Tuyên bố "README nói 47 feature": không tìm thấy trong repo bất kỳ câu "47 feature" nào (grep `docs/specs/*.md` + `module_3_bus_eta_prediction/README.md` chỉ ra số 47 trong SPEC-09 là **chỉ số thứ tự feature** tại `docs/specs/09...md:58,134`, không phải số lượng feature). SPEC-09:390 còn nhắc phiên bản pruned "38 đặc trưng" cho kịch bản client-side — một giả thuyết, không có artifact tương ứng. ⇒ Không đủ bằng chứng để chọn pruned.

**Phương án dự phòng (nếu buộc dùng pruned):** dùng `eta_xgb_global_pruned_r3_big.json` + calibrator r3_big, và BẮT BUỘC reindex cột theo `model.get_booster().feature_names` (53 feature). Khuyến nghị: **không dùng**.

#### 1.3.2. Danh sách feature có thứ tự chính xác (54 feature)

Thứ tự dưới đây là thứ tự canonical `ALL_54_FEATURES` (`eta_model_trainer.py:125-132`) và khớp đúng `learner.feature_names` của model full (đã xác minh `feature_names[:6] = ['route_id_idx','direction_id','current_station_order','target_station_order','day_type','day_of_week']`).

**(a) Ego state & kinematics — 23** (`eta_model_trainer.py:53-77`)
`route_id_idx, direction_id, current_station_order, target_station_order, day_type, day_of_week, hour_slot, sin_time, cos_time, s_bus_m, s_target_m, remaining_distance_m, n_stations_ahead, progress_ratio, target_progress_ratio, dist_to_next_station_m, ego_speed_instant_kmh, ego_speed_roll3_kmh, ego_speed_roll5_kmh, ego_accel_kmh_per_min, ego_speed_ratio_vs_baseline, ego_trip_elapsed_sec, ego_cum_delay_vs_baseline_sec`

**(b) Same-route fleet — 8** (`eta_model_trainer.py:79-88`)
`lead_bus_dist_ahead_m, lead_bus_time_headway_sec, lead_bus_speed_kmh, lead_bus_speed_ratio, follow_bus_dist_behind_m, follow_bus_speed_kmh, n_active_buses_on_route, n_buses_in_corridor_ahead`

**(c) Recent preceding-bus probe — 4** (`eta_model_trainer.py:90-95`)
`recent_corridor_tt_sum_sec, recent_corridor_congestion_ratio, recent_seg_coverage_ratio, recent_next_seg_congestion_ratio`

**(d) Historical baseline matrix — 9** (`eta_model_trainer.py:97-107`)
`baseline_eta_p50_sec, baseline_eta_mean_sec, baseline_eta_p10_sec, baseline_eta_p90_sec, baseline_eta_iqr_sec, baseline_eta_rss_std_sec, baseline_skew_sec, baseline_max_seg_p90_sec, baseline_tier0_frac`

**(e) TomTom incidents — 6** (`eta_model_trainer.py:109-116`)
`inc_ahead_count, inc_ahead_total_delay_sec, inc_ahead_max_delay_sec, inc_ahead_max_magnitude, inc_ahead_jam_length_m, inc_dist_to_nearest_m`

**(f) Route profile & physics interactions — 4** (`eta_model_trainer.py:118-123`)
`route_base_speed_kmh, route_station_spacing_m, physics_kinematic_eta_sec, physics_probe_corrected_eta_sec`

**Categorical** (cast `category` trước khi predict, `eta_model_trainer.py:144-149, 180-186`): `route_id_idx, direction_id, day_type, hour_slot`. (`feature_types` của model = `['c','c','int','int','c','int', ...]` ở 6 phần tử đầu.)

#### 1.3.3. Ngữ nghĩa target (residual vs absolute)

- XGBoost dự báo **RESIDUAL**, không phải absolute:
  `y = actual_eta_sec - baseline_eta_p50_sec` (`eta_model_trainer.py:8, 457, 462`).
- Dựng ETA: `ETA = max(5.0, baseline_eta_p50_sec + pred_delta)` (`eta_model_trainer.py:516-520`).
- Sample weight huấn luyện: `w = 1/sqrt(max(60, baseline_eta_p50_sec))` (`eta_model_trainer.py:463`) — chỉ ảnh hưởng huấn luyện, serving KHÔNG dùng.
- Objective: `reg:pseudohubererror`, `huber_slope=90` (đã xác minh trong JSON `learner.objective`).

#### 1.3.4. Quantile outputs

- XGBoost chỉ xuất **1 giá trị điểm (point P50)**. **Không** sinh P10/P90.
- P10/P90 của `SafeWindowDTO` đến từ **ma trận baseline** (`tt_p10_sec`, `tt_p90_sec`) tích lũy theo SPEC-08 §2.3 (`docs/specs/08...md:137-153`). Bất biến `p10 ≤ p50 ≤ p90` (`docs/specs/08...md:159-164`).

#### 1.3.5. Cách áp calibrator

- Huấn luyện: `fit_per_route_empirical_bayes_calibrator` (`eta_model_trainer.py:242-296`) tạo ánh xạ `(route_id_idx, direction_id, horizon_bucket) → (scale_factor, bias_shift)`.
- `horizon_bucket = assign_horizon_bucket(n_stations_ahead)` (`eta_model_trainer.py:166-177`): `0` nếu `==1`; `1` nếu `2..5`; `2` nếu `6..15`; `3` nếu `>15`.
- Áp dụng (`eta_model_trainer.py:299-324`), vector hóa:
  ```
  out = 0.5 * (out * scale_factor) + 0.5 * (out + bias_shift)
  out = max(5.0, out)
  ```
- Calibrator được persist dạng dict trong metadata JSON, khóa chuỗi `f"{route_id_idx}_{direction_id}_{horizon_bucket}"` → `[scale_factor, bias_shift]` (`eta_model_trainer.py:803`). 384 ô (đã xác minh).
- **Serving phải**: dựng lại khóa `f"{r}_{d}_{h}"`, tra `calibrator` từ metadata `_r3_big`; nếu thiếu ô → bỏ qua calibration (dùng `out` thô).

#### 1.3.6. Yêu cầu runtime model (bắt buộc)

- Load bằng `xgboost.XGBRegressor().load_model(path)` (mẫu tham chiếu: `experiments/eda/eda_route_90_underperformance.py:18-19`).
- Khi predict, DataFrames phải có đủ cột và **đúng thứ tự/`feature_names`** của booster: đọc `model.get_booster().feature_names` rồi `X = X.reindex(columns=feature_names)`; cast 4 cột categorical sang `category` (tương đương `prepare_xgb_dataframe`, `eta_model_trainer.py:180-186`).
- Feature `baseline_eta_p50_sec` vừa là **feature đầu vào** (family d) vừa là **anchor residual**. Phải tính nhất quán tuyệt đối với công thức 3.2 (`feature_store_builder.py:486-495`).

---

## 2. KIẾN TRÚC ĐÍCH & GIAO DIỆN CHO STEP 3.4

### 2.1. Layout file phẳng (Simplicity First)

```
module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/
├── dto.py             # Hợp đồng Pydantic (public API schema)
├── data_access.py     # SQLite + (tuỳ chọn) DuckDB: routes/shapes/stations/baseline matrix
├── live_feed.py       # Fetch BusMap + cache RAM + parse ping
├── frenet.py          # Chiếu Frenet 1D + tangent (hợp nhất với module 1.4)
├── online_features.py # OnlineFeatureExtractor: dựng vector 54 feature
├── model_runtime.py   # Load XGBoost + calibrator; predict absolute P50
├── eta_policy.py      # Dead-reckoning, buffer, quantization, state machine, traffic
└── serving_service.py # Orchestrator (BusMapServingService) + facade cho app.py
```

Lý do gộp: mỗi file một trách nhiệm duy nhất; không tách thêm `util.py`/`constants.py` vì hằng số đã về `config/system_config.py`. `busmap_service.py` cũ bị **thay bằng** `serving_service.py` — để tránh vỡ import của `app.py`, giữ một module `busmap_service.py` mỏng re-export facade (hoặc sửa import `app.py:16-25`).

### 2.2. `dto.py` — giao diện public

Giữ nguyên các model contract hiện có (`busmap_service.py:37-140`), nhưng tách XSS-safe và sửa trường zombie:

```python
class BusVehicleDTO(BaseModel): ...        # bỏ `lon` (alias trùng), bỏ `distance_to_next_m`
class RouteItemDTO(BaseModel): ...
class RouteLiveResponse(BaseModel): ...
class StationItemDTO(BaseModel): ...
class RouteStationsResponse(BaseModel): ...
class RouteShapeResponse(BaseModel): ...

class SafeWindowDTO(BaseModel):
    p10_seconds: float
    p50_seconds: float
    p90_seconds: float
    p10_minutes: int
    p90_minutes: int
    conservative_eta_seconds: float
    buffer_seconds: float                  # = delta_buffer thực (không hardcode 0)
    display_eta_minutes: int
    is_delayed: bool                       # = delta_delay >= REALTIME_DELAY_ALERT_SEC
    delay_seconds: float                   # = delta_delay thực
    recommended_arrival_time: str

class ApproachingBusDTO(BaseModel):
    vehicle_id: int
    plate: str
    distance_to_station_m: float
    stops_remaining: int
    eta_seconds: float
    eta_minutes: int                       # QUANTIZED int — product chuẩn (conflict C4)
    eta_minutes_precise: float             # float 1 chữ số — CHỈ demo hiển thị song song
    display_eta_minutes: int
    display_text: str
    safe_window: SafeWindowDTO
    speed_kmh: float
    status: str                            # "IN_TRANSIT" | "ARRIVING_NOW"
    traffic_status: str                    # "THONG_THOANG"|"BINH_THUONG"|"UN_TAC"
    ping_time: str
    ping_age_seconds: float
    arrival_time_epoch: float

class StationEtaResponse(BaseModel): ...
```

Trách nhiệm: chỉ định nghĩa schema. Không logic.

### 2.3. `data_access.py`

| Hàm/Class | Signature | Trách nhiệm |
|---|---|---|
| `class DataAccess` | `__init__(db_path: str = DEFAULT_DB_PATH)` | Mở/nạp catalog + baseline matrix vào RAM |
| `load_catalog()` | `-> tuple[list[RouteItemDTO], dict[int,RouteItemDTO], dict[str,RouteItemDTO]]` | Đọc `canonical_route_master` (giữ logic `busmap_service.py:404-450`) |
| `load_baseline_matrix()` | `-> dict[key, tuple[p10,p50,p90,mean,std]]` | Đọc `agg_segment_travel_times` (giữ logic `busmap_service.py:368-402`) |
| `resolve_route_id(ident)` | `(Union[str,int]) -> Optional[int]` | Giữ nguyên `busmap_service.py:456-489` |
| `get_route_shape(route_id, dir_str)` | `-> Optional[RouteShapeResponse]` | Giữ nguyên `busmap_service.py:491-543` |
| `get_route_stations(route_id, dir_str)` | `-> Optional[RouteStationsResponse]` | Giữ nguyên `busmap_service.py:545-607` |
| `lookup_baseline_tt(route_id, dir_int, k, k1, day_type, hour_slot, seg_len_m)` | `-> tuple[p10,p50,p90,mean,std]` | Giữ logic `busmap_service.py:703-741`; fallback dùng `DEFAULT_URBAN_BUS_SPEED_KMPH/3.6` |

Single responsibility: toàn bộ I/O SQLite/Parquet. Không tính ETA.

### 2.4. `live_feed.py`

| Hàm | Signature | Trách nhiệm |
|---|---|---|
| `parse_ping_epoch(ts_val, default_epoch)` | `-> tuple[float,str]` | Giữ nguyên `busmap_service.py:175-215` |
| `fetch_live_vehicles_for_route(route_id, direction)` | `-> RouteLiveResponse` | Fetch + hygiene + cache TTL; giữ logic `busmap_service.py:223-335` nhưng **sửa `HANOI_BBOX` keys** (§3 blocker B2) |
| `live_cache` | module-level `dict` | Cache RAM, TTL = `LIVE_CACHE_TTL_SEC` |

### 2.5. `frenet.py` — hợp nhất với module 1.4

Mục tiêu: loại bỏ **train/serve skew**. Module 1.4 `project_points_to_shape` (`module_1.../step_1_4.../multi_route_projector.py:49-170`) dùng:
`kx = METERS_PER_DEG_LON_EQUATOR * cos(radians(mean_lat))`, `ky = METERS_PER_DEG_LAT` (`:69-71`), lọc hành lang `d_perp <= MAX_CORRIDOR_CROSS_TRACK_M` (`:131,154,263`).

`busmap_service._get_shape_projection_model/_project_point` (`busmap_service.py:629-701`) tự dựng lại cùng công thức nhưng dùng các hằng số **không tồn tại** (`LON_DEGREE_TO_METERS`, `LAT_DEGREE_TO_METERS` — xem §3 blocker B1) và **không** dùng cửa sổ trượt tiến.

**Thiết kế hợp nhất:**

```python
# frenet.py
class ShapeProjectionModel:
    @classmethod
    def build(cls, shape_points: list[tuple[float,float,float]]) -> "ShapeProjectionModel":
        """shape_points = [(point_order, lat, lon, cum_distance_m)].
        kx = METERS_PER_DEG_LON_EQUATOR*cos(radians(mean_lat)); ky = METERS_PER_DEG_LAT."""

    def project_point(self, lat: float, lon: float) -> tuple[float, float, int]:
        """-> (s_bus_m, d_perp_m, seg_idx). seg_idx để suy tangent heading filter."""

    def segment_unit_tangent(self, seg_idx: int) -> tuple[float, float]:
        """-> (ux, uy) vector đơn vị tiếp tuyến tim tuyến (East, North)."""
```

Quy tắc:
- Dùng **cùng hằng số** với module 1.4: `METERS_PER_DEG_LON_EQUATOR` (`config/system_config.py:155`), `METERS_PER_DEG_LAT` (`:156`), `MAX_CORRIDOR_CROSS_TRACK_M` (`:158`).
- Với 1 ping đơn lẻ (serving), bỏ qua Forward Sliding Window (vốn cần `prev_s`); dùng nhánh global search y hệt `multi_route_projector.py:140-168` để cùng kết quả hình học.
- Module 1.4 là FROZEN ⇒ **không** sửa nó; `frenet.py` tái lập công thức trong một hàm dùng chung + bổ sung `seg_idx` (module 1.4 không trả `seg_idx`). **[SUY LUẬN]** Phương án lý tưởng về lâu dài là trích công thức thành một hàm chia sẻ ở module 1.4, nhưng điều đó phá bất biến frozen nên bị loại ở bước này.

### 2.6. `online_features.py` — OnlineFeatureExtractor (THÊM MỚI)

```python
class OnlineFeatureExtractor:
    def __init__(self, data_access: DataAccess, incidents_provider: "IncidentsProvider"): ...

    def update_observation(self, route_id: int, dir_int: int,
                           vehicles: list[BusVehicleDTO], now_epoch: float) -> None:
        """Cập nhật state nội bộ: RingBuffer(5) mỗi xe, trip origin, recent segment events."""

    def build_features(self, route_id: int, dir_int: int, vehicle: BusVehicleDTO,
                       target_order: int, s_target_m: float, s_bus_m: float,
                       now_epoch: float) -> dict[str, float]:
        """Trả dict đủ 54 khóa theo ALL_54_FEATURES."""
```

Nguồn cho từng nhóm (bám sát `feature_store_builder.py`):

- **(a) tĩnh/kinematics**: `route_id_idx` (chỉ mục tuyến trong danh mục sort), `direction_id`, `current_station_order = searchsorted(station_s, s_bus, 'right')-1` (`feature_store_builder.py:310-311`), `target_station_order`, `day_type/day_of_week/hour_slot/sin_time/cos_time` (`feature_store_builder.py:409-415`), phần hình học từ `s_bus_m/s_target_m`, `ego_speed_*` từ RingBuffer (công thức `feature_store_builder.py:328-338`).
- **(b) fleet**: từ 1 snapshot `vehicles` (`feature_store_builder.py:436-466`).
- **(c) recent probe**: sliding window 1800 s (`RECENT_PROBE_WINDOW_SEC`, `feature_store_builder.py:70, 471-501`).
- **(d) baseline**: prefix-sum O(1) (`feature_store_builder.py:485-495`) dùng `DataAccess`.
- **(e) incidents**: từ `fact_route_tomtom_incidents` (`feature_store_builder.py:505-529`) do `IncidentsProvider` nạp; nếu thiếu partition → toàn 0.
- **(f) physics**: `feature_store_builder.py:531-539` (w_probe=0.35, w_ego=0.20, decay 2500 m, `min(180, 0.25*inc_tot_delay)`).

**Cold-start**: lần đầu chưa đủ 5 ping → dùng Baseline Inversion SPEC-09 §4.2 (`docs/specs/09...md:267-305`): `v_roll3=v_roll5=v_inst`, `accel=0`, `rec_seg=p50`, `rec_cov=0`, `rec_cong=1`, `next_seg_probe=1`, `T_elapsed = prefix_p50[k]+α*p50[k]`, `D_cum=0`. State sống trong RAM tiến trình, cập nhật theo mỗi lần `fetch_live_vehicles_for_route` (không cần daemon 24/7) — **[SUY LUẬN]** chọn lazy accumulator vì `Simplicity First`.

### 2.7. `model_runtime.py`

```python
class ModelRuntime:
    @classmethod
    def load(cls, model_path: str, metadata_path: str) -> "ModelRuntime": ...
    @property
    def available(self) -> bool: ...

    def predict_p50(self, feature_row: dict[str, float]) -> Optional[float]:
        """XGBoost residual -> absolute. None nếu model unavailable/exception.
        = max(5.0, baseline_eta_p50_sec + delta) rồi áp calibrator theo (r,d,h)."""
```

Logic: `X = DataFrame([feature_row]).reindex(columns=self._booster_feature_names)`; cast categorical; `delta = model.predict(X)`; `base = feature_row['baseline_eta_p50_sec']`; `eta = max(5.0, base+delta)`; áp calibrator (`0.5*(eta*scale)+0.5*(eta+bias)`, `max(5,...)`).

### 2.8. `eta_policy.py`

```python
def project_filter_extrapolate(vehicle, shape_model, s_target, now_epoch, baseline_matrix,
                               route_id, dir_int, day_type, hour_slot) -> Optional["BusState"]:
    """SPEC-15 §8.1: staleness, corridor, heading cosine, station clamp (dead-reckoning HOÃN — §2.12)."""

def compute_station_eta(bus_state, route_id, dir_int, target_st, station_s, now_epoch,
                        baseline_matrix, day_type, hour_slot, ml_p50: Optional[float]
                        ) -> ApproachingBusDTO:
    """SPEC-15 §8.2 + ML override cho P50 + buffer LINEX + quantization + traffic."""
```

Trách nhiệm: toàn bộ chính sách ETA (không I/O, không I/O mạng).

### 2.9. `serving_service.py`

```python
class BusMapServingService:
    def __init__(self, db_path=None): ...
    def get_routes(self) -> list[RouteItemDTO]: ...          # ủy quyền DataAccess
    def resolve_route_id(self, ident) -> Optional[int]: ...
    def get_route_shape(self, ident, direction) -> Optional[RouteShapeResponse]: ...
    def get_route_stations(self, ident, direction) -> Optional[RouteStationsResponse]: ...
    def get_live_vehicles(self, route_code, direction=0) -> RouteLiveResponse: ...
    def get_station_eta(self, route_ident, direction=0, station_order=0) -> Optional[StationEtaResponse]:
        """1. live_feed.fetch; 2. Extractor.update_observation;
        3. per-vehicle: project_filter_extrapolate -> build_features -> model_runtime.predict_p50
        -> compute_station_eta; 4. sort & đóng gói response."""
```

`app.py` import facade từ đây (hoặc `busmap_service.py` re-export).

### 2.10. Chính sách ETA (policy chính xác) & giải quyết xung đột spec

Pipeline tổng:

```
ETA_core_p50 = calibrated_ML_p50            (nếu ModelRuntime.available)
             = baseline_p50                 (fallback khi thiếu model/feature; KHÔNG kinematic)
ETA_conservative = ETA_core_p50 + Δt_buffer
M = ceil(ETA_conservative / 60)
```

**(P1) ARRIVING_NOW band** — SPEC-15 wins. Dải `[-STATION_ARRIVING_EXIT_M, +STATION_ARRIVING_ENTRY_M] = [-20.0m, +30.0m]` (`docs/specs/15...md:96-100, 110-117`). Trong dải: `status="ARRIVING_NOW"`, `eta_seconds=0.0`, `display_eta_minutes=0`, `display_text="Đang cập bến"`, giữ xe trong `buses` (xóa bỏ "vách đá 10m" của `busmap_service.py:843`).
*Xung đột:* SPEC-08 §2.2 (`docs/specs/08...md:103-107`) và code cũ dùng `s_bus >= s_target - 10.0 ⇒ loại`. **SPEC-15 thắng** (mới hơn, chứng minh liên tục `docs/specs/15...md:123-131`, xử lý bus bunching/dừng trả khách).

**(P2) Δt_buffer bất đối xứng** — SPEC-15 wins. `Δt_buffer = κ(d)·[α·σ_accum + β·τ_telemetry + γ·ETA_core]`, `α=0.60, τ=15.0s, β=0.5 ⇒ 7.5s, γ=0.04`, clamp `[0, MAX_SAFE_BUFFER_CEILING_SEC=180]` (`docs/specs/15...md:310-318`).
*Xung đột:* SPEC-11 §3.2 dùng `α=0.50, β=1.0 (15.0s), γ=0.05` (`docs/specs/11...md:128-141`). **SPEC-15 thắng** (tuyên bố sửa trực tiếp công thức SPEC-11; `docs/specs/15...md:304-306`).

**(P3) κ(d) attenuation** — SPEC-15 wins: smoothstep `3ξ²-2ξ³` trên `[30,150]m`, `ξ=(d-30)/(150-30)` (`docs/specs/15...md:320-332`).
*Xung đột:* SPEC-11 §3.2.4 linear `(d-30)/120` (`docs/specs/11...md:143-149`). **SPEC-15 thắng** (C¹–smooth, xóa rung lắc).

**(P4) Staleness cutoff** — SPEC-15: `T_stale = MAX_TELEMETRY_STALE_SEC = 300.0s`; `Δt_age > T_stale ⇒ loại xe` (diệt xe ma) (`docs/specs/15...md:181-188`). SPEC-11 không định nghĩa ⇒ áp dụng SPEC-15.

**(P5) Heading/cosine filter** — SPEC-15: khi `v >= HEADING_MIN_SPEED_KMPH=5.0`, loại nếu `cos(Δθ) < HEADING_COS_SIMILARITY_MIN=-0.20` (`docs/specs/15...md:227-242, 416-423`). Dùng `frenet.segment_unit_tangent`.

**(P6) Traffic-status thresholds** — SPEC-15 wins (`docs/specs/15...md:293-298`):
`UN_TAC` nếu `v_obs < CONGESTION_SPEED_THRESHOLD_KMPH=10.0` hoặc `Δt_delay >= 120`; `BINH_THUONG` nếu `10.0 ≤ v_obs < 20.0` và `delay < 120`; `THONG_THOANG` nếu `v_obs ≥ 20.0` và `delay < 30`.
*Xung đột:* code cũ dùng ngưỡng 5/15/20 cho từng xe (`busmap_service.py:902-907`) và 12/20 cho trung bình tuyến (`:945-950`). **SPEC-15 thắng**.

**(P7) Δt_delay & is_delayed** — Lệch SPEC-15 §5.4 (không dùng kinematic): `Δt_delay = max(0, ETA_P50_displayed − baseline_p50)`, tức so ML với prior lịch sử; `is_delayed = Δt_delay >= REALTIME_DELAY_ALERT_SEC=120`. Khôi phục ý nghĩa trường zombie `is_delayed/delay_seconds` (`busmap_service.py:105-106, 918-919`).

**(P8) Dead-reckoning — HOÃN (OUT OF SCOPE đợt này)** — SPEC-15 §3 (mean-reverting relaxation, `λ=ln2/20`, horizon max 90s) thuộc **động lực realtime**. User yêu cầu để sau ⇒ serving dùng vị trí ping thô sau khi lọc (staleness/corridor/heading), **không** nội suy / ngoại suy / bù trễ.

**(P9) ML integration** — XGBoost cung cấp **duy nhất P50** (residual, calibrated); **P10/P90 lấy từ ma trận baseline** (user xác nhận: ML chỉ cho P50). Khi model/feature không khả dụng → fallback `baseline_p50`. Kinematic **chỉ** tồn tại ở lớp đặc trưng nuôi ML (nhóm a/f trong 54 feature), **không** tham gia ước lượng ETA. Điều này supersede vai trò `ETA_kinematic` làm P50 trong SPEC-15 §8.2 (theo chỉ đạo user "3.4 MUST fully serve the ML model").

**(P10) Quantization int minutes** — SPEC-11 §4 `M=ceil(ETA_conservative/60)` (`docs/specs/11...md:158-184`). `display_text`: `"Đang cập bến"` nếu M=0; `"~1 phút"` nếu M=1; `"{M} phút"` nếu M≥2.

**Bảng giải quyết xung đột (tóm tắt):**

| # | Xung đột | Chọn | Lý do |
|---|---|---|---|
| C1 | Band cận bến 10m (SPEC-08/old code) vs [-20,+30]m (SPEC-15) | **SPEC-15** | Mới hơn; chứng minh liên tục; tránh xe biến mất |
| C2 | Buffer hệ số α/β/γ (SPEC-11 vs SPEC-15) | **SPEC-15** | SPEC-15 tuyên bố sửa SPEC-11 |
| C3 | κ(d) linear vs smoothstep | **SPEC-15** | C¹-smooth |
| C4 | `eta_minutes` int (SPEC-11 DoD-ASYM-02) vs float (SPEC-15 §9.2) | **SPEC-11 (int)** | Product dùng int; demo hiển thị song song qua `eta_minutes_precise` (float). Giây chính xác vẫn ở `eta_seconds` |
| C5 | P50 core: ML (SPEC-08 §2.5) vs kinematic (SPEC-15 §8.2) | **ML khi khả dụng** | User: full ML; kinematic chỉ là feature input, không phải estimator; fallback = baseline_p50 |
| C6 | Ngưỡng traffic 5/15/20 vs 10/20 | **SPEC-15** | Chuẩn hóa theo phân vùng động học |

### 2.11. Ba mismatch train/serve phải xử lý (bằng chứng)

- **M1 — Trạm biên:** baseline/feature store dựng trên active corridor `[1..N-1]` (`baseline_matrix_builder.py:82-84`; `feature_store_builder.py:671-673`), còn `get_route_stations` trả toàn bộ trạm `0..N-1` (`busmap_service.py:569-574`). ⇒ Online extractor phải dùng **cùng** `get_active_corridor_stations` logic (tái lập trong `data_access`/`online_features`) để `current_station_order`/`target_station_order` khớp tập train. Trạm 0 xử lý theo SPEC-08 Ca Biên 1.
- **M2 — Fallback speed:** SPEC-15 dùng `5.0 m/s = 18 km/h` (`docs/specs/15...md:158`), tương đương `DEFAULT_URBAN_BUS_SPEED_KMPH/3.6` (`config/system_config.py:226`). Thay `BUS_FALLBACK_CORRIDOR_MPS` (không tồn tại).
- **M3 — Hằng số chiếu:** dùng chung `METERS_PER_DEG_*` + `MAX_CORRIDOR_CROSS_TRACK_M` (không dùng alias không tồn tại).

### 2.12. PHẠM VI HOÃN (OUT OF SCOPE — đợt refactor này)

Theo chỉ đạo user ("động lực realtime là bài toán phức tạp hơn, để sau"), các hạng mục sau **KHÔNG** triển khai:
- Dead-reckoning / mean-reverting relaxation (SPEC-15 §3, mục P8).
- Bù trễ LAN/GPS, nội suy vị trí giữa 2 ping, tweening mượt (SPEC-09).
- Bộ ước lượng ETA động học độc lập (`eta_kinematic`) — chỉ giữ phần feature bắt buộc cho ML.
- Poll interval 5s và `StickyCountdownManager` (SPEC-09/SPEC-11 UI).

Hệ quả: P50 = ML (hoặc fallback baseline); P10/P90 = ma trận baseline. Không có thành phần nào khác tham gia sinh ETA trong đợt này.

---

## 3. MIGRATION MAP CHO `busmap_service.py` (973 dòng)

Ký hiệu: KEEP = giữ nguyên (di chuyển file nếu cần) · MOVE = chuyển sang module mới · REWRITE = viết lại · DELETE = xóa.

| Symbol / Block | Lines | Hành động | Đích | Lý do (1 dòng) |
|---|---|---|---|---|
| Imports `feed`/`config` | 21-30 | **REWRITE** | `live_feed.py`, `data_access.py`, `frenet.py` | **Blocker B1**: `LAT_DEGREE_TO_METERS` (26), `LON_DEGREE_TO_METERS` (27), `BUS_FALLBACK_CORRIDOR_MPS` (28), `CORRIDOR_DEVIATION_METERS` (29) **không tồn tại** trong `config/system_config.py` ⇒ `ImportError` khi import module |
| `HANOI_TZ` | 34 | MOVE | config `TZ_HANOI` | Trùng lặp `TZ_HANOI` (`config:229`) |
| `BusVehicleDTO` | 37-50 | KEEP (sửa) | dto.py | Contract giữ; xóa 2 trường zombie (dưới) |
| ├ `lon` | 44 | **DELETE** | — | Alias trùng `lng`, luôn bằng nhau (`:315`) |
| └ `distance_to_next_m` | 48 | **DELETE** | — | Zombie: luôn gán `None` (`:319`) |
| `RouteItemDTO` | 53-56 | KEEP | dto.py | Contract BusMap route |
| `RouteLiveResponse` | 59-64 | KEEP | dto.py | Contract live |
| `StationItemDTO` | 67-74 | KEEP | dto.py | Contract trạm |
| `RouteStationsResponse` | 77-83 | KEEP | dto.py | Contract trạm |
| `RouteShapeResponse` | 86-93 | KEEP | dto.py | Contract shape |
| `SafeWindowDTO` | 96-107 | **REWRITE** | dto.py | 4 trường zombie: `conservative_eta_seconds` default None (103), `buffer_seconds=0.0` (104), `is_delayed=False` (105), `delay_seconds=0.0` (106) |
| `ApproachingBusDTO` | 110-125 | **REWRITE** | dto.py | `eta_minutes` float→int; `status` chỉ `IN_TRANSIT`; thêm SPEC-15 fields |
| `StationEtaResponse` | 128-140 | KEEP | dto.py | Contract response |
| `normalize_direction` | 143-167 | KEEP/MOVE | dto.py | `app.py:23` phụ thuộc; giữ chữ ký |
| `_now_hanoi_iso` | 170-172 | MOVE | util/live_feed | Dùng `TZ_HANOI` |
| `_parse_ping_epoch` | 175-215 | MOVE | live_feed.py | Logic parse ping giữ nguyên |
| `_live_vehicles_cache` + TTL | 218-220 | MOVE | live_feed.py | TTL 8.0 → config |
| `fetch_live_vehicles_for_route` | 223-335 | MOVE (sửa) | live_feed.py | **Blocker B2** tại dòng 276 |
| └ BBox check | 276 | **REWRITE** | live_feed.py | **Blocker B2**: `HANOI_BBOX["lat_min"/"lat_max"/"lon_min"/"lon_max"]` nhưng config dùng `min_lat/max_lat/min_lon/max_lon` (`config:57-62`) ⇒ `KeyError` khi có xe hợp lệ |
| `class BusMapServingService` | 338-973 | **REWRITE** | serving_service.py | Tách trách nhiệm; thêm ML + extractor |
| ├ `__init__` | 343-366 | REWRITE | serving_service.py | Khởi tạo DataAccess/ModelRuntime/Extractor |
| ├ `_load_baseline_matrix` | 368-402 | MOVE | data_access.py | Logic đúng, giữ; dùng `DEFAULT_DB_PATH` |
| ├ `_load_catalog` | 404-450 | MOVE | data_access.py | Logic đúng, giữ |
| ├ `get_routes` | 452-454 | MOVE | data_access.py | Facade |
| ├ `resolve_route_id` | 456-489 | MOVE | data_access.py | Logic đúng, giữ |
| ├ `get_route_shape` | 491-543 | MOVE | data_access.py | Logic đúng, giữ |
| ├ `get_route_stations` | 545-607 | MOVE | data_access.py | Logic đúng, giữ |
| ├ `get_live_vehicles` | 609-627 | MOVE | serving_service.py | Facade live_feed |
| ├ `_get_shape_projection_model` | 629-679 | **REWRITE** | frenet.py | Hợp nhất hằng số module 1.4; dùng `METERS_PER_DEG_*` |
| ├ `_project_point` | 681-701 | **REWRITE** | frenet.py | Thêm `seg_idx` + tangent cho heading filter |
| ├ `_lookup_baseline_tt` | 703-741 | MOVE | data_access.py | Giữ logic; fallback dùng config constant |
| └ `get_station_eta` | 743-973 | **REWRITE** | eta_policy.py + serving_service.py | ETA composition hiện sai (xem bên dưới) |
| └ `traffic_status` per-bus ngưỡng 5/15 | 902-907 | **DELETE/REWRITE** | eta_policy.py | Thay bằng ngưỡng SPEC-15 |
| └ avg-speed 12/20 | 945-950 | **REWRITE** | eta_policy.py | Thay bằng SPEC-15 |
| └ deadband `s_target-10` | 843 | **DELETE** | — | Thay band `[-20,+30]` SPEC-15 |

**Chú thích zombie fields (tổng hợp):** `BusVehicleDTO.lon` (44), `BusVehicleDTO.distance_to_next_m` (48), `SafeWindowDTO.conservative_eta_seconds` (103 — bị gán = p50 tại 915), `.buffer_seconds` (104 — luôn 0 tại 916), `.is_delayed` (105 — luôn False tại 918), `.delay_seconds` (106 — luôn 0 tại 919), `ApproachingBusDTO.status` (934 — luôn "IN_TRANSIT"), `ApproachingBusDTO.eta_minutes` (929 — float, vi phạm SPEC-11).

---

## 4. FIX LIST CHO STEP 3.5 (thay đổi tối thiểu)

### 4.1. Asset CDN (GIỮ CDN — KHÔNG vendor offline)

**Quyết định của User:** Web Demo **GIỮ CDN** (Leaflet unpkg + Google Fonts + Esri tiles); **KHÔNG** vendor offline, do đó **KHÔNG** tạo `static/vendor/`.

| Vấn đề | Bằng chứng | Xử lý (GIỮ CDN) |
|---|---|---|
| Leaflet CSS từ unpkg CDN | `static/index.html` | **GIỮ** CDN unpkg; KHÔNG tải `leaflet.css` về local |
| Google Fonts Inter từ CDN | `static/index.html` | **GIỮ** CDN Google Fonts; KHÔNG vendor font (woff2) |
| Leaflet JS từ unpkg CDN | `static/index.html` | **GIỮ** CDN unpkg; KHÔNG tải `leaflet.js` về local |
| Tile bản đồ Esri | `static/app.js` | **GIỮ** Esri World Imagery / Street Map trực tuyến |

Ghi chú: giữ nguyên `integrity`/`crossorigin` sẵn có cho các thẻ CDN; không cần route tĩnh `/static/vendor`.

### 4.2. Hợp nhất health contract

| Vấn đề | Bằng chứng | Fix |
|---|---|---|
| Endpoint lệch: server trả `/api/health` | `app.py:64-73` | Thêm alias `/api/v1/health` (route phụ) |
| Launcher gọi `/api/v1/health` và check `status == "healthy"` | `run_demo.ps1:38-39` | Server phải trả `status:"healthy"` (đang trả `"ok"` tại `app.py:68`) |
| Payload server: `{"status":"ok","healthy":true,...}` | `app.py:67-73` | Thống nhất: `{"status":"healthy","healthy":true,...}` và thêm route `/api/v1/health` |

Khuyến nghị: thêm `@app.get("/api/v1/health")` trỏ cùng handler; đổi `"ok"` → `"healthy"` để khớp `run_demo.ps1:39`. `run_demo.bat:5` chỉ uỷ quyền `run_demo.ps1` ⇒ không cần sửa.

### 4.3. HTML escaping (XSS)

Các vị trí nhúng dữ liệu BusMap trực tiếp vào `innerHTML` mà không escape:

| Vị trí | Dữ liệu nhúng | Bằng chứng |
|---|---|---|
| Popup xe | `vehicle.plate`, `next_station_id` | `app.js:122-141` |
| Thẻ xe sidebar | `v.plate` | `app.js:163-172` |
| Badge trạm | `badgeNumber` | `app.js:239-240` |
| Popup trạm | `station.station_name`, `station.address` | `app.js:259-288` |
| Thẻ trạm ghim | `b0.plate`, `b1.plate`, `stName`, `display_text` | `app.js:423-490` |
| Popup ETA trạm | `b0.plate`, `b1.plate`, `display_text`, `recommended_arrival_time` | `app.js:535-555` |

Fix tối thiểu: thêm helper `escapeHtml(str)` (thay `& < > " '`) và bọc **mọi** giá trị chuỗi nguồn BusMap/gold trước khi nội suy template. Không đổi cấu trúc UI.

### 4.4. CORS wildcard + credentials

`app.py:35-41`: `allow_origins=["*"]` + `allow_credentials=True` là tổ hợp **không hợp lệ** (trình duyệt từ chối credentials với wildcard). Fix: đặt `allow_origins=["http://127.0.0.1:8000","http://localhost:8000"]` và `allow_credentials=False` (API public, không cần cookie) — tối thiểu và an toàn.

### 4.5. Dead JS/CSS

| Item | Bằng chứng | Hành động |
|---|---|---|
| `.count-badge` định nghĩa nhưng không dùng | `style.css:453` (0 lần trong html/js) | DELETE |
| `.focus-station-meta` không dùng | `style.css:851` | DELETE |
| `.focus-next-bus` không dùng | `style.css:899` | DELETE |
| `.popup-eta-window` không dùng | `style.css:957` | DELETE |
| `.focus-eta-val.arriving-now` không dùng | `style.css:424` | DELETE (hoặc tái dùng cho badge ARRIVING_NOW nếu coder thêm class) |
| Thiếu CSS `.badge-pulse-green` / `.badge-delay-warning` mà SPEC-11 yêu cầu | `docs/specs/11...md:463` | **CHỈ THÊM nếu làm UI hysteresis**; ngoài scope "fix only" ⇒ ghi chú, không bắt buộc |

**[SUY LUẬN]** `app.js` chưa cài `StickyCountdownManager` (SPEC-11) và hiện hiển thị thẳng `b0.display_text`; do scope 3.5 là "fix only — KHÔNG rewrite UI", việc thêm hysteresis được đưa vào backlog (không nằm trong SPEC-16).

### 4.6. Tests

Hiện `tests/` **rỗng** (đã xác minh). SPEC-16 §6 định nghĩa bộ test black-box cần tạo. Riêng test `W-02` phản ánh quyết định **GIỮ CDN** của User (§4.1): `index.html` vẫn tham chiếu `unpkg.com`/`fonts.googleapis.com` nên KHÔNG kiểm tra offline vendor.

---

## 5. HỢP NHẤT CONFIG / SSOT (`config/system_config.py`)

Mọi magic number hardcode trong 3.4/3.5 phải chuyển về SSOT. Cột "Hằng số đích" ghi hằng đã có hoặc cần thêm.

### 5.1. `busmap_service.py` (→ 3.4 mới)

| Magic number | Bằng chứng | Hằng số đích |
|---|---|---|
| `timezone(timedelta(hours=7))` | `busmap_service.py:34` | `TZ_HANOI` (đã có, `config:229`) |
| `LIVE_CACHE_TTL_SEC = 8.0` | `:220` | **THÊM** `LIVE_CACHE_TTL_SEC` |
| `HANOI_BBOX["lat_min"...]` | `:276` | Sửa key `min_lat/max_lat/min_lon/max_lon` (`config:57-62`) |
| `data/hanoi_bus_system.db` | `:349` | `DEFAULT_DB_PATH` (đã có, `config:30`) |
| `data/metadata/hust_cluster_config.json` | `:350` | `CONFIG_FILE` (đã có, `config:16`) |
| `LON_DEGREE_TO_METERS`, `LAT_DEGREE_TO_METERS` | `:659-660` | `METERS_PER_DEG_LON_EQUATOR`/`METERS_PER_DEG_LAT` (`config:155-156`) |
| `BUS_FALLBACK_CORRIDOR_MPS = 5.0` | `:740` | `DEFAULT_URBAN_BUS_SPEED_KMPH/3.6` (`config:226`) |
| `hour_slot min 21 max 5` | `:772` | `BASELINE_MIN_HOUR_SLOT`/`BASELINE_MAX_HOUR_SLOT` (`config:216-217`) |
| `day_type 0/1/2` | `:771` | `DAY_TYPE_WEEKDAY/SATURDAY/SUNDAY` (`config:218-220`) |
| `CORRIDOR_DEVIATION_METERS = 35` | `:839` | `MAX_CORRIDOR_CROSS_TRACK_M` (`config:158`) |
| Deadband `-10.0` | `:843` | **THÊM** `STATION_ARRIVING_ENTRY_M`/`EXIT_M` (SPEC-15 §7.1) |
| `~10-15 phút` message | `:806, :958` | **THÊM** `NEXT_BUS_HEADWAY_HINT_TEXT` (hoặc để nguyên — thuần hiển thị) |
| Ngưỡng tốc độ xe `5.0/15.0` | `:902-907` | **THÊM** `CONGESTION_SPEED_THRESHOLD_KMPH`, `FREEFLOW_SPEED_THRESHOLD_KMPH` (SPEC-15 §7.1) |
| Ngưỡng tốc độ TB `12.0/20.0` | `:945-950` | Dùng `CONGESTION_SPEED_THRESHOLD_KMPH`/`FREEFLOW_SPEED_THRESHOLD_KMPH` |

### 5.2. Hằng số MỚI bắt buộc thêm (SPEC-15 §7.1, `docs/specs/15...md:358-373`)

`STATION_ARRIVING_ENTRY_M=30.0`, `STATION_ARRIVING_EXIT_M=20.0`, `STATION_BUFFER_ATTEN_MIN_M=30.0`, `STATION_BUFFER_ATTEN_MAX_M=150.0`, `DEAD_RECKONING_TAU_HALF_LIFE_S=20.0`, `DEAD_RECKONING_MAX_HORIZON_S=90.0`, `MAX_TELEMETRY_STALE_SEC=300.0`, `HEADING_MIN_SPEED_KMPH=5.0`, `HEADING_COS_SIMILARITY_MIN=-0.20`, `CONGESTION_SPEED_THRESHOLD_KMPH=10.0`, `FREEFLOW_SPEED_THRESHOLD_KMPH=20.0`, `REALTIME_DELAY_ALERT_SEC=120.0`, `MIN_PHYSICAL_CRAWL_SPEED_MPS=0.556`, `MAX_SAFE_BUFFER_CEILING_SEC=180.0`.
Thêm cho buffer & physics: `BUFFER_ALPHA_SIGMA=0.60`, `BUFFER_BETA_TELEMETRY=0.5`, `TELEMETRY_HEARTBEAT_SEC=15.0`, `BUFFER_GAMMA_HORIZON=0.04`, `MAX_CORRIDOR_CROSS_TRACK_M` (đã có), `EGO_SPEED_WEIGHT_OBS=0.75`, `CONGESTION_PROP_MAX=2.5`, `CONGESTION_PROP_EXP=0.5`.
Thêm cho online features: `RECENT_PROBE_WINDOW_SEC=1800.0` (`feature_store_builder.py:70`), `FLEET_ACTIVE_WINDOW_SEC=300.0` (`:71`), `MIN_EGO_SAMPLE_ADVANCE_M=150.0` (`:72`), `PROCESS_POOL` không cần. Physics blend: `PHYS_W_PROBE=0.35`, `PHYS_W_EGO=0.20`, `PHYS_DECAY_M=2500.0`, `PHYS_INC_DELAY_FACTOR=0.25`, `PHYS_INC_DELAY_CAP=180.0` (`feature_store_builder.py:531-539`).

### 5.3. `step_3_5` (app.py / static)

| Magic number | Bằng chứng | Hằng số đích |
|---|---|---|
| `port 8000` (uvicorn) | `app.py:207`, `run_demo.ps1:30` | **THÊM** `WEB_DEMO_PORT=8000` (hoặc để nguyên; thuộc launcher) |
| `POLL_INTERVAL_MS=15000` | `app.js:10` | **THÊM** `DEMO_POLL_INTERVAL_MS` nếu muốn SSOT; hiện là hằng client |
| Tile URL Esri | `app.js:66,75` | `OSM_TILE_SERVERS["esri_sat"]` (`config:121-128`) — **[SUY LUẬN]** client khó import Python; có thể expose qua endpoint config |

### 5.4. Cảnh báo phạm vi frozen

SPEC-15 §7.2 yêu cầu xóa biến TimBus/alias khỏi config (`docs/specs/15...md:375-378`). Kiểm tra: các biến này **không tồn tại** trong `config/system_config.py` hiện tại (grep xác nhận), và **không** có file Python nào ngoài `busmap_service.py` import chúng (grep chỉ thấy trong docs + `busmap_service.py:26-29`). ⇒ Việc "xóa" thực chất là **sửa import sai** trong `busmap_service.py`. **Không** chỉnh config vì lý do này, tránh chạm module frozen.

---

## 6. TEST PLAN (cho `@blind_tester`) — black-box, suy từ spec

Tất cả test dựng từ **hợp đồng** (§1) + spec (08/11/15), KHÔNG đọc code cài đặt. Dùng `fastapi.testclient.TestClient` (mẫu: `scratch/test_edge_cases_blackbox.py:5-8`).

### 6.1. Files

```
tests/
├── conftest.py                                  # fixture client + frozen data probes
├── test_eta_contract_spec08_blackbox.py
├── test_conservative_asymmetric_eta_blackbox.py # SPEC-11 (DoD-ASYM-01..09)
├── test_spec15_kinematics_and_serving.py        # SPEC-15 (TC-01..10)
├── test_online_feature_extractor_blackbox.py    # 54 feature + cold-start
└── test_web_demo_fixes_blackbox.py              # SPEC-16 §4 fixes
```

### 6.2. Test cases & tiêu chí

**(T) Hợp đồng & schema (SPEC-08)**
| ID | Input | Pass |
|---|---|---|
| T08-01 | `GET /api/station-eta?route=02&direction=0&station_order=5` | 200; đủ `route_id, route_code, direction, target_station, approaching_count, buses` |
| T08-02 | mọi bus trả về | `0 ≤ p10 ≤ p50 ≤ p90`; `distance_to_station_m>0`; `stops_remaining≥0` |
| T08-03 | so `/api/live-vehicles` | 100% xe approaching nằm trong live cùng chiều; không xe nào `s_bus>s_target+30m` |
| T08-04 | `station_order=0` / `=N-1` | 0 trả `buses=[]`; N-1 trả đủ xe lưu thông |
| T08-05 | 50 truy vấn liên tiếp | P95 ≤ 20 ms |

**(T) SPEC-11 (DoD-ASYM)** — `test_conservative_asymmetric_eta_blackbox.py`
`ASYM-01` `conservative_eta_seconds ≥ p50_seconds` và `buffer_seconds ≥ 0`.
`ASYM-02` `eta_minutes` là `int` và `== ceil(conservative_eta_seconds/60)`.
`ASYM-03` `display_text` khớp bảng M (§2.10-P10).
`ASYM-04` với `d≤30m`: `status=="ARRIVING_NOW"`, `eta_seconds==0`, `buffer_seconds==0`.
`ASYM-05/06` hysteresis (client) — kiểm tra qua payload `is_delayed`.
`ASYM-07` `recommended_arrival_time` ≤ (now + p50).
`ASYM-08` backward-compat các trường SPEC-08.
`ASYM-09` P95 latency ≤ 20 ms.

**(T) SPEC-15** — `test_spec15_kinematics_and_serving.py` (TC-01..10, `docs/specs/15...md:661-672`)
TC-01 d=8m → ARRIVING_NOW, count=1; TC-02 d=+12m → ARRIVING_NOW; TC-03 d=+25m → count=0;
TC-04 Δt_age=400s → count=0; TC-05 xe ngược chiều cos≈-1 → count=0; TC-06 kẹt cứng → `UN_TAC`, `is_delayed`, `delay>120`, `eta>180`;
TC-07 Δt_age=60s → `s_now>s_ping+300m`; TC-08 liên tục tại d=31/29m; TC-09 config không chứa `TIMBUS_`; TC-10 M đơn điệu theo d.

**(T) Online feature extractor** — `test_online_feature_extractor_blackbox.py`
- `FE-01` vector trả đủ 54 khóa đúng tên `ALL_54_FEATURES` (§1.3.2), đúng kiểu categorical cho 4 cột.
- `FE-02` cold-start 1 ping: `v_roll3==v_roll5==v_inst`, `accel==0`, `rec_cov_ratio==0`, `rec_cong_ratio==1` (SPEC-09 §4.2).
- `FE-03` hội tụ: sau ≥5 ping, `v_roll3` sai số `<2%` so công thức `feature_store_builder.py:331` (SPEC-09 AC-09-03).
- `FE-04` `baseline_eta_p50_sec` khớp tra cứu prefix-sum (`feature_store_builder.py:486`).

**(T) Model runtime & fallback**
- `MR-01` với model r3_big + calibrator: `predict_p50` = `max(5, base+delta)` rồi calibrate (đối chiếu `eta_model_trainer.py:299-324`).
- `MR-02` khi artifact thiếu/corrupt → `available==False`, serving trả `p50=baseline_eta_p50`, HTTP 200 (không 500).

**(T) Fix 3.5** — `test_web_demo_fixes_blackbox.py`
- `W-01` `GET /api/health` và `/api/v1/health` đều trả `status=="healthy"` (khớp `run_demo.ps1:39`).
- `W-02` `index.html` **giữ** tham chiếu `unpkg.com`/`fonts.googleapis.com` (GIỮ CDN theo quyết định của User, §4.1).
- `W-03` payload có ký tự `<script>` trong `station_name`/`plate` ⇒ HTML render escape (test hàm `escapeHtml` hoặc quét template).
- `W-04` CORS: response với `Origin` không dùng `*` + credentials.

### 6.3. Điều kiện thành công tổng

- Toàn bộ DoD-ASYM + TC-01..10 + FE/MR/W pass.
- Không sửa file frozen; diff chỉ trong `step_3_4`, `step_3_5`, `config/system_config.py`.
- Fallback baseline hoạt động khi model vắng mặt (MR-02) — bảo đảm "safe fallback".

---

## 7. WORK BREAKDOWN (thực thi) & PHỤ THUỘC

> **Phụ thuộc bất biến:** `step_3_1`, `step_3_2`, `step_3_3`, `module_1`, `module_2` là FROZEN. Mọi task dưới đây coi schema §1 là cố định; nếu phát hiện lệch schema so với §1 → DỪNG và báo `@architect` (không tự sửa upstream).

| # | Task | Verify |
|---|---|---|
| 0 | Xác nhận `import` module 3.4 hiện đang **lỗi** (blocker B1/B2) bằng cách chạy `python -c "import module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.busmap_service"` | Reproduce `ImportError` |
| 1 | Thêm hằng số §5.2 vào `config/system_config.py` (không xóa gì) | `python -c "import config.system_config"` OK |
| 2 | Tạo `dto.py` (schema §2.2), gồm sửa zombie fields | Unit: khởi tạo DTO, `eta_minutes` int |
| 3 | Tạo `data_access.py` (MOVE `busmap_service.py:368-607, 703-741`) | Truy vấn routes/shape/stations/baseline trả đúng |
| 4 | Tạo `live_feed.py` (MOVE `:175-335`), sửa BBox keys (B2) | Fetch live thật, không `KeyError` |
| 5 | Tạo `frenet.py` (§2.5), dùng chung hằng số module 1.4 | So `s_bus` với `multi_route_projector.project_points_to_shape` trên cùng điểm: sai số `<1e-3 m` |
| 6 | Tạo `online_features.py` (§2.6) + cold-start inversion | FE-01..04 pass |
| 7 | Tạo `model_runtime.py` (§2.7), load `_r3_big` + calibrator | MR-01/02 pass |
| 8 | Tạo `eta_policy.py` (§2.8) theo P1-P7/P9/P10 (P8 hoãn) | TC-01..10 pass |
| 9 | Tạo `serving_service.py` (§2.9), ghép ML làm P50 core | ASYM + T08 pass |
| 10 | Cập nhật `app.py` import facade + health `/api/v1/health` + CORS (§4.2, §4.4) | W-01, W-04 pass |
| 11 | Giữ CDN (§4.1) + escape HTML (§4.3) + xóa dead CSS (§4.5) | W-02/03 pass |
| 12 | Chạy full test suite §6 | Tất cả pass |

**Definition of Done:** 3.4 phục vụ ML XGBoost (calibrated) với fallback baseline an toàn; 3.5 đã fix các lỗi UI/ops; không chạm mã frozen; mọi hằng số về SSOT.

---

*Hết SPEC-16. Mọi số liệu và đường dẫn trong tài liệu được trích trực tiếp từ mã nguồn/dữ liệu tại thời điểm ban hành. Các mục `[SUY LUẬN]` cần `@orchestrator` xác nhận trước khi `@leaf_coder` triển khai.*
