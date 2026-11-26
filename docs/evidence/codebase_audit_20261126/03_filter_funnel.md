# Giai đoạn 3 — Evidence Filter Funnel & Ablation Probe

- **Thời điểm chạy:** `2026-11-26 18:49:16+0700`
- **Phạm vi dữ liệu:** `dt=2026-11-18`, 5 tuyến `['01', '02', '27', '32', 'E03']`, cadence `180.0s`.
- **Lưu ý phạm vi:** Dữ liệu Silver Parquet đã qua lọc hành lang `<= 35m` ở Batch và không lưu trường `deg` thô, nên cổng `heading` & `cross_track` trên Silver chủ yếu đo hành vi tái chiếu qua `RouteProjectionTracker` (`RouteHMM horizon=120s`) và các cổng Serving phía sau.

---

## 1. Funnel Mức Ping (Ingestion & HMM Online)

| Cổng lọc | Số lượng | Tỷ lệ (%) | Ghi chú |
| :--- | ---: | ---: | :--- |
| Silver pings đầu vào | `54,280` | `100.00%` | Dữ liệu ngày `2026-11-18` |
| `RouteProjectionTracker` (`HMM 120s`) chấp nhận | `54,278` | `100.00%` | `matched_projection != None` |
| `RouteProjectionTracker` (`HMM 120s`) loại | `2` | `0.00%` | Theo tuyến: `{'27': 2}` |
| `CausalFeatures.observe` chấp nhận | `54,278` | `100.00%` | `HMM 360s, window=128` |
| `CausalFeatures.observe` từ chối | `2` | `0.00%` | `out-of-order` / không khớp hình học |

---

## 2. Funnel Mức Cặp (Xe × Trạm) & Trạng thái Dự báo

| Cổng lọc trạm (`project_filter_extrapolate` + ML) | Số lượng | Tỷ lệ (%) |
| :--- | ---: | ---: |
| Tổng lượt đánh giá `(xe x trạm)` | `115,842` | `100.00%` |
| Loại do `passed_s_target` (`s_now > s_target`) | `57,865` | `49.95%` |
| Loại do `hmm_unmatched` | `6` | `0.01%` |
| Loại do `cross_track > 35m` | `0` | `0.00%` |
| Loại do `heading_rejected` (`deg` nội suy) | `492` | `0.42%` |
| Loại do `stale > 300s` | `0` | `0.00%` |
| Chấp nhận vào `compute_station_eta` | `57,479` | `49.62%` |
| Trong đó trường hợp biên `d_station == 0.0` | `7` | `0.01%` |

**Phân bố `fallback_reason` trên các lượt được chấp nhận:**

| Lý do | Số lượt | Tỷ lệ (%) |
| :--- | ---: | ---: |
| `ok` | `52,163` | `90.75%` |
| `cold_start_causal` | `5,316` | `9.25%` |

---

## 3. Ablation Probe — Kiểm tra Lớp Kẹp / Trần Phòng thủ

- **ETA clamp `max(5.0, baseline_p50 + delta)`:** Trên `52,163` lượt dự báo ML, có **`85` (`0.163%`)** lượt có `raw_eta < 5.0s` (trong đó `< 0.0s`: `21`). Phân bố `raw_eta`: `{'count': 52163, 'min': -14.35, 'p01': 20.74, 'p05': 91.28, 'p50': 1415.68, 'p95': 4080.19, 'p99': 5399.51, 'max': 7600.56}`.
- **LINEX buffer ceiling `180.0s`:** Trên `57,479` lượt xuất ETA, có **`20,637` (`35.9%`)** lượt có `raw_buffer > 180.0s` bị chạm trần. Phân bố `raw_buffer`: `{'count': 57479, 'min': 0.0, 'p01': 6.35, 'p05': 20.93, 'p50': 139.9, 'p95': 344.08, 'p99': 456.49, 'max': 694.14}`.
- **Proximity Cap (`80m / 120m / 2.5 m/s / 15s`):** Kích hoạt trên **`531 / 54,733` (`0.97%`)** lượt xe trong hàng chờ nhiều xe; mức giảm ETA: `{'count': 531, 'min': 0.02, 'p01': 0.19, 'p05': 0.78, 'p50': 18.09, 'p95': 129.37, 'p99': 256.57, 'max': 606.28}`.
- **Phân bố `traffic_status`:** `{'UN_TAC': 24800, 'THONG_THOANG': 12801, 'BINH_THUONG': 19878}` | Tỷ lệ `is_delayed == True`: **`15.58%`** (`8,956` lượt).
