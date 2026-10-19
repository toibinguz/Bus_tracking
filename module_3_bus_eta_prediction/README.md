# MODULE 3: MÔ HÌNH DỰ BÁO ETA XE BUÝT (BUS ETA PREDICTION ENGINE)
> **Phần 3 - Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Mục tiêu**: Xây dựng ma trận Baseline thời gian chạy lịch sử, trích xuất Feature Store có giám sát và huấn luyện mô hình học máy (XGBoost/LightGBM) dự báo thời gian xe buýt đến trạm đích kế tiếp với sai số MAE < 40 giây.

---

## 1. CẤU TRÚC SUBCOMPONENTS & PIPELINES

```
module_3_bus_eta_prediction/
├── step_3_1_historical_baseline_model/       # Mô hình cơ sở (Baseline Segment Average)
│   └── baseline_segment_average.py           # Ma trận thời gian chạy từng chặng trạm theo 4 khung giờ
├── step_3_2_feature_store_extractor/         # Trích xuất đặc trưng có giám sát (X -> Y)
│   └── feature_extractor.py                  # Ghép nối ping với thời điểm thực tế xe cập bến đích
├── step_3_3_machine_learning_models/         # Huấn luyện mô hình học máy Gradient Boosting
│   └── train_eta_model.py                    # Huấn luyện XGBoost Regressor và lưu artifact (.json)
└── step_3_4_evaluation_and_benchmarking/     # Đo đạc sai số & Đối chuẩn hiệu năng
    └── benchmark_evaluator.py                # Đánh giá đa tuyến MAE, RMSE, MAPE so sánh Baseline vs ML
```

---

## 2. BỘ ĐẶC TRƯNG HỌC MÁY (FEATURE SPECIFICATION)

| Tên Đặc Trưng | Kiểu | Ý Nghĩa Nghiệp Vụ | Trọng Số Ảnh Hưởng (Gain) |
| :--- | :---: | :--- | :---: |
| `is_dwell` | Binary (0/1) | Cờ xe đang dừng đỗ theo quy tắc $\Delta s < 15\text{m}, \Delta t \ge 20\text{s}$ | **71.02% (Thống trị)** |
| `distance_remaining_m` | Float | Khoảng cách 1D còn lại đến vạch dừng trạm đích $\Delta s_{\text{remain}}$ | **7.76%** |
| `hour` | Integer | Giờ trong ngày (phân hóa cao điểm sáng / chiều / đêm) | **6.15%** |
| `next_station_order` | Integer | Thứ tự trạm trên hành trình (từ 0 đến $N_{\text{stations}}$) | **3.85%** |
| `minute` | Integer | Phút trong giờ | **3.48%** |
| `derived_speed_kmh` | Float | Vận tốc dẫn xuất không gian - thời gian $\bar{v} = \Delta s / \Delta t$ | **3.39%** |
| `s_bus_m` | Float | Lý trình dọc tuyến của xe buýt tính từ đầu bến | **2.60%** |
| `cross_track_m` | Float | Độ lệch vuông góc của xe so với tim đường | **1.74%** |

---

## 3. HƯỚNG DẪN THỰC THI CHO THÀNH VIÊN NHÓM

### Bước 3.1: Chạy mô hình Baseline cho tuyến được phân công
Tính ma trận thời gian chạy lịch sử giữa các cặp trạm theo từng khung giờ:
```powershell
python module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_segment_average.py 02
```
*(Thay `02` bằng mã tuyến bất kỳ trong 48 tuyến: `01`, `32`, `26`, `E01`,...)*

### Bước 3.2: Huấn luyện và Đánh giá Mô hình XGBoost
Trích xuất dữ liệu giám sát, huấn luyện mô hình XGBoost và đo MAE đối chuẩn:
```powershell
python module_3_bus_eta_prediction/step_3_3_machine_learning_models/train_eta_model.py 02
```
*Kết quả đối chuẩn thực nghiệm trên Tuyến 02*:
- **Baseline Model MAE**: 71.47 giây (1.19 phút)
- **XGBoost Model MAE**: **38.80 giây (0.65 phút)** $\to$ **Cải thiện độ chính xác +45.72% so với Baseline!**
- Tệp mô hình xuất xưởng: `models/xgboost_eta_route_02.json`.

### Bước 3.3: Đối chuẩn hiệu năng đa tuyến hàng loạt
Đánh giá độ chính xác cùng lúc nhiều tuyến xe buýt:
```powershell
python module_3_bus_eta_prediction/step_3_4_evaluation_and_benchmarking/benchmark_evaluator.py 01 02 32
```
