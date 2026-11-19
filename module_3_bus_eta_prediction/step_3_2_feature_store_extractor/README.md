# Step 3.2: Trích xuất Đặc trưng Nhân quả (`step_3_2_feature_store_extractor`)

- **Vai trò:** Xây dựng bộ 36 đặc trưng `CausalFeatures` chỉ từ tiền tố quan sát quá khứ (`observation prefix` — tuyệt đối không rò rỉ tương lai), dùng chung 1 code path duy nhất cho cả replay huấn luyện (`step_3_3`) và inference trực tuyến (`step_3_4`).
- **Đầu vào:** Chuỗi `Observation` (tọa độ `s_m`, tốc độ, nguồn `busmap`/`timbus`, trạng thái snapshot) và dữ liệu baseline/trạm từ `DataAccess`.
- **Đầu ra:** Vector 36 đặc trưng `FEATURES` (thông tin tuyến/khung giờ, khoảng cách còn lại, tốc độ/gia tốc ego, mật độ đội xe cùng tuyến, `baseline_eta_p50_sec`, v.v.).

## Thành phần chính

| File / Symbol | Vai trò | Input -> Output |
| --- | --- | --- |
| `causal_eta.py` (`CausalFeatures`, `Observation`, `VehicleState`, `Speed`) | Trạng thái từng xe (bảo vệ bằng `threading.RLock`) và hàm sinh 36 đặc trưng nhân quả | `Observation` stream -> 36-feature dict |
| `feature_store_builder.py` (`build_gold_feature_store`, `_process_single_route`) | Trích xuất song song Gold Feature Store Parquet phục vụ phân tích batch | Silver Parquet -> `data/lakehouse/gold/eta_feature_store/` |

## Cách kiểm thử

```bash
python -m pytest tests/module_3/test_causal_eta_training.py --basetemp=runtime/pytest_tmp -q
```
