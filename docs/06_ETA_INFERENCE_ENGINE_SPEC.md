# ĐẶC TẢ BƯỚC 3.5: ENGINE SUY LUẬN ETA (SERVING VERTICAL SLICE)
> **Mã tài liệu**: `docs/06_ETA_INFERENCE_ENGINE_SPEC.md` | **Căn cứ**: Điều 1, 2, 6, 8 của [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md); kết quả Bước 3.4 trong [05_SESSION_HANDOVER_STEP_3_4_AND_CRAWLER_AUDIT.md](file:///z:/Desktop/Bus_tracking/docs/05_SESSION_HANDOVER_STEP_3_4_AND_CRAWLER_AUDIT.md).

## 1. Phạm vi (lát cắt nhỏ nhất, kiểm chứng được)
1. **Có**: `EtaInferenceEngine` nạp model `data/models/eta_xgb_global_full_54feat_r3_big.json` + bộ hiệu chỉnh Empirical-Bayes từ `eta_xgb_metadata_and_calibrator_r3_big.json`; nhận bảng 54 đặc trưng, trả ETA (giây) = `baseline_eta_p50_sec + Δ̂` rồi hiệu chỉnh theo `(route_id_idx, direction_id, horizon)`.
2. **Có**: kiểm tra đầu vào (đủ cột, không `NaN`/`inf`, `n_stations_ahead >= 1`), cắt dưới `5s`.
3. **Có**: kiểm chứng thực nghiệm — (a) tái lập đúng `MAE` của `5_XGB_Global_Calibrated` (`95,76s`) trên `3.704.820` mẫu Test qua engine; (b) đo độ trễ 1 dòng và theo lô.
4. **KHÔNG (ngoài phạm vi, ghi nợ)**: tự tính 54 đặc trưng từ telemetry trực tiếp BusMap (cần tái cấu trúc `feature_store_builder.py` thành bộ trích xuất tăng dần), API HTTP, loại bỏ trạm đầu cuối (`TD-19`) ở tầng đầu vào.

## 2. Tiêu chí nghiệm thu
- `MAE` qua engine trên toàn Test khớp `95,76s` (sai khác `< 0,01s`).
- Độ trễ trung vị dự báo 1 dòng và lô `10.000` dòng được đo và báo cáo.
- Mã chạy exit 0; kiểm thử: [`scripts/verify_eta_serving.py`](file:///z:/Desktop/Bus_tracking/scripts/verify_eta_serving.py).
