# Giai đoạn 0 — Evidence Kiểm định Tính đúng đắn của Dữ liệu

- **Thời điểm chạy:** `2026-11-26 18:48:34+0700`
- **Chế độ:** Read-only 100% (`SQLite mode=ro` + `DuckDB` trên Parquet cục bộ).

---

## D1. Hình học Chuẩn hóa (`canonical_shape_master`, `canonical_station_master`)
- Tổng số tuyến canonical: `176` (trong đó tập Baseline: `48` tuyến).
- Tổng số trạm: `13301`, tổng số điểm polyline: `118563`.

| Kiểm tra | Toàn mạng (176 tuyến) | Tập Baseline (48 tuyến) |
| :--- | :---: | :---: |
| Trạm `cum_distance_m` không đơn điệu tăng (`ds <= 0`) | `0` | `0` |
| Lỗi `station_order` trùng/thiếu | `5` | `1` |
| Trạm có `snap_dist_m > 35.0m` | `208` | `59` |
| Trạm có `snap_dist_m > 100.0m` | `92` | `24` |
| Chặng `< 50m` | `53` | `6` |
| Chặng `> 5000m` | `59` | `14` |
| Điểm shape ngoài `HANOI_BBOX` / không đơn điệu | `0` / `0` | — |

**Top trạm có `snap_dist_m > 35.0m` lớn nhất (tối đa 10):**

| Tuyến | Baseline | Chiều | Order | Tên trạm | `snap_dist_m` |
| :--- | :---: | :---: | :---: | :--- | ---: |
| `163` | `False` | `go` | `47` | Bưu điện Hoài Đức | `13898.0` |
| `163` | `False` | `go` | `46` | Qua lối rẽ HV Khoa học Quân Sự | `13438.0` |
| `163` | `False` | `go` | `45` | Đối diện KĐT Kim Chung | `13202.5` |
| `146CT` | `False` | `re` | `28` | Vườn hoa Nhà hát Lớn | `11640.2` |
| `146CT` | `False` | `re` | `29` | Ngân hàng Nhà nước Việt Nam - Vườn hoa con Cóc | `11600.2` |
| `146CT` | `False` | `re` | `31` | Hàng Muối - Cầu Chương Dương | `11539.5` |
| `146CT` | `False` | `re` | `30` | 23 Hàng Tre - Ngã 4 Lò Sũ | `11504.7` |
| `35B` | `False` | `go` | `16` | Trước đối diện Cty CP Tam Sơn 30m (chiều Mê Linh - Hà Nội) | `9751.9` |
| `36` | `False` | `go` | `25` | Đối diện 81 Thanh Liệt | `9697.0` |
| `35B` | `False` | `go` | `15` | Cách cổng Cty TNHH xây dựng 305 - 30m | `9683.5` |

---

## D2. Silver Telemetry & Gold Feature Store
| Nguồn | Số dòng | Số tuyến | Khoảng thời gian (Hanoi UTC+7) |
| :--- | ---: | :---: | :--- |
| Silver Parquet (`route_projected_telemetry`) | `9,829,318` | `48` | `2026-10-08 12:55:20+0700` → `2026-11-19 20:47:46+0700` |
| SQLite (`route_projected_telemetry`) | `9,839,745` | `48` | `2026-10-08 12:55:20+0700` → `2026-11-19 20:47:46+0700` |

- Silver bất thường: `cross_track > 35m` = `0`, `s_bus < 0` = `0`, `speed < 0 or > 80` = `0`, `null_cols` = `0`, nhóm trùng `(route_id, vehicle_id, device_epoch)` = `0`.
- Tuyến Baseline thiếu chiều `go` hoặc `re` trong Silver: `0` tuyến (`[]`).

- **Gold `eta_feature_store` — Rò rỉ thời gian train $\ge$ test:** `False`.

| Split | Số dòng | Tuyến | Ngày `dt` | `actual_eta <= 0` | `> 3600s` | `NaN` | P01 / P50 / P95 / P99 / Max (s) |
| :--- | ---: | :---: | :--- | ---: | ---: | ---: | :--- |
| `test` | `3,704,820` | `47` | `2026-11-01..2026-11-07` | `0` | `152968` | `0` | `11.39 / 689.79 / 3425.07 / 4744.2 / 7199.83` |
| `train` | `11,364,661` | `48` | `2026-10-08..2026-10-31` | `0` | `496373` | `0` | `11.5 / 709.15 / 3475.36 / 4787.98 / 7199.41` |

---

## D3. Bản đồ Neo TimBus (`timbus_hanoi.sqlite` vs `hanoi_bus_system.db`)
- Sai lệch giữa `timbus_route_anchors` và `timbus_verified_anchors`: `0` dòng.
- Tổng số dòng anchor: `352` | Đang bật (`timbus_enabled=1`): `192` chiều trên `96` tuyến.
- Thiếu `primary_anchor_sid` trong `stations`: `28` | Thiếu `backup_anchor_sid`: `14`.
- Anchor cách trạm cùng chiều `> 100m`: **`17`** | Nghi ngờ lệch chiều (gần chiều ngược hơn > 30m): **`3`**.

**Top 10 anchor có khoảng cách tới trạm cùng chiều lớn nhất:**

| Tuyến | Chiều | `primary_sid` | Trạm TimBus | Khoảng cách cùng chiều (m) | Khoảng cách chiều ngược (m) |
| :--- | :---: | ---: | :--- | ---: | ---: |
| `02TC` | `go` | `1667` | Điểm cuối Trần Khánh Dư | `4897.8` | `4875.2` |
| `107` | `re` | `4158` | Điểm cuối Làng văn hóa các dân tộc Việt Nam | `1314.0` | `1314.0` |
| `36` | `re` | `1766` | Điểm cuối KĐT Linh Đàm | `589.0` | `575.0` |
| `12` | `re` | `1760` | Điểm cuối Đại Áng | `312.1` | `278.9` |
| `34` | `re` | `455` | Công viên Ngọc Lâm | `275.9` | `275.9` |
| `26` | `re` | `1789` | Điểm cuối Sân vận đông Quốc Gia | `264.1` | `268.4` |
| `92` | `re` | `2901` | Ngã 3 Đồng Bảng | `263.9` | `254.4` |
| `63` | `go` | `1664` | Cổng Khu Công nghiệp Bắc Thăng Long | `252.6` | `32.4` |
| `49` | `go` | `606` | Nhà Hát Lớn Hà Nội | `231.8` | `250.5` |
| `95` | `go` | `3122` | Điểm cuối Bến xe Nam Thăng Long | `204.5` | `204.5` |

---

## D4. Sự cố TomTom (`bronze/tomtom_incidents_raw` vs `silver/fact_route_tomtom_incidents`)
- **Bronze Parquet:** `479,377` dòng (`40` ngày: `2026-10-08..2026-11-19`), `delay <= 0`: `114861`, `length <= 0`: `0`, `bad_coords`: `0`.
- **Silver Parquet:** `1,379,409` dòng (`46` tuyến, `2026-10-08 21:00:18+0700` → `2026-11-19 20:46:01+0700`).
- **SQLite `fact_route_tomtom_incidents`:** `1,379,409` dòng (`46` tuyến, `2026-10-08 21:00:18+0700` → `2026-11-19 20:46:01+0700`).
- Silver bất thường: `delay <= 0` = `18511`, `s_max < s_min` = `0`, `overlap <= 0` = `0`, `t_end < t_start` = `0`, `d_perp > 35m` = `0`.
- **Bidirectional bleed (cùng episode chiếu sang cả 2 chiều `go` & `re` trên cùng tuyến):** `34,481 / 728,723` (**`4.73%`**).

---

## D5. Ma trận Baseline Gold (`agg_segment_travel_times`: Parquet vs SQLite)
- Số dòng: Parquet `169,830` vs SQLite `169,830` (Khóa trùng khớp: `169,830`, chỉ Parquet: `0`, chỉ SQLite: `0`).
- Sai lệch tuyệt đối lớn nhất `|tt_p50_sec|`: **`0.0s`**.
- Bất thường định lượng: `p10 > p50 or p50 > p90` = `0`, `p50 <= 0` = `0`, `p50 > 1800` = `21`, `seg_len <= 0` = `0`, `std < 0` = `0`.
- Phân bố `quality_tier`: `{'0': 145412, '1': 13971, '2': 7693, '3': 2754}`.

**10 tuyến có tỷ lệ `quality_tier = 0` thấp nhất:**

| Tuyến | Tổng cell | Tier 0 cell | Tỷ lệ Tier 0 (%) |
| :--- | ---: | ---: | ---: |
| `39` | `4,335` | `637` | `14.69%` |
| `E11` | `4,131` | `640` | `15.49%` |
| `67` | `5,661` | `2,764` | `48.83%` |
| `56B` | `3,825` | `1,912` | `49.99%` |
| `101A` | `6,579` | `3,794` | `57.67%` |
| `92` | `6,018` | `4,153` | `69.01%` |
| `42` | `3,978` | `3,161` | `79.46%` |
| `61` | `4,845` | `4,115` | `84.93%` |
| `40` | `3,009` | `2,601` | `86.44%` |
| `01` | `3,519` | `3,102` | `88.15%` |
