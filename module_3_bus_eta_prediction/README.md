# MODULE 3: MÔ HÌNH DỰ BÁO ETA XE BUÝT — ĐIỂM & KHOẢNG THỜI GIAN (BUS ETA PREDICTION ENGINE)
> **Phần 3 - Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Đặc tả kỹ thuật**: [docs/60_FEATURE_STORE_AND_INTERVAL_ETA_MODEL_SPECIFICATION.md](../docs/60_FEATURE_STORE_AND_INTERVAL_ETA_MODEL_SPECIFICATION.md)

---

## 1. CẤU TRÚC SUBCOMPONENTS & PIPELINES

```
module_3_bus_eta_prediction/
├── step_3_1_historical_baseline_model/       # Mô hình cơ sở (Baseline Segment Travel Time Matrix)
│   └── baseline_segment_average.py           # Ma trận 95,094 ô (3 loại ngày x 9 chế độ động học)
├── step_3_2_feature_store_extractor/         # Trích xuất 16 đặc trưng trực giao (X -> Y, 0% leakage)
│   └── feature_extractor.py                  # Kết hợp Tiên nghiệm 3.1 + Động học chuỗi Ping + Xe đi trước/sau
├── step_3_3_machine_learning_models/         # Huấn luyện Residual Multi-Quantile XGBoost + Scaled CQR
│   └── train_eta_model.py                    # Dự báo đồng thời Điểm (P50) & Khoảng tin cậy 80% [P10, P90]
└── step_3_4_evaluation_and_benchmarking/     # Đo đạc sai số Điểm & Khoảng đa tuyến
    └── benchmark_evaluator.py                # Đánh giá MAE, RMSE, Hit@60s, PICP, MPIW, Winkler Score
```

---

## 2. BỘ 16 ĐẶC TRƯNG TRỰC GIAO (`FEATURE_COLUMNS`)

Được tuyển chọn qua kiểm định Ablation (`Train vs. Unseen Holdout Test Gap`) nhằm ngăn chặn cả Underfitting lẫn Overfitting:

1. **Tiên nghiệm Ma trận Lịch sử Module 3.1 (3 biến)**: `baseline_median_sec`, `baseline_spread_sec`, `baseline_std_sec`
2. **Tương tác Đội xe Cùng Tuyến — Xe đi trước & Giãn cách (3 biến)**: `leader_pace_ratio`, `dist_to_leader_m`, `headway_to_leader_sec`
3. **Động học Chuỗi Ping & Nhịp độ Xe Hiện Tại (5 biến)**: `ego_recent_pace_ratio`, `rolling_speed_180s_kmh`, `v_last_1_ping_kmh`, `is_dwell`, `current_dwell_sec`
4. **Hình học 1D Frenet & Topo Trạm (3 biến)**: `s_bus_m`, `distance_remaining_m`, `stops_ahead`
5. **Ngữ cảnh Thời gian & Chiều (2 biến)**: `direction_encoded`, `hour`

---

## 3. HƯỚNG DẪN THỰC THI

```powershell
# 1. Trích xuất thử tập huấn luyện có giám sát của 1 tuyến
.\.venv\Scripts\python.exe module_3_bus_eta_prediction\step_3_2_feature_store_extractor\feature_extractor.py 02

# 2. Huấn luyện và đo kiểm Point & Interval ETA cho 1 tuyến
.\.venv\Scripts\python.exe module_3_bus_eta_prediction\step_3_3_machine_learning_models\train_eta_model.py 02

# 3. Đối chuẩn hàng loạt trên nhiều tuyến
.\.venv\Scripts\python.exe module_3_bus_eta_prediction\step_3_4_evaluation_and_benchmarking\benchmark_evaluator.py 02 32 01
```
