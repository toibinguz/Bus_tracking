# MODULE 3: MÔ HÌNH DỰ BÁO ETA XE BUÝT TOÀN MẠNG (UNIFIED BUS ETA PREDICTION ENGINE)
> **Phần 3 - Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Lộ trình thiết kế**: [docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md](../docs/01_MASTER_WORK_BREAKDOWN_STRUCTURE_ROADMAP.md)

---

## TRẠNG THÁI HIỆN TẠI: CLEAN-SLATE (CHỜ TRIỂN KHAI PHASE 3 – PHASE 6)

Toàn bộ mã nguồn thí nghiệm cũ (48 mô hình rời rạc, bóc tách dwell-time vi mô, cấu trúc Weekly SLA 2-stage) đã được lưu trữ vào `archive/clean_slate_2026_11_07/legacy_module_3_code/` để ngăn chặn triệt để hiện tượng ô nhiễm ngữ cảnh (Context Poisoning).

Module 3 sẽ được xây dựng mới hoàn toàn từ đầu trên nền dữ liệu **Silver Parquet sạch (`5.340.551` dòng trên 48 tuyến chuẩn cụm HUST)** theo đúng 4 phân khu chuẩn tắc:
1. `step_3_1_historical_baseline_model/`: Ma trận thời gian di chuyển phân vị lịch sử chỉ tính trên tập Train ($\le$ `2026-11-01`), có gắn nhãn `quality_tier` và `sample_count`.
2. `step_3_2_feature_store_extractor/`: Trích xuất Unified Feature Store toàn mạng (Macroscopic link travel time, không tách dwell time vi mô).
3. `step_3_3_machine_learning_models/`: Huấn luyện mô hình Unified Network Residual Gradient Boosting dự báo đa phân vị ($P_{10}, P_{50}, P_{90}$).
4. `step_3_4_evaluation_and_benchmarking/`: Kiểm định độc lập trên tập Test ($\ge$ `2026-11-02`, 1,25 triệu bản ghi).
