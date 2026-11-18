# Kiểm toán Live Web Demo & Đề xuất xử lý cụm `lead_bus` / `follow_bus` (2026-11-18)

## 1. Bối cảnh & Dữ liệu thu thập
- **Nguồn dữ liệu:** 65 ticks thu thập từ web app demo chạy thực tế tại `127.0.0.1:8018` (`runtime/live_audit_20261118/`), theo kịch bản chuyển tuyến trong `collect_and_switch.py` (`32` -> `02` -> `66` -> `32`).
- **RAM Client (`module_3_bus_eta_prediction/step_3_5_web_demo/static/app.js`):** Không gây rò rỉ dữ liệu tuyến cũ khi chuyển tuyến nhờ `routeGeneration` và dọn layer/marker theo tuyến.
- **Cold-start / Quá hạn khi đổi tuyến:** Cần `MIN_SPEED_WINDOW = 30.0s` để có `ego_speed` và hết hạn sau `MAX_POSITION_AGE = 90.0s` do đánh đổi giữa kiến trúc client-driven và politeness với upstream. *(Tạm gác lại, chưa thay đổi).*

---

## 2. Các bất thường ghi nhận trên `lead_bus` / `follow_bus`

### 2.1. Nhảy qua ngưỡng cứng `d > 20m` trong `_fleet()` (`causal_eta.py`)
- `_fleet()` dùng ngưỡng cắt cứng `d > 20` và `d < -20` để chọn 1 xe `ahead[0]` và 1 xe `behind[0]`.
- **Ca `29F-051.06` (tuyến 32):**
  - Nhịp `t=63` (`qe=1795003787.3`): `29F-052.68` (`2.2 km/h`, `p50=619.8s`) ở `s=8708.7` cách `29F-051.06` (`9.3 km/h`) ở `s=8688.1` đúng **`20.6m > 20m`** -> thay thế `29F-051.80` (`2598.5m`, `13.1 km/h`). `p50` của `29F-051.06` nhảy **`620.2s -> 768.5s` (`+148.3s`)**, tạo nghịch lý xe sau `20.6m` có `p50` lớn hơn xe trước **`148.7s`**.
  - Nhịp `t=64` (`qe=1795003793.1`): khoảng cách rút còn **`9.7m <= 20m`** -> `29F-052.68` rớt khỏi `ahead`, `lead_bus` quay lại `29F-051.80` (`2602.5m`) -> `p50` tụt **`768.5s -> 613.9s` (`-154.6s`)**.
- **Ca `29F-052.00` (tuyến 32):** Nhảy `+163.5s` ở `t=14` (`gap=25.0m`, `lead_bus_speed_ratio: 0.723 -> 0.124`, SHAP `+97.43s` + `lead_bus_dist_ahead_m` `+30.07s`) cùng 7 cú nhảy khác quanh vùng `15–28m`.

### 2.2. Nhảy lúc warm-up (`lead_bus_speed_ratio: None -> ~0.008`)
- `29F-052.68` (`t=8`): `p50` nhảy `735.9s -> 835.7s` (**`+99.8s`**), `lead_bus_speed_ratio: None -> 0.0077` (SHAP `+77.32s`).
- `29F-051.30` (`t=13`): `p50` nhảy `1879.0s -> 1971.3s` (**`+92.3s`**), `lead_bus_speed_ratio: None -> 0.0093` (SHAP `+72.21s`).

### 2.3. Quy luật đóng góp SHAP của 7 feature đội xe (`fleet_shap_rules.py`, `sweep_3d.py`)
- Trên `379` mẫu trace:
  - Tác động nhỏ (`±0.2..±5s`): `lead_bus_speed_kmh` (`[-3.7, +4.8]s`), `follow_bus_speed_kmh` (`[-1.6, +0.2]s`), `n_active_buses_on_route` (`[-2.6, +3.3]s`).
  - Độ lệch nền & tinh chỉnh vừa: `n_buses_in_corridor_ahead` (`[+12.0, +41.7]s`, p50 `+26.2s`), `follow_bus_dist_behind_m` (`[-6.9, +9.5]s`).
  - Chi phối biến động lớn: `lead_bus_speed_ratio` (`[-13.6, +101.1]s`, std `16.3s`) và `lead_bus_dist_ahead_m` (`[-11.8, +33.0]s`).
- Sweep 3 chiều `(ego_speed × lead_dist × lead_ratio=0.15)` cho thấy `lead_bus_speed_ratio <= 0.15` kích hoạt mức phạt `+68..+103s` trên mọi khoảng cách (`21m..2500m`) và gần như không phụ thuộc `ego_speed` (`0..22 km/h`).

---

## 3. Kết quả các thí nghiệm đối chứng

### 3.1. Thử nghiệm Phương án C1 — Proximity Cap (`test_option_c.py`)
- Trên 65 tick (`http.jsonl`), có `17` cú nhảy `|Δp50| >= 40s` (gồm `4` cú tại `t=56` do nghỉ 60s chuyển tuyến, và `13` cú đơn nhịp 5s).
- Áp dụng `behind.p50 <= ahead.p50 + gap / 2.5 + 15.0` cho `gap <= d_prox`:
  - `d_prox = 40m`: 10 lượt chỉnh -> còn 5 cú nhảy đơn nhịp.
  - `d_prox = 60m`: 13 lượt chỉnh -> còn 6 cú nhảy (biên `60m` tự sinh thêm 1 cú nhảy `-48.8s` tại `t=31`).
  - **`d_prox = 80m` và `100m`**: 21–22 lượt chỉnh -> **triệt tiêu 10/13 cú nhảy đơn nhịp** (toàn bộ chuỗi nhảy của `29F-051.06` và `29F-052.00`); chỉ còn 3 cú không do cặp xe gần (`t=8 +99.8s`, `t=13 +92.3s`, `t=14 -41.7s`).
- Lưu ý: Không ép sàn dưới (`behind >= ahead`) để giữ khả năng vượt xe thật; Phương án C chỉ đóng vai trò lưới an toàn đầu ra vì phụ thuộc vào độ chuẩn của `ahead` và không xử lý được trường hợp chính `ahead` tự nhảy lúc warm-up.

### 3.2. Ablation trên 4,000,961 dòng test & Retrain mẫu 12.5% (`ablation_fleet.py`)
**Part 1 — Masked Ablation trên toàn bộ 4,000,961 dòng test (`causal_eta_v1`):**
| Biến thể | MAE | MdAE | P90 | Bias |
|---|---:|---:|---:|---:|
| `original (36 feats)` | 141.26s | 84.68s | 336.82s | -3.26s |
| `clip lead_ratio >= 0.25` | 141.28s | 84.68s | 336.84s | -3.51s |
| `mask lead_speed_ratio` | 142.30s | 85.26s | 339.46s | -1.69s |
| `mask lead_dist_ahead` | 142.82s | 86.91s | 337.50s | +7.08s |
| `mask both lead ratio+dist` | 144.25s | 87.97s | 340.78s | +10.07s |
| `mask ALL 7 fleet feats` | 149.97s | 96.92s | 343.73s | +31.38s |

- Lát cắt `lead_dist <= 50m & lead_ratio <= 0.20` chỉ chiếm **`498 / 4,000,961` (`0.01%`)**, với `MAE = 182.06s`, `MdAE = 145.97s`, `Bias = +28.85s`.

**Part 2 — True Retrain Ablation (mẫu 12.5% theo `journey`, 630,288 train / 454,671 val / 504,201 test, `max_depth=6`):**
| Biến thể | `best_iter` | MAE | MdAE | P90 | Bias |
|---|---:|---:|---:|---:|---:|
| `retrain full (36)` | 248 | 149.09s | 89.92s | 353.51s | +0.15s |
| `retrain no lead_ratio` | 350 | 149.22s | 90.24s | 353.65s | +1.36s |
| `retrain no lead_dist` | 315 | 149.25s | 90.43s | 354.45s | +1.30s |
| `retrain no fleet (7)` | 223 | 151.76s | 92.77s | 356.55s | +1.57s |

### 3.3. Kiểm chứng dịch chuyển xung nhảy khi bỏ `lead_bus_speed_ratio` (`check_shift_hypothesis.py`)
- `29F-051.06` (`20m` flip-flop): `+109.0s` -> **`+92.3s`** (xung nhảy dịch sang `lead_bus_speed_kmh: +44.2s` và `lead_bus_dist_ahead_m: +31.7s`).
- `29F-052.00` (`25m` flip-flop): `+73.6s` -> **`+25.0s`**.
- `29F-052.68` (warm-up `None -> 0.008`): `+55.8s` -> **`+16.4s`**.
- `29F-051.30` (warm-up `None -> 0.009`): `+77.0s` -> **`-2.0s`**.

---

## 4. Hướng giải quyết đề xuất (đã ghi nhận, chưa chỉnh sửa code)

1. **Giai đoạn 1 (Ngắn hạn — không retrain):**
   - Bổ sung **Proximity Sanity Cap** ở tầng serving cho các xe cùng tuyến/chiều/trạm đích trong phạm vi `gap <= 80–100m` (có chuyển tiếp mượt ở vùng biên để tránh bước nhảy tại `d_prox`, chỉ chặn trần trên, đồng bộ `safe_window`).
   - Giữ nguyên toàn bộ 36 feature và model `causal_eta_v1` cho 99.99% các ca còn lại.

2. **Giai đoạn 2 (Dài hạn — khi retrain bản tiếp theo):**
   - Giữ thông tin xe gần nhất, đồng thời **bổ sung đặc trưng tốc độ hành lang phía trước tới trạm đích** ($0 < d \le s_{\text{target}} - s_{\text{ego}}$, trọng số giảm mượt theo khoảng cách) để XGBoost tự phân biệt giữa 1 xe tấp trạm cục bộ và tắc cả hành lang mà không cần luật biên hard-code.
   - Đánh giá đưa `lead_bus_speed_ratio` vào `MONOTONE_SPEED_FEATURES = -1` (giống `lead_bus_speed_kmh`) hoặc kiểm chứng lại mức đóng góp sau khi có biến hành lang phía trước.
