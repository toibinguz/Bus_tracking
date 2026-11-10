# MODULE 3: MÔ HÌNH DỰ BÁO ETA XE BUÝT TOÀN MẠNG (UNIFIED BUS ETA PREDICTION ENGINE)
> **Current status (2026-11-10):** Offline pieces/artifacts exist. Split serving modules are present but not wired by the app, and no current tests are stored. Where a feature count is required, the canonical full model has 54 features.
> **Phần 3 - Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Lộ trình thiết kế**: [docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md](../docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md)

---

## TRẠNG THÁI HIỆN TẠI: ĐÃ TRIỂN KHAI (PHASE 3 – PHASE 7)

Toàn bộ mã nguồn thí nghiệm cũ (48 mô hình rời rạc, bóc tách dwell-time vi mô, cấu trúc Weekly SLA 2-stage) đã được lưu trữ để ngăn chặn triệt để hiện tượng ô nhiễm ngữ cảnh (Context Poisoning) và đã được tái cấu trúc theo SPEC-15/SPEC-16.

Module 3 được tái cấu trúc trên nền dữ liệu **Silver Parquet sạch (số liệu thay đổi theo thời điểm — xem docs/specs/16) trên 48 tuyến chuẩn cụm HUST** theo đúng 5 phân khu chuẩn tắc:
1. `step_3_1_historical_baseline_model/`: Ma trận thời gian di chuyển phân vị lịch sử chỉ tính trên tập Train ($\le$ `2026-11-01`), có gắn nhãn `quality_tier` và `sample_count`.
2. `step_3_2_feature_store_extractor/`: Trích xuất Unified Feature Store toàn mạng (Macroscopic link travel time, không tách dwell time vi mô).
3. `step_3_3_machine_learning_models/`: Huấn luyện mô hình Unified Network Residual Gradient Boosting dự báo đa phân vị ($P_{10}, P_{50}, P_{90}$).
4. `step_3_4_eta_serving_and_evaluation/`: Dịch vụ phục vụ ETA thời gian thực (`dto`, `data_access`, `live_feed`, `frenet`, `online_features`, `model_runtime`, `eta_policy`, `serving_service`).
5. `step_3_5_web_demo/`: Web App Demo Contract-First (FastAPI `app.py` + SPA Leaflet tĩnh trong `static/`).
