# 60. ĐẶC TẢ KỸ THUẬT MODULE 3.2 & 3.3: TRÍCH XUẤT FEATURE STORE TRỰC GIAO (16 THUỘC TÍNH ĐỘI XE & ĐỘNG HỌC) VÀ MÔ HÌNH ƯỚC LƯỢNG KHOẢNG THỜI GIAN ETA
> **Tài liệu**: `docs/60_FEATURE_STORE_AND_INTERVAL_ETA_MODEL_SPECIFICATION.md`  
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Phạm vi**: `module_3_bus_eta_prediction` (`step_3_2`, `step_3_3`, `step_3_4`)  
> **Ngày lập**: 01/11/2026  
> **Trạng thái**: Đã thực thi và kiểm chứng thực nghiệm trên dữ liệu thật (`hanoi_bus_system.db`)

---

## I. KIỂM ĐỊNH ABLATION STUDY: CHỌN SỐ LƯỢNG THUỘC TÍNH VỪA ĐỦ ĐỂ TRÁNH UNDERFITTING & OVERFITTING

Để tránh hai thái cực:
1. **Underfitting (Quá ít thuộc tính, $K = 4 \dots 6$)**: Chỉ dùng khoảng cách, vận tốc tức thời và giờ trong ngày — mô hình không biết đặc thù ùn tắc của từng đoạn đường và không biết xe phía trước đang chạy nhanh hay chậm.
2. **Overfitting (Nhồi nhét $K = 36$ thuộc tính đa cộng tuyến)**: Đưa cả `v_last_2_ping`, `v_last_3_ping`, `minute`, `cross_track_m`, `active_fleet_count`, `kinematic_eta_sec`, `baseline_p10_sec` khiến cây quyết định học vẹt nhiễu trên tập Train ở các tuyến có số chuyến vừa và nhỏ.

### Kết quả thực nghiệm Ablation (`Train MAE` vs. `Unseen Holdout Test MAE`)

| Tập thuộc tính thử nghiệm | Số biến ($K$) | Tuyến 02 (`N=794k`, 4,078 chuyến)<br>`Test MAE` / `RMSE` | Tuyến 01 (`N=197k`, 916 chuyến)<br>`Test MAE` / `Overfit Gap` | Tuyến 123 (`N=59k`, 569 chuyến)<br>`Test MAE` / `Overfit Gap (Test-Train)` | Chẩn đoán Kỹ thuật |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **1. Cơ bản (Basic)** | $K = 4$ | 63.47s / 90.30s | 45.96s / -2.29s | 30.75s / -0.45s | **Underfitting nặng** (Sai số cao hơn +23s) |
| **2. Chỉ Tiên nghiệm Lịch sử 3.1** | $K = 5$ | 43.32s / 65.92s | 45.20s / -1.50s | 29.95s / +0.10s | Thiếu thông tin động học thời gian thực của xe và đội xe |
| **3. Tập Trực Giao Chuẩn (Orthogonal Sweet Spot)** | **$K = 16$** | **40.40s / 60.50s** | **44.67s / -0.94s** | **29.33s / +0.21s** | **ĐIỂM CÂN BẰNG TỐI ƯU (Sweet Spot)** |
| **4. Tập Đầy Đủ Đa Cộng Tuyến** | $K = 36$ | 40.41s / 60.45s | 44.63s / -0.42s | 29.14s / **+2.59s (Tăng 12x)** | **Overfitting ở tuyến nhỏ**, dư thừa 20 biến đa cộng tuyến |

> **Kết luận thực nghiệm**: Cắt tỉa từ 36 biến xuống đúng **16 thuộc tính trực giao (`FEATURE_COLUMNS`)** giữ nguyên 100% độ chính xác trên các tuyến lớn (`MAE = 40.4s` trên Tuyến 02, `40.3s` trên Tuyến 32) đồng thời chặn đứng hiện tượng Overfitting trên các tuyến nhỏ (giảm độ lệch `Test - Train` trên Tuyến 123 từ `+2.59s` về `+0.21s`).

---

## II. BỘ 16 THUỘC TÍNH TRỰC GIAO CHUẨN TẮC (`FEATURE_COLUMNS`) TRONG MODULE 3.2

Trong [`feature_extractor.py`](../module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_extractor.py), toàn bộ 16 thuộc tính được tính toán **nhân quả nghiêm ngặt ($t_{\text{obs}} \le t_{\text{ping}}$, 0% rò rỉ tương lai)** chia làm 5 chiều vật lý độc lập:

| Nhóm Chiều Vật Lý | Tên Thuộc Tính (`16 biến`) | Công Thức & Ý Nghĩa Thực Chiến | Tỷ Trọng Đóng Góp Thực Nghiệm (Gain %) |
| :--- | :--- | :--- | :---: |
| **1. Tiên nghiệm Ma trận Lịch sử 3.1** *(3 biến)* | `baseline_median_sec`<br>`baseline_spread_sec`<br>`baseline_std_sec` | Thời gian trung vị lịch sử $T_{\text{base}}$, độ tản $P_{90} - P_{10}$ và độ lệch chuẩn gộp $\sqrt{\sum \sigma_j^2}$ trên các đoạn từ vị trí xe hiện tại tới trạm đích $m$. | **31% – 43%**<br>*(Định hình khung thời gian & độ rộng khoảng tin cậy)* |
| **2. Tương tác Đội xe Cùng Tuyến — Xe Đi Trước & Giãn Cách** *(3 biến)* | `leader_pace_ratio`<br>`dist_to_leader_m`<br>`headway_to_leader_sec` | - **`leader_pace_ratio`**: Tỷ số thời gian thực tế của **xe cùng tuyến liền trước** vừa đi qua đúng các đoạn đường phía trước (trong $\le 45$ phút) so với `baseline_median_sec`.<br>- **`dist_to_leader_m`**: Khoảng cách không gian tới xe liền trước ($< 500\text{m}$: hiệu ứng dồn toa *Bus Bunching* — xe trước đã vét sạch khách).<br>- **`headway_to_leader_sec`**: Thời gian kể từ lúc chuyến trước đi qua trạm hiện tại (đo lượng khách tích tụ tại trạm). | **10% – 16%**<br>*(`leader_pace_ratio` đứng Top 3 toàn mô hình với **10.6% – 12.3%**)* |
| **3. Động học Chuỗi Ping & Nhịp độ Xe Hiện Tại** *(5 biến)* | `ego_recent_pace_ratio`<br>`rolling_speed_180s_kmh`<br>`v_last_1_ping_kmh`<br>`is_dwell`<br>`current_dwell_sec` | - **`ego_recent_pace_ratio`**: Tỷ số thời gian thực tế / lịch sử của **chính xe đang xét** trên 1–3 đoạn trạm vừa đi qua.<br>- **`rolling_speed_180s_kmh` & `v_last_1_ping_kmh`**: Vận tốc trượt 3 phút và vận tốc bước ping gần nhất.<br>- **`is_dwell` & `current_dwell_sec`**: Trạng thái dừng và số giây xe đã đứng im liên tục ($\Delta s < 15\text{m}$). | **15% – 22%**<br>*(`ego_recent_pace_ratio` và `current_dwell_sec` đóng góp trực tiếp vào hiệu chỉnh tức thời)* |
| **4. Hình học 1D Frenet & Topo Trạm** *(3 biến)* | `s_bus_m`<br>`distance_remaining_m`<br>`stops_ahead` | Vị trí dọc tuyến (nhận diện nút cổ chai cố định), quãng đường còn lại (mét) và số trạm dừng phải đi qua ($1 \dots 5$). | **12% – 18%** |
| **5. Ngữ cảnh Thời gian & Chiều** *(2 biến)* | `direction_encoded`<br>`hour` | Chiều đi/về (`1/0`) và giờ trong ngày (`5..22`). | **9% – 14%** |

---

## III. ĐỘ ĐO CHUẨN CHO MÔ HÌNH ƯỚC LƯỢNG KHOẢNG THỜI GIAN (`[P10, P50, P90]`)

Vì sản phẩm thực tế trả về cho hành khách cả **Dự báo điểm (Point ETA)** lẫn **Khoảng thời gian tin cậy 80% (`[ETA_sớm, ETA_muộn]`)**, hệ thống đánh giá trong [`train_eta_model.py`](../module_3_bus_eta_prediction/step_3_3_machine_learning_models/train_eta_model.py) sử dụng song song 2 bộ chỉ số:

1. **Bộ độ đo Điểm trung tâm (`P50`)**:
   - **MAE (Mean Absolute Error)** & **MdAE (Median Absolute Error)**: Sai số tuyệt đối trung bình và trung vị (giây).
   - **RMSE (Root Mean Squared Error)**: Phạt nặng các trường hợp sai số lớn.
   - **Hit Rate `@ ±60s` & `@ ±90s`**: Tỷ lệ % dự báo sai lệch không quá 1 phút và 1.5 phút.
2. **Bộ độ đo Khoảng thời gian (`[P10, P90]` — 80% Nominal Interval)**:
   - **PICP (*Prediction Interval Coverage Probability*)**: Tỷ lệ % chuyến xe thực tế đến nằm lọt trong khoảng $[\hat{y}_{10}, \hat{y}_{90}]$. Mô hình chuẩn phải đạt **$\text{PICP} \approx 80\% - 82\%$**.
   - **MPIW (*Mean Prediction Interval Width*)**: Độ rộng trung bình của khoảng dự báo $\hat{y}_{90} - \hat{y}_{10}$ (giây). Khi cùng đạt PICP $\ge 80\%$, mô hình nào có **MPIW nhỏ hơn (khoảng hẹp hơn)** thì thông tin càng sắc bén.
   - **Winkler Interval Score ($S_{\alpha=0.20}$)**: Độ đo tổng hợp chuẩn quốc tế kết hợp cả độ hẹp của khoảng và mức phạt gấp $2/\alpha = 10$ lần khi thực tế rơi ra ngoài khoảng:
     $$S_{0.20}(L, U, y) = (U - L) + 10\max(0, L - y) + 10\max(0, y - U)$$
   - **Missed Bus Risk ($\mathbb{P}(y < \hat{y}_{10})$)**: Rủi ro xe đến sớm hơn cận dưới khiến khách ra trạm muộn bị lỡ xe (yêu cầu kiểm soát chặt quanh mức $\le 10\%$).

---

## IV. CHIẾN LƯỢC TẬP TRUNG VÀO CÁC TUYẾN CHỦ LỰC GIÀU DỮ LIỆU (GOLDEN DEMO ROUTES) & KẾT QUẢ ĐỐI CHUẨN

Trong giai đoạn nguyên mẫu, thay vì dàn trải trên các tuyến nhánh ngoại thành ít chuyến (như 56B, 67), hệ thống tập trung huấn luyện và phục vụ Demo trên **Top 6 Tuyến Chủ Lực Giàu Dữ Liệu Nhất (`GOLDEN_DEMO_ROUTES`)** đại diện cho đủ các loại hình vận tải buýt Hà Nội (Truyền thống trục chính, Buýt điện VinBus, Buýt nhanh BRT), mỗi tuyến có **50,000 – 116,000+ lượt vượt chặng** và **90.5% – 96.0% độ phủ GPS trực tiếp Tier 0**:

1. **Tuyến `02` (Bác Cổ – BX Yên Nghĩa)**: 4,078 chuyến (`794,276` mẫu giám sát, `95.7%` Tier 0)
2. **Tuyến `27` (BX Yên Nghĩa – Nam Thăng Long)**: 4,117 chuyến (`769,854` mẫu giám sát, `96.0%` Tier 0)
3. **Tuyến `32` (BX Giáp Bát – Nhổn)**: 3,500 chuyến (`663,677` mẫu giám sát, `91.8%` Tier 0)
4. **Tuyến `E01` (BX Mỹ Đình – Ocean Park, VinBus Điện)**: 3,763 chuyến (`513,535` mẫu giám sát, `94.7%` Tier 0)
5. **Tuyến `BRT01` (BX Yên Nghĩa – Kim Mã, Buýt Nhanh BRT)**: 3,750 chuyến (`467,158` mẫu giám sát, `93.1%` Tier 0)
6. **Tuyến `26` (Mai Động – SVĐ Quốc Gia)**: 2,509 chuyến (`518,818` mẫu giám sát, `90.5%` Tier 0)

> **Tổng quy mô tập dữ liệu 6 tuyến Demo**: **3,727,318 mẫu giám sát** trên **21,717 chuyến xe độc lập**. Với quy mô $> 450,000$ mẫu/tuyến, mô hình khai thác trọn vẹn **28 thuộc tính tín hiệu cao** (`FEATURE_COLUMNS`) mà hoàn toàn không bị Overfitting.

### 1. Kết quả Đối Chuẩn Đa Trạm (`1 đến 5 trạm phía trước`, cự ly tới $3,500\text{m}$)

| Tuyến Demo | Tập Test Độc Lập | Mô Hình Đối Chiếu | Point MAE $\downarrow$ | Point MdAE $\downarrow$ | Point RMSE $\downarrow$ | Hit Rate $\pm 60\text{s}$ $\uparrow$ | Hit Rate $\pm 90\text{s}$ $\uparrow$ | Độ Phủ PICP $[80\%]$ | Độ Rộng Khoảng MPIW $\downarrow$ | Điểm Khoảng Winkler $\downarrow$ |
| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Tuyến 02** | 816 chuyến<br>*(150,568 mẫu)* | 1. Naive Speed | 71.4s | 50.7s | 100.6s | 56.2% | 71.3% | 69.5% | 206.9s | 332.7s |
| | | 2. Module 3.1 Matrix | 45.0s | 27.9s | 70.8s | 76.0% | 87.2% | 78.8% | 151.5s | 223.7s |
| | | **3. Module 3.3 XGB-CQR** | **40.4s** | **26.6s** | **60.4s** | **77.9%** | **89.3%** | **81.8%** | **135.4s (2.3p)** | **184.6s (-44.5%)** |
| **Tuyến 27** | 824 chuyến<br>*(155,770 mẫu)* | 1. Naive Speed | 70.2s | 46.3s | 106.7s | 59.4% | 74.2% | 70.0% | 192.6s | 350.7s |
| | | 2. Module 3.1 Matrix | 47.8s | 28.0s | 78.2s | 74.3% | 85.6% | 76.8% | 146.8s | 236.8s |
| | | **3. Module 3.3 XGB-CQR** | **42.1s** | **26.3s** | **67.0s** | **77.1%** | **88.3%** | **81.1%** | **135.6s (2.3p)** | **194.8s (-44.5%)** |
| **Tuyến 32** | 700 chuyến<br>*(127,426 mẫu)* | 1. Naive Speed | 73.0s | 49.6s | 107.7s | 56.6% | 71.5% | 74.8% | 234.0s | 360.4s |
| | | 2. Module 3.1 Matrix | 47.3s | 27.0s | 79.4s | 76.2% | 86.6% | 78.1% | 150.2s | 256.1s |
| | | **3. Module 3.3 XGB-CQR** | **40.1s** | **25.6s** | **62.0s** | **79.1%** | **89.6%** | **81.2%** | **133.6s (2.2p)** | **186.1s (-48.4%)** |
| **Tuyến E01**<br>*(VinBus)* | 753 chuyến<br>*(95,744 mẫu)* | 1. Naive Speed | 81.1s | 47.2s | 128.8s | 57.9% | 71.3% | 66.1% | 189.8s | 426.6s |
| | | 2. Module 3.1 Matrix | 52.4s | 29.6s | 86.6s | 72.6% | 83.5% | 71.8% | 148.9s | 259.1s |
| | | **3. Module 3.3 XGB-CQR** | **40.2s** | **24.4s** | **62.4s** | **78.3%** | **88.8%** | **80.9%** | **133.3s (2.2p)** | **184.7s (-56.7%)** |
| **BRT01**<br>*(Buýt Nhanh)* | 750 chuyến<br>*(92,251 mẫu)* | 1. Naive Speed | 59.1s | 36.0s | 94.5s | 67.8% | 80.9% | 80.5% | 192.4s | 305.9s |
| | | 2. Module 3.1 Matrix | 46.8s | 27.0s | 77.3s | 76.6% | 86.9% | 75.3% | 129.1s | 236.1s |
| | | **3. Module 3.3 XGB-CQR** | **37.3s** | **24.1s** | **57.2s** | **81.4%** | **91.3%** | **79.9%** | **116.8s (1.9p)** | **171.8s (-43.8%)** |
| **Tuyến 26** | 502 chuyến<br>*(97,321 mẫu)* | 1. Naive Speed | 73.1s | 46.7s | 113.5s | 58.5% | 72.7% | 78.6% | 246.6s | 369.1s |
| | | 2. Module 3.1 Matrix | 47.3s | 29.1s | 79.7s | 75.4% | 86.8% | 77.3% | 154.2s | 237.7s |
| | | **3. Module 3.3 XGB-CQR** | **42.4s** | **27.4s** | **68.5s** | **78.0%** | **89.1%** | **80.7%** | **135.8s (2.3p)** | **195.9s (-46.9%)** |

### 2. Kết quả Dự báo Trạm Kế Tiếp Gần Nhất (`stops_ahead == 1`)

| Tuyến Demo | Mẫu Test (`stops_ahead = 1`) | Module 3.1 Baseline MAE | **Module 3.3 XGB-CQR MAE** | **Hit Rate $\pm 60\text{s}$** | **Độ Phủ PICP $[80\%]$** | **Độ Rộng Khoảng MPIW** | Artifact Mô Hình Đã Xuất |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Tuyến 02** | 31,140 mẫu | 21.94s | **19.52s** *(0.33p)* | **94.0%** | **81.0%** | **62.4s** ($\pm 31\text{s}$) | `models/xgboost_eta_route_02.json` |
| **Tuyến 27** | 31,596 mẫu | 23.32s | **20.72s** *(0.35p)* | **92.3%** | **80.8%** | **65.2s** ($\pm 33\text{s}$) | `models/xgboost_eta_route_27.json` |
| **Tuyến 32** | 26,255 mẫu | 26.25s | **20.24s** *(0.34p)* | **93.4%** | **80.8%** | **65.3s** ($\pm 33\text{s}$) | `models/xgboost_eta_route_32.json` |
| **Tuyến E01** | 24,256 mẫu | 35.91s | **22.07s** *(0.37p)* | **91.6%** | **80.4%** | **71.5s** ($\pm 36\text{s}$) | `models/xgboost_eta_route_E01.json` |
| **Tuyến BRT01** | 21,136 mẫu | 30.86s | **22.90s** *(0.38p)* | **91.8%** | **79.2%** | **69.9s** ($\pm 35\text{s}$) | `models/xgboost_eta_route_BRT01.json` |
| **Tuyến 26** | 20,256 mẫu | 22.23s | **19.58s** *(0.33p)* | **94.5%** | **80.7%** | **63.1s** ($\pm 32\text{s}$) | `models/xgboost_eta_route_26.json` |

---

## V. TRIỂN KHAI TOÀN MẠNG LƯỚI 48 TUYẾN VÀ LƯU TRỮ CSDL KIỂM ĐỊNH

Thực thi `benchmark_evaluator.py` trên toàn bộ **48/48 tuyến** (tổng thời gian chạy 448 giây):
- **Xuất xưởng 48/48 tệp mô hình**: `models/xgboost_eta_route_<route_code>.json` cho tất cả 48 tuyến.
- **Lưu trữ trực tiếp vào `data/hanoi_bus_system.db`**:
  1. Bảng **`ml_route_evaluation_summary` (48 dòng)**: Tổng hợp kết quả đánh giá cấp độ tuyến cho toàn bộ 48 tuyến. Cả 48/48 tuyến đều ghi nhận mức cải thiện dương (`+6.0%` đến `+38.6%`) so với Ma trận Lịch sử 3.1, với sai số trung vị cặp trạm (`MdAE`) chỉ từ **`5.3s – 14.1s` (`7.1% – 15.4%`)** và độ phủ khoảng tin cậy `PICP` đạt **`76.9% – 83.6%`**.
  2. Bảng **`ml_station_pair_evaluation` (3,522 dòng)**: Bảng đánh giá chi tiết từng cặp trạm liên tiếp ($k \to k+1$) không rút gọn trên toàn bộ 48 tuyến (96 chiều tuyến), bao gồm cả sai lệch tính bằng giây (`ml_mae_sec`, `ml_median_err_sec`) và phần trăm (`ml_wmape_pct`, `ml_mape_pct`, `ml_median_err_pct`).


