# 23. PHẢN BIỆN CHUYÊN GIA ML: CÁC QUYẾT ĐỊNH KIẾN TRÚC CUỐI CÙNG (ML EXPERT ANSWERS & FINALIZED ARCHITECTURE DECISIONS)

> **Mục tiêu tài liệu:** Ghi lại toàn bộ phản biện chuyên sâu và các quyết định kiến trúc đã được chốt cho hệ thống dự đoán ETA xe buýt Hà Nội, dựa trên tham vấn từ tài liệu `22_ML_EXPERT_CONSULTATION_DOSSIER.md`.

---

## Câu Hỏi 1: Lựa Chọn Mô Hình (Model Selection)

### Verdict: **LightGBM đơn lẻ. Không Stacking Ensemble.**

### Luận chứng so sánh

| Tiêu chí | LightGBM | CatBoost | XGBoost | TabNet / MLP |
| :--- | :---: | :---: | :---: | :---: |
| Tốc độ train (~3M rows) | ✅ Nhanh nhất | ⚠️ Chậm hơn 2–4× | ⚠️ Chậm hơn 1.5× | ❌ Cần GPU, 10× chậm |
| Inference latency | **< 0.05ms** | ~0.1ms | ~0.1ms | 1–5ms |
| Tabular data (23 dim) | ✅ Tối ưu | ✅ Tốt | ✅ Tốt | ❌ Under-parameterized |
| NaN Native Handling | ✅ Có | ✅ Có | ⚠️ Partial | ❌ Không |
| Regularization built-in | ✅ `min_data_in_leaf` | ✅ L1/L2 | ✅ | ❌ Cần dropout tuning |

### Cấu hình khuyến nghị

```python
params = {
    "objective":        "huber",       # Xem Q2 — Loss Function
    "alpha":            0.9,           # tham số Huber
    "num_leaves":       127,           # 2^7 - 1; tăng lên 255 nếu vẫn underfit
    "learning_rate":    0.03,
    "n_estimators":     3000,          # + early_stopping_rounds=100
    "min_data_in_leaf": 200,           # chống overfit cho chặng ít xuất hiện
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq":     5,
    "verbose":         -1,
}
```

### Về Stacking Ensemble

Với 2–3M mẫu tabular, LightGBM được tune kỹ chiếm 95%+ hiệu năng của một Ensemble đầy đủ. Chi phí vận hành tăng gấp đôi nhưng gain thực tế < 1% RMSE. **Không đáng đầu tư.**

---

## Câu Hỏi 2: Hàm Mất Mát (Loss Function Optimization)

### Verdict: **Huber Loss (delta = 30s) để train + hệ số buffer ×1.10 cho display hành khách.**

### Phân tích bất đối xứng

Bài toán có **hai loại lỗi mang hệ quả khác nhau hoàn toàn:**

- **Under-prediction** (dự báo xe đến muộn hơn thực tế): Hành khách đứng chờ thêm → gây khó chịu.
- **Over-prediction** (dự báo xe đến sớm hơn thực tế): Hành khách **lỡ xe** → mất 10–20 phút chờ chuyến tiếp → hậu quả nặng hơn nhiều.

### Tại sao KHÔNG dùng MSE thuần

- MSE phạt ngang nhau hai chiều → tối ưu cho điểm trung tâm phân phối, không phản ánh bất đối xứng.
- Target $\Delta T \geq 0$ có đuôi phải rất nặng (kẹt xe đột biến) → MSE bị kéo mạnh bởi outlier.

### Tại sao KHÔNG dùng Quantile τ=0.75 duy nhất

Quantile Loss tối ưu cho một phân vị cụ thể, không tối ưu cho Mean Error → bias có hệ thống, không phù hợp để tổng hợp ETA trên nhiều chặng (sai số sẽ tích lũy theo chiều bảo thủ ở mỗi chặng).

### Kiến trúc hai lớp đầu ra

| Layer | Mục đích | Cách implement |
| :--- | :--- | :--- |
| **Model backbone (Huber)** | Dự đoán median delay để tổng hợp ETA nội bộ | Train LightGBM với `objective="huber"`, `delta=30s` |
| **Display buffer** | Hiển thị cận trên an toàn cho hành khách trên app | `ETA_display = ETA_backbone × 1.10 + 45s` (không cần train model riêng) |

> **Lý do Huber hơn MSE:** `delta = 30s` tương đương "bỏ qua gradient của outlier kẹt cứng > 30 giây khi tối ưu hóa" — model học tốt phân phối thông thường mà không bị lệch bởi 2–3% kẹt cực đoan.

---

## Câu Hỏi 3: Chiến Lược Chia Tập & Chống Rò Rỉ Dữ Liệu (Validation Strategy)

### Verdict: **Time-based Split cứng + Gap 6 giờ + Purge 15 phút cho probe features.**

### Sơ đồ chia tập

```
[Ngày 1 ──────── Ngày 30] [GAP 6h] [Ngày 31──── Ngày 38] [GAP 6h] [Ngày 39──── Ngày 45]
         TRAIN                           VALIDATION                       TEST
         ~2.1M mẫu                        ~560K mẫu                    ~420K mẫu
```

> **Tại sao Gap 6 giờ?** Feature `segment_cross_route_delay_30m` tổng hợp 30 phút gần nhất. Không có gap, mẫu validation sẽ "nhìn thấy" outcome của mẫu train cuối thông qua aggregated probe → data leakage.

### Ba nguồn Data Leakage nguy hiểm nhất

| Nguồn Leakage | Cơ chế | Cách xử lý |
| :--- | :--- | :--- |
| `segment_cross_route_delay_30m` | Aggregation 30p → có thể dùng timestamp tương lai khi build feature | **Strict lag:** chỉ dùng data $t_{now} - 30\text{ min}$ trở về trước |
| `cumulative_trip_delay_sec` | Trong cùng một trip, segment sau "biết" kết quả segment trước | **Không phải leakage** — đây là causal feature hợp lệ; xe đã trễ thì tiếp tục trễ |
| `lead_bus_delay` của xe đi sau | Xe A (đi trước) có thể xuất hiện trong feature của Xe B (đi sau) trong cùng khung giờ | **Purge by trip:** loại tất cả mẫu cùng chặng trong window $\pm 15\text{ min}$ xung quanh trip của xe probe khỏi validation |

### Về Blocked Cross-Validation

Không cần thiết với 45 ngày dữ liệu. Blocked CV phù hợp khi dataset < 2 tuần. Time-based Split đơn giản hơn và ít rủi ro implementation hơn.

---

## Câu Hỏi 4: Xử Lý Cold-Start & Giá Trị Thiếu (Imputation & Edge Cases)

### Verdict: **LightGBM Native NaN Handling. Không impute thủ công.**

### Tại sao Native NaN là lựa chọn đúng

LightGBM xử lý NaN bằng cách tìm **hướng split tối ưu** cho các sample NaN trong quá trình training. Nó *học được* rằng khi `lead_bus_delay = NaN` và `has_lead_bus_probe = 0` → không có thông tin probe → model tự rơi về prior thống kê. Đây là cách nhất quán và chính xác nhất.

### Nguy cơ của Imputation thủ công

| Chiến lược | Vấn đề |
| :--- | :--- |
| **Impute = 0** | Nói với model "xe đầu ngày có delay = 0s" → **Sai hoàn toàn** (unknown ≠ 0) |
| **Impute = mean** | Gán thông tin giả tạo → model tin rằng có probe khi không có → dự báo lệch hệ thống |

### Pattern implementation chuẩn

```python
# ─── Cold-start (05:00 sáng, chuyến đầu tiên) ───
has_lead_bus_probe            = 0
lead_bus_delay                = float("nan")   # LightGBM tự xử lý
lead_bus_age_min              = float("nan")   # LightGBM tự xử lý
segment_cross_route_delay_30m = float("nan")   # chưa có xe nào qua

# ─── Chuyến thông thường (có probe đi trước) ────
has_lead_bus_probe            = 1
lead_bus_delay                = 45.2           # giây
lead_bus_age_min              = 18.5           # phút
segment_cross_route_delay_30m = 32.1           # giây (trung bình 30p)
```

> **Quan trọng:** `has_lead_bus_probe` vẫn giữ nguyên dù có Native NaN, vì nó encode **lý do cấu trúc** của việc thiếu — cold-start (có thể dự đoán theo pattern) vs. lỗi hệ thống ngẫu nhiên (không dự đoán được). Model sẽ học hai "chế độ vận hành" khác nhau một cách tường minh.

---

## Câu Hỏi 5: Điểm Yếu Ẩn & Rủi Ro Thiết Kế (Latent Pitfalls)

---

### 🔴 Pitfall 1 — `tomtom_delay_contrib` phát nổ khi tắc cứng (CRITICAL)

**Cơ chế:**

$$\Delta t_{tomtom} = L_{overlap} \times \left(\frac{1}{v_{tomtom}} - \frac{1}{v_{free}}\right) \xrightarrow{v_{tomtom} \to 0} +\infty$$

Khi TomTom báo kẹt cứng (`v_tomtom ≈ 2 km/h`), giá trị feature có thể đạt hàng nghìn giây cho một chặng 600m — outlier cực trị phá vỡ phân phối gradient boosting.

**Fix bắt buộc:**

```python
v_tom   = max(v_tomtom_current, 3.0)      # floor 3 km/h (~đi bộ nhanh)
v_free  = max(v_free_flow,      15.0)     # floor 15 km/h để tránh phân mẫu số âm
tomtom_delay_contrib = L_overlap * (1/v_tom - 1/v_free)
tomtom_delay_contrib = min(tomtom_delay_contrib, 600.0)   # hard cap 10 phút
```

---

### 🔴 Pitfall 2 — Target $\Delta T \geq 0$ có phân phối Zero-Inflated (CRITICAL)

**Cơ chế:** Phân phối thực tế của $\Delta T_{delay}$:
- **~40–50% mẫu:** $\Delta T = 0$ (đường thông, xe chạy nhanh hơn $T_{base}$).
- **Đuôi phải nặng:** ~2–5% mẫu có $\Delta T > 300\text{s}$ (kẹt xe nặng).

Regression thông thường sẽ predict giá trị âm cho chặng vắng; phải clamp về 0 gây **discontinuity** tại ranh giới — model không học được ranh giới "kẹt / thông" sắc nét.

**Fix được khuyến nghị — Log-transform target:**

$$y' = \log\!\left(1 + \Delta T_{delay}\right)$$

Train trên $y'$, inverse transform khi predict:

$$\hat{\Delta T} = e^{\hat{y}'} - 1$$

Phân phối log-normal phù hợp với delay dương, giảm ảnh hưởng của outlier kẹt nặng, và tự động đảm bảo $\hat{\Delta T} \geq 0$ sau inverse transform.

> **Lưu ý:** Khi dùng log-transform, toàn bộ metric đánh giá (RMSE, MAE) phải được tính trên **không gian gốc** (giây), không phải không gian $\log$.

---

### 🟡 Pitfall 3 — `road_quality_index` bị ô nhiễm theo mùa thu thập (IMPORTANT)

**Cơ chế:** $Q_{road}(k) = v_{base}(k) / v_{limit}$, trong đó $v_{base}$ được tính từ quantile 5h sáng trong 45 ngày dữ liệu. Nếu 45 ngày này rơi vào mùa mưa hoặc giai đoạn sửa đường, $v_{base}$ thấp bất thường → `road_quality_index` bị underestimate có hệ thống trên các chặng bị ảnh hưởng.

**Fix:** Tính $v_{base}$ dùng cho `road_quality_index` từ **top-percentile tốc độ** (ví dụ: Q80 của tốc độ đo được trong 5h–6h), không dùng Q15 (Q15 dành cho $T_{base}$ — hai thứ hoàn toàn khác nhau). Hoặc lấy tốc độ giới hạn `v_limit` từ OpenStreetMap (`maxspeed` tag) thay vì ước lượng từ dữ liệu cào.

---

### 🟡 Pitfall 4 — `segment_cross_route_delay_30m` bị Spatial Mismatch (IMPORTANT)

**Cơ chế:** Feature này giả định xe các tuyến khác đi qua **cùng đoạn đường vật lý**. Với GPS accuracy 10–30m và đường hẹp Hà Nội, nếu dùng bounding box đơn giản (lat/lon ± threshold) sẽ bắt nhầm xe trên đường song song cách nhau 20–30m.

**Fix:** Dùng **H3 hexagon index (resolution 11 ≈ 25m cell)** để group xe cùng chặng thay vì bounding box hình chữ nhật. Hoặc map-match toàn bộ GPS trace về road network graph trước khi tổng hợp.

---

### 🟡 Pitfall 5 — `headway_ratio` khi tuyến không có lịch trình (IMPORTANT)

**Cơ chế:** Một số tuyến Hà Nội không publish timetable. `H_scheduled = NaN → headway_ratio = NaN`. Đây là NaN **cấu trúc vĩnh viễn** (toàn bộ tuyến đó), khác với NaN **tạm thời** của cold-start. LightGBM sẽ học chung một chiến lược NaN cho cả hai → miscalibrated predictions.

**Fix:** Thêm cờ `has_schedule` (binary) song song. Khi không có lịch chính thức, tính `headway_ratio` dựa trên **actual rolling median giãn cách thực tế** của tuyến đó trong 7 ngày gần nhất.

---

### ⚪ Pitfall 6 — `direction` và `route_progress_ratio` collinear theo tuyến (LOW)

**Cơ chế:** Với tuyến một chiều hoặc tuyến vòng, `direction = 0` luôn có `route_progress_ratio` tăng 0→1, và ngược lại. Correlation giữa hai feature sẽ cao nhưng LightGBM xử lý được collinearity thông qua feature subsampling.

**Không cần fix**, nhưng cần monitor feature importance sau training để đảm bảo cả hai không bị ignore hoàn toàn.

---

## Tổng Hợp Quyết Định Kiến Trúc Cuối Cùng

| # | Vấn đề | Quyết định chốt | Mức ưu tiên |
| :---: | :--- | :--- | :---: |
| Q1 | Model Selection | **LightGBM đơn lẻ**, `num_leaves=127`, `n_estimators=3000`, `early_stopping=100` | ✅ Chốt |
| Q2 | Loss Function | **Huber (delta=30s)** để train + `ETA_display = ETA × 1.10 + 45s` cho hành khách | ✅ Chốt |
| Q3 | Validation | **Time Split** Ngày 1–30 / 31–38 / 39–45 + Gap 6h + Purge probe window 15 phút | ✅ Chốt |
| Q4 | Cold-start NaN | **LightGBM Native NaN** + giữ `has_lead_bus_probe` flag | ✅ Chốt |
| P1 | `tomtom_delay_contrib` | Clamp: floor `v_tomtom ≥ 3 km/h`, hard cap 600s | 🔴 Fix ngay |
| P2 | Zero-inflated target | **Log-transform:** $y' = \log(1 + \Delta T)$, evaluate trên space gốc | 🔴 Fix ngay |
| P3 | `road_quality_index` bias | Dùng Q80 tốc độ hoặc `maxspeed` OSM thay vì Q15 cào | 🟡 Fix trước train |
| P4 | Spatial mismatch probe | Dùng **H3 resolution 11** thay vì bounding box | 🟡 Fix trước train |
| P5 | `headway_ratio` thiếu lịch | Thêm `has_schedule` flag + actual rolling median fallback | 🟡 Fix trước train |
| P6 | Collinearity direction | Monitor feature importance — không cần can thiệp | ⚪ Theo dõi |

---

## Bộ Đặc Trưng Cập Nhật Sau Pitfall Analysis (23 + 1 Chiều)

Sau khi xử lý Pitfall 5, bộ đặc trưng cần thêm **1 chiều bổ sung**:

| STT | Tên đặc trưng | Nhóm | Ghi chú |
| :---: | :--- | :--- | :--- |
| 24 | `has_schedule` | IV — Đội xe & Probe | Binary: 1 nếu tuyến có timetable chính thức, 0 nếu chạy theo tần suất thực tế |

> Tổng cộng: **24 chiều đặc trưng** sau phân tích pitfall. Tài liệu `21_SEGMENTATION_AND_FEATURE_ENGINEERING_SPECIFICATION.md` cần được cập nhật tương ứng.

---

*Tài liệu này là kết quả của vòng tham vấn chuyên gia dựa trên `22_ML_EXPERT_CONSULTATION_DOSSIER.md`. Mọi thay đổi kiến trúc tiếp theo cần cập nhật đồng bộ vào tài liệu này.*

