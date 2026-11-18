# Kiểm kê 54 feature ETA: model đã học gì, app đang cung cấp gì?

Đối chiếu mã và model ngày **18/11/2026**. Tài liệu này mô tả hiện trạng và đề xuất cách tính cần thống nhất; **không có nghĩa các sửa đổi đề xuất đã được cài đặt**. Không huấn luyện lại hay thay model trong lần kiểm kê này.

## 1. Phạm vi và cách đọc số liệu

Model full `eta_xgb_global_full_54feat_r3_big.json` có **54 feature**, 708 vòng cây được lưu, nhưng `best_iteration=677`: hàm predict hiện dùng **678 vòng đầu**. Model pruned có **53 feature**, bỏ `n_active_buses_on_route`; số liệu bên dưới thuộc **model full**, không được dùng thay cho báo cáo model pruned.

SHA256 model full: `eb524de9e2838880bc9d4cc4ce0bf8f8d77024665e36bbc70b99ebf0d3034ef2`.

### Đóng góp khi huấn luyện và khi dự báo là hai việc khác nhau

Đúng là dự án đã lưu sẵn đóng góp khi huấn luyện: `feature_importance` và `family_importance` trong `data/models/eta_xgb_metadata_and_calibrator_r3_big.json`. Trainer tạo chúng tại `compute_feature_importance_ledger()`, bằng `total_gain` và số split. Ledger này tính trên **toàn bộ 708 vòng đã lưu**. Lần kiểm kê này đối chiếu lại ledger với model, đồng thời tính riêng trên **678 vòng thực sự dùng khi predict** để không trộn hai phạm vi. Mỗi feature bên dưới có cả tỷ trọng gain trong ledger gốc và trong phần model được dùng.

Các thống kê có ý nghĩa như sau:

| Số đo | Diễn giải đúng | Không được diễn giải thành |
|---|---|---|
| Gain TB | Mức cải thiện hàm mục tiêu trung bình tại các lần chia dùng feature | Số giây giảm MAE |
| Tổng gain | Tổng mức cải thiện tại các lần chia đó | Hiệu quả độc lập của feature |
| Tỷ trọng tổng gain | Tổng gain của feature / tổng gain của mọi feature, % | Phần trăm độ chính xác do feature tạo ra |
| Số split | Số nút chia sử dụng feature | Số mẫu huấn luyện |
| Cover TB / tổng cover | Trung bình / tổng độ phủ nút theo thống kê XGBoost; với objective này gắn với Hessian của mẫu | Số xe hoặc số bản ghi độc lập |

Đây là dấu vết quá trình học còn trong model, không phải log MAE theo epoch. Objective đang khai báo trong trainer là `reg:pseudohubererror`; không chuyển đơn vị gain/cover thành giây. Chưa có thí nghiệm loại từng feature rồi train lại với cùng split để đo thay đổi MAE; không bịa số liệu đó. Provenance của lần train model cũ chưa đủ để khẳng định mọi tham số trong trainer hiện tại chính là tham số đã tạo ra artifact này.

Đóng góp khi dự báo được đo bằng **TreeSHAP native XGBoost**, trên **4.990 vector feature đã ghi trong phiên raw 17/11/2026**, trước khi cài phép chiếu HMM. Số `|SHAP| TB` là trung bình trị tuyệt đối đóng góp, đơn vị **giây của phần hiệu chỉnh residual**, không phải sai số dự báo. Các dự báo trong cùng chuỗi xe/trạm có tương quan; đây không phải 4.990 hành trình độc lập, không đại diện mọi tuyến/giờ. Không gọi đây là phân phối online sau HMM.

Runtime tính `pre=max(5, baseline_p50 + residual_XGB)`, sau đó nếu có ô hiệu chỉnh: `ETA=max(5, 0,5×pre×scale + 0,5×(pre+bias))`. Vì thế baseline P50 còn tác động **trực tiếp ngoài cây**; SHAP của cây không đo toàn bộ tác động đó. Dấu và độ lớn đóng góp thay đổi theo từng mẫu, các feature tương quan chia sẻ thông tin; không có quy tắc “feature tăng thì ETA chắc chắn tăng”. Một feature luôn mặc định vẫn có thể có SHAP khác 0 vì model đã học cách xử lý giá trị đó.

Số liệu chi tiết, min/median/max, số giá trị khác nhau và hash nguồn nằm trong [ml_feature_importance.json](evidence/spec41_20261117/ml_feature_importance.json). Tái lập bằng:

```powershell
python scripts/audit_ml_feature_importance.py --session runtime/eta_live_session_20261117_raw --output runtime/ml_feature_importance_check.json
```

Script dùng category mapping trong model để tránh đổi mã tuyến khi tập live chỉ chứa một phần các category. Có kiểm tra tổng SHAP + bias khớp residual predict; kết quả số đo được ghi bên dưới. Importance được tính trên cây đã học, không suy ra từ việc feature có thay đổi trong phiên live hay không.

Đối chiếu ledger gốc với 708 cây: sai khác tương đối lớn nhất của tổng gain **0**, số split khớp từng feature. Sai khác lớn nhất giữa tổng SHAP+bias và residual predict: **0,000145 s**. Phiên đo chỉ có hai tuyến 02/27, chiều re, thứ Ba lúc 19h; không đủ để suy mức đóng góp trên toàn bộ test.

Hai lệch cần ưu tiên: nhóm probe có **10,491% tổng gain trong ledger train** nhưng ON chưa tạo probe thực; cumulative delay có **3,242% tổng gain train** nhưng ON luôn 0. Đây là mức sử dụng khi học cây, không có nghĩa sửa producer sẽ giảm MAE đúng bằng các tỷ lệ này. Trong phiên cũ, cumulative delay=0 vẫn có SHAP trung bình −8,264 s residual: model đang phản ứng với giá trị mặc định, không phải đang quan sát độ trễ tích lũy thật.

Tổng hợp đúng theo sáu nhóm trong ledger huấn luyện gốc (708 cây):

| Nhóm | Số feature | Tỷ trọng tổng gain train |
|---|---:|---:|
| Định danh, thời gian, vị trí và trạng thái ego | 23 | 43,368% |
| Baseline lịch sử | 9 | 31,147% |
| Probe thời gian chạy đoạn gần đây | 4 | 10,491% |
| Sự cố TomTom | 6 | 7,380% |
| Profile tuyến và physics kết hợp | 4 | 4,540% |
| Fleet trước/sau | 8 | 3,074% |

Nhóm incidents có gain khi học dù toàn bộ feature incidents trong phiên live cũ đều mặc định. Nhóm fleet có tỷ trọng gain nhỏ hơn nhưng vẫn có thể gây biến động ở một ca cụ thể; tỷ trọng toàn cục không thay thế phân tích trace từng xe.

## 2. Công thức và nguồn mã chung

Các đường dẫn nguồn dưới đây đều tính từ gốc repository:

- **ON:** [online_features.py](../module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/online_features.py), `build_features`, `_speed_features`, `_incident_features`, `update_observation`.
- **OFF:** [feature_store_builder.py](../module_3_bus_eta_prediction/step_3_2_feature_store_extractor/feature_store_builder.py), cách dựng dữ liệu offline hiện tại. Đọc code hiện tại không chứng minh mọi Gold/model cũ được tạo bằng phiên bản này.
- **DA:** [data_access.py](../module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/data_access.py), baseline, thứ tự tuyến, danh sách trạm, profile và nguồn incidents.
- **MODEL:** [model_runtime.py](../module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/model_runtime.py), predict residual và hiệu chỉnh; [eta_model_trainer.py](../module_3_bus_eta_prediction/step_3_3_machine_learning_models/eta_model_trainer.py), schema và trainer hiện tại.
- **PROJ:** [route_matcher.py](../module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py), HMM dùng chung; [projection_boundary.py](../module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/projection_boundary.py), adapter offline.

Ký hiệu trong các mục: `s` là lý trình xe, `S[j]` là lý trình trạm; `k` là đoạn hiện tại `[S[k],S[k+1]]`, `t` là chỉ mục trạm đích trong hành lang; `ρ=clip((S[k+1]−s)/L[k],0,1)`. `L[k]` có sàn 15 m trong ON. Với đại lượng đoạn `a`, đặt **B(a)=ρ×a[k]+Σa[j]**, tổng sau chạy từ `k+1` tới `t−1`. Baseline đoạn lấy theo tuyến, chiều, loại ngày, giờ. Thiếu ô thì ON dựng từ tốc độ tuyến: P10=0,75×P50; P90=1,35×P50; mean=P50; std=0,2×P50; tier=3. Đây là giá trị thay thế, không phải thống kê quan sát.

“Cách nên tính” bên dưới là hợp đồng đề xuất cho cả OFF/ON. Chỗ cần thông tin app chưa có được ghi rõ, không coi là sửa một công thức là xong. Đổi định nghĩa feature phải tạo lại dữ liệu và đánh giá/train lại; không giữ tên cũ rồi âm thầm đổi ý nghĩa cho model cũ.

## 3. Định danh, thời gian và vị trí — 16 feature

### 01. `route_id_idx`

- **Ý nghĩa:** Mã category của tuyến trong model, không phải số hiệu tuyến hay `route_id` API.
- **Đóng góp XGB:** Ledger train 708 cây: **3.818% tổng gain**, 5,403 split; 678 cây dùng khi predict: **3.789% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.379 s residual**.
- **Online hiện tại:** DA tra `route_idx_by_code`, xây từ danh mục tuyến baseline được sắp xếp; không có thì −1, runtime không chạy ML.
- **Nên tính:** Đóng băng bảng code→index cùng model và kiểm tra hash khi load cả OFF/ON.
- **Vấn đề:** Thêm/bớt tuyến làm đổi danh mục có thể đổi nghĩa index. Khớp số lượng category chưa chứng minh khớp tuyến. Hiện không có cơ sở coi mọi release baseline tương thích model cũ.

### 02. `direction_id`

- **Ý nghĩa:** Chiều tuyến: 0=go, 1=re.
- **Đóng góp XGB:** Ledger train 708 cây: **0.510% tổng gain**, 741 split; 678 cây dùng khi predict: **0.508% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.015 s residual**.
- **Online hiện tại:** Tham số chiều đã chuẩn hóa của luồng serving; HMM chỉ khớp theo shape chiều đang được cấp.
- **Nên tính:** Một quy tắc chuẩn hóa nguồn dùng chung OFF/ON; đổi chiều tạo lượt/state mới, không dùng lịch sử chiều cũ.
- **Vấn đề:** HMM không tự chứng minh nhãn chiều nguồn đúng. Khi nguồn báo đổi chiều chậm, xe có thể bị giữ unmatched; ép sang chiều cũ để đủ feature là sai.

### 03. `current_station_order`

- **Ý nghĩa:** Thứ tự trạm đầu đoạn xe đang nằm trên, không phải trạm gần nhất theo khoảng cách thẳng.
- **Đóng góp XGB:** Ledger train 708 cây: **0.453% tổng gain**, 1,296 split; 678 cây dùng khi predict: **0.450% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.389 s residual**.
- **Online hiện tại:** Tìm `k` bằng searchsorted trên lý trình trạm hành lang, lấy `st_orders[k]`; k bị chặn vào các đoạn hợp lệ.
- **Nên tính:** Dùng cùng danh sách trạm/geometry/ranh giới đoạn trong OFF/ON; đánh dấu ngoài hành lang thay vì chỉ chặn chỉ mục.
- **Vấn đề:** Hành lang có thể bỏ hai bến đầu/cuối; xe ngoài hành lang vẫn nhận đoạn biên. Đi qua ranh giới làm category số thứ tự đổi đột ngột, cần phân biệt thay đổi đúng với lỗi chiếu.

### 04. `target_station_order`

- **Ý nghĩa:** Thứ tự trạm đích mà dự báo hướng tới.
- **Đóng góp XGB:** Ledger train 708 cây: **0.521% tổng gain**, 926 split; 678 cây dùng khi predict: **0.515% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.640 s residual**.
- **Online hiện tại:** Không dùng thẳng `target_order` truyền vào: ánh xạ `s_target_m` về `t`, rồi lấy `st_orders[t]`; nếu t≤k ép tới k+1 khi có thể.
- **Nên tính:** Tra đúng station ID/order trong cùng catalog; không có đích hợp lệ thì không dự báo ML.
- **Vấn đề:** Ép đích hoặc clip ở biên có thể khiến order, khoảng cách và trạm HTTP không cùng ý nghĩa. Bến bị loại khỏi hành lang là ca cần kiểm chứng riêng.

### 05. `day_type`

- **Ý nghĩa:** Nhóm ngày: thường=0, thứ Bảy=1, Chủ nhật=2.
- **Đóng góp XGB:** Ledger train 708 cây: **1.420% tổng gain**, 851 split; 678 cây dùng khi predict: **1.419% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.707 s residual**.
- **Online hiện tại:** `_calendar(now_epoch)` theo múi giờ Hà Nội; OFF cũng phân loại từ thời điểm mẫu.
- **Nên tính:** Dùng cùng timestamp quyết định dự báo và timezone; duy trì mapping cùng model.
- **Vấn đề:** Không biểu diễn ngày lễ. ON dùng giờ query, OFF dùng giờ GPS; khi ping cũ hoặc qua nửa đêm có thể khác category.

### 06. `day_of_week`

- **Ý nghĩa:** Thứ trong tuần, thứ Hai=0 đến Chủ nhật=6.
- **Đóng góp XGB:** Ledger train 708 cây: **3.180% tổng gain**, 1,936 split; 678 cây dùng khi predict: **3.177% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 3.290 s residual**.
- **Online hiện tại:** `datetime.weekday()` từ giờ query Hà Nội.
- **Nên tính:** Cùng mốc thời gian như day_type và baseline, hoặc tách tuổi ping thành trường riêng khi train lại.
- **Vấn đề:** Có thông tin trùng day_type nhưng không mặc nhiên là lỗi; chưa có ablation để kết luận dư thừa. Vẫn có lệch query-time/event-time.

### 07. `hour_slot`

- **Ý nghĩa:** Ô giờ dùng chọn điều kiện giao thông/baseline.
- **Đóng góp XGB:** Ledger train 708 cây: **7.725% tổng gain**, 3,235 split; 678 cây dùng khi predict: **7.747% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 4.590 s residual**.
- **Online hiện tại:** Lấy giờ Hà Nội, chặn vào [5,21].
- **Nên tính:** Cùng quy tắc OFF/ON và cùng model; nếu hỗ trợ ngoài giờ phải có dữ liệu/ô fallback được định nghĩa.
- **Vấn đề:** 22–04 giờ bị nhập về biên dù sin/cos vẫn là giờ thật. Không thể diễn giải ô giờ là quan sát đủ 24 giờ.

### 08. `sin_time`

- **Ý nghĩa:** Thành phần sin biểu diễn chu kỳ một ngày, giúp 23h và 0h gần nhau.
- **Đóng góp XGB:** Ledger train 708 cây: **5.592% tổng gain**, 3,728 split; 678 cây dùng khi predict: **5.586% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 8.646 s residual**.
- **Online hiện tại:** `sin(2π×(giờ+phút/60)/24)`, làm tròn 4 chữ số; không dùng giây.
- **Nên tính:** Giữ một định nghĩa timestamp và độ phân giải chung OFF/ON.
- **Vấn đề:** Query-time khác event-time khi ping cũ; không mô tả trực tiếp ùn tắc hay tốc độ.

### 09. `cos_time`

- **Ý nghĩa:** Thành phần cos đi cùng sin để phân biệt vị trí trong ngày.
- **Đóng góp XGB:** Ledger train 708 cây: **7.172% tổng gain**, 3,793 split; 678 cây dùng khi predict: **7.186% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 10.543 s residual**.
- **Online hiện tại:** Cùng góc với sin_time, dùng cos và làm tròn 4 chữ số.
- **Nên tính:** Tính cùng sin trong một hàm dùng chung, cùng mốc thời gian với các feature lịch.
- **Vấn đề:** Cùng vấn đề timestamp; không suy dấu tác động ETA chỉ từ dấu cos.

### 10. `s_bus_m`

- **Ý nghĩa:** Vị trí xe theo mét dọc shape của chiều đang chạy.
- **Đóng góp XGB:** Ledger train 708 cây: **0.935% tổng gain**, 1,878 split; 678 cây dùng khi predict: **0.930% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.422 s residual**.
- **Online hiện tại:** Dùng `matched_projection[0]` từ HMM đã chuẩn bị; làm tròn 0,1 m.
- **Nên tính:** Cùng shape và matcher nhân quả cho OFF/ON, cùng chính sách reset, trùng/late ping; mọi feature dẫn xuất lấy cùng một trạng thái chiếu.
- **Vấn đề:** Gold/model hiện hữu chưa được dựng/train lại với HMM. ON sửa lại một phần lịch sử theo best_path còn OFF xuất điểm tại thời điểm xử lý: cùng s hiện tại không bảo đảm cùng lịch sử tốc độ. Độ phân giải 0,1 m không phải độ chính xác GPS.

### 11. `s_target_m`

- **Ý nghĩa:** Lý trình trạm đích trên cùng shape với xe.
- **Đóng góp XGB:** Ledger train 708 cây: **0.467% tổng gain**, 1,225 split; 678 cây dùng khi predict: **0.463% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.290 s residual**.
- **Online hiện tại:** Nhận từ trạm trong catalog, làm tròn 0,1 m.
- **Nên tính:** Version catalog/shape/trạm cùng nhau; đối chiếu đúng đích HTTP với đích dùng tính feature.
- **Vấn đề:** Chiếu GPS mới không tự cập nhật lý trình trạm đã lưu; geometry khác phiên bản có thể làm hai giá trị s không so sánh được.

### 12. `remaining_distance_m`

- **Ý nghĩa:** Quãng đường dọc tuyến từ xe đến đích.
- **Đóng góp XGB:** Ledger train 708 cây: **0.583% tổng gain**, 1,355 split; 678 cây dùng khi predict: **0.579% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 2.350 s residual**.
- **Online hiện tại:** `s_target−s_bus`, làm tròn 0,1 m; riêng feature này không chặn âm.
- **Nên tính:** Chỉ dự báo cho cùng lượt và đích còn phía trước; đã qua đích thì lọc ở lớp phục vụ, không biến số âm thành số dương giả.
- **Vấn đề:** Một số công thức physics chặn khoảng cách về 0 trong khi feature này không chặn. Lỗi lọc hoặc lệch đích có thể tạo vector tự mâu thuẫn.

### 13. `n_stations_ahead`

- **Ý nghĩa:** Số đoạn/trạm còn lại tới đích trong hành lang, không phải số điểm shape.
- **Đóng góp XGB:** Ledger train 708 cây: **1.021% tổng gain**, 1,092 split; 678 cây dùng khi predict: **1.019% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 4.475 s residual**.
- **Online hiện tại:** `t−k` sau bước ánh xạ/ép t.
- **Nên tính:** Tính từ đúng đoạn hiện tại và trạm đích hợp lệ; cùng quy tắc tại đúng ranh giới trạm OFF/ON.
- **Vấn đề:** Ép t khiến gần đích vẫn thường là một hop. Trường này còn chọn bucket calibrator 1 / 2–5 / 6–15 / >15, nên đổi bucket có tác động ngoài XGB và có thể gây bước nhảy ETA.

### 14. `progress_ratio`

- **Ý nghĩa:** Phần chiều dài toàn shape xe đã đi qua.
- **Đóng góp XGB:** Ledger train 708 cây: **0.650% tổng gain**, 1,828 split; 678 cây dùng khi predict: **0.647% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.046 s residual**.
- **Online hiện tại:** `s_bus/max(1,r_len)`, làm tròn 4 chữ số; r_len là lý trình điểm shape cuối.
- **Nên tính:** Dùng cùng điểm gốc và chiều dài shape với OFF; kiểm tra s và r_len hợp lệ trước khi chia.
- **Vấn đề:** Không có clip [0,1] ở đây. Mẫu số không phải chiều dài hành lang trạm; không được diễn giải thành phần trăm hành trình quan sát được.

### 15. `target_progress_ratio`

- **Ý nghĩa:** Vị trí tương đối của trạm đích trên toàn shape.
- **Đóng góp XGB:** Ledger train 708 cây: **0.323% tổng gain**, 1,298 split; 678 cây dùng khi predict: **0.318% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.243 s residual**.
- **Online hiện tại:** `s_target/max(1,r_len)`, làm tròn 4 chữ số.
- **Nên tính:** Cùng geometry/version với progress_ratio và s_target.
- **Vấn đề:** Tương quan cao với s_target; sai shape/chiều dài gây sai đồng thời nhiều feature. Chưa có ablation chứng minh nên bỏ.

### 16. `dist_to_next_station_m`

- **Ý nghĩa:** Quãng đường tới trạm cuối đoạn hiện tại.
- **Đóng góp XGB:** Ledger train 708 cây: **2.192% tổng gain**, 2,778 split; 678 cây dùng khi predict: **2.197% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.975 s residual**.
- **Online hiện tại:** `max(0,S[k+1]−s_bus)`.
- **Nên tính:** Cùng định nghĩa đoạn và trạm; sau khi qua trạm chuyển đoạn theo vị trí đã khớp, tránh rung qua lại ranh giới.
- **Vấn đề:** Gần bến ngoài hành lang có thể bị 0 do clip. Đường đi gần trạm không đồng nghĩa đã dừng đón khách.

## 4. Trạng thái và vận tốc xe — 7 feature

### 17. `ego_speed_instant_kmh`

- **Ý nghĩa:** Vận tốc dịch chuyển ngắn hạn, thực tế không phải vận tốc tức thời của thiết bị.
- **Đóng góp XGB:** Ledger train 708 cây: **0.836% tổng gain**, 2,236 split; 678 cây dùng khi predict: **0.835% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 2.684 s residual**.
- **Online hiện tại:** Δs/Δt trên cửa sổ lùi khoảng 75 s; thiếu lịch sử dùng điểm cũ nhất, dt tối thiểu 10 s, clip [0,80]. Không đủ dt dùng raw_speed_kmh, thiếu nữa dùng speed_kmh hiển thị.
- **Nên tính:** Chọn cửa sổ theo thời gian và chất lượng timestamp cho cả OFF/ON; fallback cần có tuổi/nguồn/chất lượng rõ, không coi ngang với vận tốc quan sát.
- **Vấn đề:** OFF dùng speed của từng điểm Silver, thường là Δs/Δt hai điểm liên tiếp. Nhịp BusMap/TimBus khác nhau; timestamp fetch không chứng minh GPS mới. Cold start và HMM sửa lịch sử có thể đổi giá trị mạnh.

### 18. `ego_speed_roll3_kmh`

- **Ý nghĩa:** Tốc độ trung hạn, làm mượt hơn instant.
- **Đóng góp XGB:** Ledger train 708 cây: **0.404% tổng gain**, 1,104 split; 678 cây dùng khi predict: **0.403% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.894 s residual**.
- **Online hiện tại:** Δs/Δt lùi khoảng 240 s, dt≥10 s; thiếu cửa sổ dùng lịch sử hiện có, không đủ thì instant.
- **Nên tính:** Dùng cửa sổ thời gian chung OFF/ON, định nghĩa khi thiếu history và khi đứng yên; không đòi cùng số mẫu ở hai nguồn khác heartbeat.
- **Vấn đề:** OFF dùng i−3 mẫu, thời gian thực tế biến thiên. Tên roll3 không phải trung bình ba speed. Ring chỉ giữ tối đa 160 điểm/600 s và có gộp mẫu; cửa sổ thực tế phải đo theo timestamp.

### 19. `ego_speed_roll5_kmh`

- **Ý nghĩa:** Tốc độ dài hạn hơn để nhận biết xu hướng chậm/nhanh.
- **Đóng góp XGB:** Ledger train 708 cây: **1.301% tổng gain**, 1,513 split; 678 cây dùng khi predict: **1.302% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.244 s residual**.
- **Online hiện tại:** Δs/Δt lùi khoảng 405 s, dt≥15 s; thiếu thì dùng roll3.
- **Nên tính:** Cùng hợp đồng theo thời gian như roll3, ghi độ dài cửa sổ thực có; reset theo lượt/chiều.
- **Vấn đề:** OFF lùi 5 mẫu, không cố định 405 s. Khi mới mở app, cả ba tốc độ có thể trùng do fallback, không phải có đủ ba quan sát độc lập.

### 20. `ego_accel_kmh_per_min`

- **Ý nghĩa:** Chênh tốc độ hai cửa sổ chia thời gian; chỉ báo xu hướng, không phải gia tốc vật lý tức thời.
- **Đóng góp XGB:** Ledger train 708 cây: **0.124% tổng gain**, 521 split; 678 cây dùng khi predict: **0.123% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.106 s residual**.
- **Online hiện tại:** `(roll3−roll5)/max(0,5,dt5/60)`, thiếu roll5 dùng mẫu số 1 phút; clip ±30 km/h/phút.
- **Nên tính:** Chung công thức/cửa sổ/clip OFF/ON; nếu cần gia tốc thật phải đổi định nghĩa, dùng hai ước lượng vận tốc gắn thời điểm và train lại.
- **Vấn đề:** OFF hiện không có clip ±30 ở phép tính này. Hai cửa sổ chồng lấn; dấu dương chỉ là cửa sổ ngắn nhanh hơn dài, không chứng minh xe đang tăng tốc ngay lúc query.

### 21. `ego_speed_ratio_vs_baseline`

- **Ý nghĩa:** Xe nhanh/chậm bao nhiêu lần so với tốc độ lịch sử đoạn hiện tại.
- **Đóng góp XGB:** Ledger train 708 cây: **0.595% tổng gain**, 1,693 split; 678 cây dùng khi predict: **0.595% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 2.971 s residual**.
- **Online hiện tại:** `clip(roll3 / max(3.0, 3.6*L[k]/max(1.0,P50[k])), 0.1, 3.0)`.
- **Nên tính:** Cùng baseline snapshot và tốc độ cửa sổ đã thống nhất; giữ thông tin thiếu baseline/thiếu speed để tránh hiểu ratio=1 là quan sát bình thường.
- **Vấn đề:** Sàn 3 km/h và clip làm xe đứng yên vẫn nhận ratio 0,1. Khi qua ranh giới đoạn, baseline đổi nên ratio đổi ngay cả khi speed không đổi.

### 22. `ego_trip_elapsed_sec`

- **Ý nghĩa mong muốn:** Thời gian đã quan sát trong lượt xe hiện tại.
- **Đóng góp XGB:** Ledger train 708 cây: **0.304% tổng gain**, 1,228 split; 678 cây dùng khi predict: **0.301% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 2.462 s residual**.
- **Online hiện tại:** **Không đo thời gian**: `ΣP50[j], j<k + (1−ρ)×P50[k]` — thời gian lịch sử dự kiến từ đầu hành lang tới vị trí xe.
- **Nên tính:** Nếu giữ định nghĩa OFF hiện tại, lấy `t_event−t_first_seen_in_trip` với cùng bộ chia lượt; không biết đầu lượt thì có cờ thiếu/tuổi quan sát. Nếu muốn thời gian từ xuất bến thật phải có bằng chứng xuất bến.
- **Vấn đề:** OFF dùng `t_cur−tr_epochs[0]`. ON trả lời câu hỏi khác và không bắt được xe chậm thật. App mở giữa lượt không biết giờ xuất phát; không thể suy ra thời gian thật chỉ bằng s và baseline.

### 23. `ego_cum_delay_vs_baseline_sec`

- **Ý nghĩa:** Độ chậm tích lũy so với thời gian lịch sử trên phần đường đã quan sát.
- **Đóng góp XGB:** Ledger train 708 cây: **3.242% tổng gain**, 2,489 split; 678 cây dùng khi predict: **3.252% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 8.264 s residual**.
- **Online hiện tại:** **Luôn 0**, không có bộ theo dõi độ trễ tích lũy.
- **Nên tính:** Ghi lần xe qua một trạm neo đã quan sát, lấy elapsed từ neo trừ baseline đúng cùng quãng đường; thống nhất OFF/ON và reset theo lượt. Chưa có neo thì thiếu, không khẳng định đúng giờ.
- **Vấn đề:** OFF dùng thời gian từ trạm đầu có arrival tới hiện tại trừ tổng baseline tới đầu đoạn hiện tại, clip [−600,1800]. Công thức còn gồm thời gian xe đang chạy trong đoạn hiện tại nhưng baseline mới tới đầu đoạn: cần sửa định nghĩa cả hai phía, không sao chép máy móc. Dữ liệu test cũ có trường này khác 0 ở 3.480.276/3.704.820 dòng.

## 5. Xe phía trước, phía sau và đội xe — 8 feature

Fleet ON là snapshot các xe cùng tuyến/chiều đã khớp HMM. Khoảng cách phân biệt trước/sau tối thiểu 20 m. Không có xe thì khoảng cách=25.000 m; tốc độ=tốc độ tuyến; lead ratio=1. Đây là sentinel/fallback, không phải xe có thật ở cách 25 km.

### 24. `lead_bus_dist_ahead_m`

- **Ý nghĩa:** Khoảng cách dọc tuyến tới xe gần nhất phía trước.
- **Đóng góp XGB:** Ledger train 708 cây: **0.433% tổng gain**, 1,255 split; 678 cây dùng khi predict: **0.424% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.391 s residual**.
- **Online hiện tại:** Min(s_other−s_ego)>20 m, trong fleet cùng chiều; mặc định 25.000 m.
- **Nên tính:** Chỉ dùng vị trí đủ mới theo event time, cùng lượt/shape, công khai missing; lựa chọn xe trước cần ổn định khi nguồn mất/gộp xe.
- **Vấn đề:** Có thể chọn xe đã vượt trạm đích. Không quan sát đủ fleet hoặc GPS cũ làm “không thấy xe” bị hiểu như “không có xe”. OFF dùng fleet tích lũy có TTL, ON dựng lại snapshot mỗi lần.

### 25. `lead_bus_time_headway_sec`

- **Ý nghĩa hiện thực:** Thời gian ước tính ego cần đi hết khoảng cách tới vị trí hiện tại của xe trước.
- **Đóng góp XGB:** Ledger train 708 cây: **0.161% tổng gain**, 729 split; 678 cây dùng khi predict: **0.159% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.035 s residual**.
- **Online hiện tại:** `min(3600, lead_distance/max(1.5, roll3/3.6))`.
- **Nên tính:** Giữ và đặt đúng nghĩa proxy khoảng cách/tốc độ nếu dùng model cũ; muốn headway thật thì đo chênh thời điểm hai xe qua cùng một mốc và train lại.
- **Vấn đề:** Không phải chênh giờ qua trạm, cũng không phải thời gian đuổi kịp xe đang chạy. Không có lead vẫn sinh số hữu hạn tới 3.600 s; xe dừng vẫn dùng sàn 1,5 m/s.

### 26. `lead_bus_speed_kmh`

- **Ý nghĩa:** Tốc độ gần đây của xe được chọn là lead.
- **Đóng góp XGB:** Ledger train 708 cây: **0.366% tổng gain**, 881 split; 678 cây dùng khi predict: **0.362% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.178 s residual**.
- **Online hiện tại:** Fleet tính roll3 từ lịch sử xe trước; thiếu thì instant rồi raw/UI; không lead dùng route_base_speed.
- **Nên tính:** Chung cửa sổ thời gian, cùng bộ chiếu, kiểm tra freshness và cold start riêng cho từng xe; giữ lịch sử đủ lâu.
- **Vấn đề:** Đổi danh tính lead, reset, fallback hoặc chọn nhánh chiếu khác đều làm speed nhảy. Cú 17→3 km/h không tự chứng minh giao thông đột ngột xấu đi; cần xem cả ID, tuổi ping, cửa sổ và s.

### 27. `lead_bus_speed_ratio`

- **Ý nghĩa:** Tốc độ lead so với baseline tại đoạn của chính lead.
- **Đóng góp XGB:** Ledger train 708 cây: **1.243% tổng gain**, 488 split; 678 cây dùng khi predict: **1.248% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.822 s residual**.
- **Online hiện tại:** Lấy ratio trong fleet, clip [0,1;3]; thiếu lead dùng 1.
- **Nên tính:** Cùng chuẩn tốc độ/baseline như ego ratio; phân biệt thiếu lead với lead đúng tốc độ lịch sử.
- **Vấn đề:** Lead có thể nằm ở đoạn khác hoặc ngoài đường tới đích. Baseline đổi khi lead qua trạm có thể làm ratio đổi trong khi tốc độ giữ nguyên.

### 28. `follow_bus_dist_behind_m`

- **Ý nghĩa:** Khoảng cách dọc tuyến tới xe gần nhất phía sau.
- **Đóng góp XGB:** Ledger train 708 cây: **0.187% tổng gain**, 887 split; 678 cây dùng khi predict: **0.181% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.072 s residual**.
- **Online hiện tại:** Min(s_ego−s_other)>20 m; thiếu dùng 25.000 m.
- **Nên tính:** Cùng kiểm tra định danh, chiều và timestamp như lead; thêm trạng thái thiếu khi train lại.
- **Vấn đề:** Các xe sát trong 20 m bị bỏ qua; mất telemetry khác với giãn cách thật. Chưa có cơ sở diễn giải trực tiếp follow xa làm ETA tăng hay giảm.

### 29. `follow_bus_speed_kmh`

- **Ý nghĩa:** Tốc độ gần đây của xe được chọn là follow.
- **Đóng góp XGB:** Ledger train 708 cây: **0.153% tổng gain**, 754 split; 678 cây dùng khi predict: **0.150% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.256 s residual**.
- **Online hiện tại:** Lấy speed từ cùng fleet; không follow dùng tốc độ tuyến.
- **Nên tính:** Cùng cửa sổ thời gian/nguồn/chất lượng như lead speed.
- **Vấn đề:** Cold start và đổi xe follow tạo bước nhảy; tốc độ lịch sử thay thế không phải thông tin giao thông mới.

### 30. `n_active_buses_on_route`

- **Ý nghĩa:** Số xe quan sát được trong fleet tuyến/chiều, gồm ego nếu có.
- **Đóng góp XGB:** Ledger train 708 cây: **0.084% tổng gain**, 343 split; 678 cây dùng khi predict: **0.081% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.634 s residual**.
- **Online hiện tại:** `len(fleet)` sau projection; fleet được dựng lại và gắn `now_epoch` cho từng xe trong snapshot.
- **Nên tính:** Đếm ID đủ mới theo event time với TTL chung OFF/ON; ghi độ phủ nguồn, không đặt tên thành tổng xe thực đang vận hành.
- **Vấn đề:** Vòng dọn TTL ON so với timestamp vừa gắn now nên không tự loại ping cũ trong snapshot. OFF duy trì state với TTL theo mẫu. Pruned loại feature này, không có nghĩa full không sử dụng nó.

### 31. `n_buses_in_corridor_ahead`

- **Ý nghĩa:** Số xe quan sát được giữa ego và trạm đích.
- **Đóng góp XGB:** Ledger train 708 cây: **0.448% tổng gain**, 305 split; 678 cây dùng khi predict: **0.446% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.525 s residual**.
- **Online hiện tại:** Đếm `s_other−s_ego>20` và `s_other≤s_target`, bỏ ego.
- **Nên tính:** Cùng fleet đủ mới/định danh rõ; dùng s_target đúng với đích dự báo.
- **Vấn đề:** Phụ thuộc độ phủ API và khả năng khớp HMM. Số xe giảm có thể do dữ liệu mất hoặc xe bị reject, không phải dòng giao thông đã thông thoáng.

## 6. Thời gian xe đã đi qua đoạn đường gần đây — 4 feature

**Cả bốn trường dưới đây chưa có producer online thực sự.** OFF lấy sự kiện hoàn tất đoạn có thời điểm≤t_cur, còn mới trong 1.800 s; thiếu đoạn nào dùng baseline đoạn đó. Đây là thời gian chạy đoạn quan sát từ lịch sử fleet, không đồng nhất với tốc độ lead ở snapshot hiện tại. Danh sách completion OFF không giữ vehicle ID trong tuple đang sử dụng, nên chưa thể bảo đảm probe luôn là một xe khác ego.

### 32. `recent_corridor_tt_sum_sec`

- **Ý nghĩa:** Thời gian dự kiến tới đích nếu lấy thời gian hoàn tất đoạn gần đây thay cho lịch sử ở đoạn có probe.
- **Đóng góp XGB:** Ledger train 708 cây: **1.629% tổng gain**, 1,378 split; 678 cây dùng khi predict: **1.625% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.661 s residual**.
- **Online hiện tại:** **Gán bằng baseline_eta_p50_sec**, kể cả khi app đã chạy lâu.
- **Nên tính:** Theo dõi xe qua hai trạm liên tiếp, chỉ công bố traversal sau khi hoàn tất/đã nhận đủ bằng chứng; chọn probe mới trong 1.800 s; `B(TT_recent_or_P50)`.
- **Vấn đề:** Cần state crossing theo xe/lượt và timestamp; không thể lấy speed lead nhân khoảng cách rồi gọi là traversal. Đổi heartbeat và arrival interpolation ảnh hưởng trực tiếp TT.

### 33. `recent_corridor_congestion_ratio`

- **Ý nghĩa:** Thời gian từ probe so với baseline trên cùng đường tới đích.
- **Đóng góp XGB:** Ledger train 708 cây: **7.104% tổng gain**, 2,163 split; 678 cây dùng khi predict: **7.128% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.142 s residual**.
- **Online hiện tại:** **Luôn 1**.
- **Nên tính:** `clip(recent_corridor_tt_sum/max(1,baseline_p50),0.3,3.5)` sau khi có producer; đi cùng coverage/tuổi probe.
- **Vấn đề:** ON không phản ánh chậm nhanh từ traversal. OFF có thể trộn các đoạn từ nhiều xe/thời điểm, không phải thời gian một xe chạy toàn hành lang liên tục.

### 34. `recent_seg_coverage_ratio`

- **Ý nghĩa:** Tỷ lệ số đoạn tới đích có probe đủ mới.
- **Đóng góp XGB:** Ledger train 708 cây: **1.160% tổng gain**, 1,223 split; 678 cây dùng khi predict: **1.152% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 4.141 s residual**.
- **Online hiện tại:** **Luôn 0**.
- **Nên tính:** Số đoạn có completion hợp lệ trong cửa sổ / số đoạn cần đi; thống nhất có tính đoạn hiện tại hay không (OFF hiện tính có).
- **Vấn đề:** OFF train có giá trị>0 ở **9.474.608/11.364.661** dòng, test **3.034.766/3.704.820**; 4.990 vector live cũ đều 0. Các số đếm offline thuộc lần quét dữ liệu đã lưu trong [behavior_summary.json](evidence/spec41_20261117/behavior_summary.json), không phải phân phối của dữ liệu đã dựng lại sau HMM. Đây là lệch đã đo, không chỉ nguy cơ. Tỷ lệ theo số đoạn không đại diện phần chiều dài hay thời gian được quan sát.

### 35. `recent_next_seg_congestion_ratio`

- **Ý nghĩa trong code:** TT probe / P50 của **đoạn hiện tại còn phải đi**, không phải nhất thiết đoạn sau trạm kế tiếp.
- **Đóng góp XGB:** Ledger train 708 cây: **0.599% tổng gain**, 757 split; 678 cây dùng khi predict: **0.600% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.379 s residual**.
- **Online hiện tại:** **Luôn 1**.
- **Nên tính:** `clip(TT_recent_or_P50[k]/max(1,P50[k]),0.3,3.5)`; giữ đúng chỉ mục OFF và đặt tên rõ khi đổi schema.
- **Vấn đề:** Tên “next” dễ hiểu sai. Không có probe và có probe ratio=1 hiện không phân biệt ở trường này; phải đọc cùng coverage/availability.

## 7. Baseline lịch sử — 9 feature

Các feature sau lấy từ bảng thống kê lịch sử, không phải một model ML khác. Tổng các phân vị đoạn không đương nhiên là phân vị của tổng thời gian hành trình. Cần đóng băng baseline chỉ từ dữ liệu quá khứ hợp lệ của split; baseline chứa dữ liệu validation/test sẽ làm đánh giá lạc quan. Model cũ chưa có provenance đủ để xóa nghi ngờ chỉ bằng việc code mới đã chặn leakage.

### 36. `baseline_eta_p50_sec`

- **Ý nghĩa:** Thời gian tham chiếu từ trung vị các đoạn trên đường còn lại.
- **Đóng góp XGB:** Ledger train 708 cây: **0.638% tổng gain**, 785 split; 678 cây dùng khi predict: **0.639% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 2.113 s residual**.
- **Online hiện tại:** `B(P50)`; đồng thời được cộng thẳng với residual ngoài XGB.
- **Nên tính:** Chung baseline version và công thức phần đoạn OFF/ON; thiếu ô cần có quality tier/flag; đo calibration so với arrival thật theo horizon.
- **Vấn đề:** Đây không được bảo đảm là median tổng hành trình. Baseline trong feature và fallback của ETA policy có thể dùng quy tắc thay ô thiếu khác nhau; không coi hai con số tự động đồng nhất.

### 37. `baseline_eta_mean_sec`

- **Ý nghĩa:** Tổng thời gian trung bình tham chiếu trên đường còn lại.
- **Đóng góp XGB:** Ledger train 708 cây: **0.165% tổng gain**, 415 split; 678 cây dùng khi predict: **0.163% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.276 s residual**.
- **Online hiện tại:** `B(mean)`.
- **Nên tính:** Thống kê mean từ dữ liệu đúng cutoff; cùng quy tắc phần đoạn và cùng đơn vị.
- **Vấn đề:** Nhân thời gian đoạn với phần chiều dài giả sử thời gian phân bố đều; dừng trạm/đèn đỏ không phân bố đều. Khi fallback mean=P50 thì mất khác biệt thực giữa hai đại lượng.

### 38. `baseline_eta_p10_sec`

- **Ý nghĩa:** Tham chiếu tình huống nhanh từ P10 các đoạn.
- **Đóng góp XGB:** Ledger train 708 cây: **0.243% tổng gain**, 850 split; 678 cây dùng khi predict: **0.242% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.117 s residual**.
- **Online hiện tại:** `B(P10)`; ô thiếu dùng 0,75×P50.
- **Nên tính:** Giữ là tổng tham chiếu P10 đoạn; muốn P10 hành trình phải ước lượng/kiểm chứng phân phối tổng riêng.
- **Vấn đề:** Không được gọi đây là mốc mà chắc chắn 10% xe đến sớm hơn. Fallback là hệ số đặt trước, không có độ phủ xác suất được kiểm định.

### 39. `baseline_eta_p90_sec`

- **Ý nghĩa:** Tham chiếu tình huống chậm từ P90 các đoạn.
- **Đóng góp XGB:** Ledger train 708 cây: **0.578% tổng gain**, 726 split; 678 cây dùng khi predict: **0.576% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.657 s residual**.
- **Online hiện tại:** `B(P90)`; ô thiếu dùng 1,35×P50.
- **Nên tính:** Cùng định nghĩa như P10; nếu dùng làm khoảng dự báo phải đo tỷ lệ arrival nằm trong khoảng theo nhóm horizon.
- **Vấn đề:** Cộng P90 không cho P90 tổng; phụ thuộc giữa các đoạn có thể rất lớn. Không có cơ sở gọi [P10,P90] này là khoảng tin cậy 80% đã hiệu chỉnh.

### 40. `baseline_eta_iqr_sec`

- **Ý nghĩa thực trong code:** Độ rộng **P90−P10** tham chiếu.
- **Đóng góp XGB:** Ledger train 708 cây: **9.047% tổng gain**, 3,624 split; 678 cây dùng khi predict: **9.079% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 3.470 s residual**.
- **Online hiện tại:** `max(1,base_p90−base_p10)`.
- **Nên tính:** Giữ giá trị để tương thích model cũ nhưng mô tả đúng; nếu cần IQR đúng nghĩa thì P75−P25, đổi schema và train lại.
- **Vấn đề:** Tên IQR hiện sai nghĩa thống kê thông thường. Sàn 1 s không phải độ bất định quan sát tối thiểu.

### 41. `baseline_eta_rss_std_sec`

- **Ý nghĩa:** Độ phân tán tham chiếu từ căn tổng phương sai đoạn.
- **Đóng góp XGB:** Ledger train 708 cây: **3.616% tổng gain**, 4,790 split; 678 cây dùng khi predict: **3.613% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 4.416 s residual**.
- **Online hiện tại:** `sqrt(max(1,ρ²×var[k]+Σvar[j]))`.
- **Nên tính:** Giữ là xấp xỉ RSS; muốn std tổng thật cần xét covariance hoặc đo trực tiếp theo hành trình.
- **Vấn đề:** Bỏ tương quan ùn tắc giữa các đoạn; ρ² cũng là giả thiết về phần thời gian đoạn. Không dùng làm sai số chuẩn của ETA ML nếu chưa kiểm chứng.

### 42. `baseline_skew_sec`

- **Ý nghĩa thực trong code:** Chênh mean và median tham chiếu, đơn vị giây.
- **Đóng góp XGB:** Ledger train 708 cây: **11.232% tổng gain**, 3,479 split; 678 cây dùng khi predict: **11.271% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 15.557 s residual**.
- **Online hiện tại:** `base_mean−base_p50`.
- **Nên tính:** Mô tả đúng là mean-minus-median; nếu cần skewness chuẩn hóa phải tính lại và train lại.
- **Vấn đề:** Không phải moment bậc ba chuẩn hóa; không so độ lệch phân phối giữa hành trình dài/ngắn chỉ bằng số giây này.

### 43. `baseline_max_seg_p90_sec`

- **Ý nghĩa:** P90 lớn nhất của một đoạn trong phần đường tới đích, proxy đoạn dễ chậm.
- **Đóng góp XGB:** Ledger train 708 cây: **4.315% tổng gain**, 6,838 split; 678 cây dùng khi predict: **4.309% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.396 s residual**.
- **Online hiện tại:** `max(P90[k:t])`, gồm toàn P90 đoạn hiện tại, không nhân ρ.
- **Nên tính:** Chốt rõ giữ đặc điểm nguyên đoạn hay phần còn lại; OFF/ON phải giống nhau. Nếu muốn nút thắt còn phải trải qua, xem xét phần đoạn còn lại và vị trí dừng thực.
- **Vấn đề:** Xe gần ra khỏi đoạn vẫn mang toàn P90 của đoạn đó; qua trạm có thể rơi đột ngột. Không tự kết luận đó là lỗi model, cần soi trace tại ranh giới.

### 44. `baseline_tier0_frac`

- **Ý nghĩa:** Tỷ lệ số đoạn có ô baseline thuộc quality tier 0.
- **Đóng góp XGB:** Ledger train 708 cây: **1.312% tổng gain**, 881 split; 678 cây dùng khi predict: **1.310% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.647 s residual**.
- **Online hiện tại:** Số ô tier0 trong `[k,t)` / max(1,t−k), clip [0,1]; ô giả định thuộc tier3.
- **Nên tính:** Cùng định nghĩa quality tier và snapshot; giữ tỷ lệ theo đoạn nếu tương thích model, bổ sung độ phủ theo quãng đường/thời gian khi đổi schema.
- **Vấn đề:** Đoạn rất ngắn và rất dài có trọng số bằng nhau; không phải phần trăm dữ liệu chuẩn xác hay mức tin cậy trực tiếp của dự báo.

## 8. Sự cố TomTom — 6 feature

**Có code xử lý incidents**, nhưng nguồn ON hiện là Silver Parquet cục bộ, nạp theo tuyến và cache RAM; chưa phải feed TomTom cập nhật liên tục trong app. Thiếu hoặc lỗi đọc partition trả về rỗng và cache kết quả đó. Trong phiên raw 17/11, toàn bộ 4.990 vector có count/delay/magnitude/jam=0 và nearest=25.000; không được suy ra “thực tế không có sự cố”.

ON chọn episode có `t_start≤now≤t_end`, đúng chiều và giao với `[s_bus,s_target]`. `ov=min(s_target,s_max)−max(s_bus,s_min)`; code cho phép `ov=0`. Trọng số delay `f=clip(ov/max(20,s_max−s_min),0.1,1)`. Các quyết định này tồn tại cả OFF: nhất quán không có nghĩa hợp lý. Cần xác minh episode/t_end và thời điểm thông tin thực được nhận: replay được episode hoàn chỉnh chưa chứng minh online đã biết mọi trường tại thời điểm dự báo.

### 45. `inc_ahead_count`

- **Ý nghĩa:** Số episode sự cố đang hiệu lực trên đường tới đích theo nguồn được nạp.
- **Đóng góp XGB:** Ledger train 708 cây: **0.300% tổng gain**, 464 split; 678 cây dùng khi predict: **0.296% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.102 s residual**.
- **Online hiện tại:** Đếm episode giao hành lang, kể cả chỉ chạm biên (`ov=0`).
- **Nên tính:** Dùng incident ID/version và thời điểm nhận; quy định giao dương hay sự cố dạng điểm; deduplicate bản tin cập nhật cùng incident, có freshness/availability.
- **Vấn đề:** Nguồn cục bộ cũ/cache không refresh. Chưa xác minh episode trùng có bị đếm nhiều lần; count=0 trộn không sự cố với không dữ liệu.

### 46. `inc_ahead_total_delay_sec`

- **Ý nghĩa:** Tổng delay sự cố đã phân bổ cho phần giao đường tới đích.
- **Đóng góp XGB:** Ledger train 708 cây: **3.011% tổng gain**, 1,085 split; 678 cây dùng khi predict: **3.019% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.610 s residual**.
- **Online hiện tại:** `Σ delay_episode×f`, f có sàn 0,1.
- **Nên tính:** Chốt ý nghĩa delay nguồn và phép phân bổ; nếu theo chiều dài thì giao 0 không nên tự có 10% delay, ngoại trừ sự cố điểm được xử lý riêng; tránh cộng trùng cùng sự cố.
- **Vấn đề:** Có thể thêm delay dù chỉ chạm biên. Delay TomTom không đương nhiên bằng delay xe buýt; không cộng trực tiếp như một đo đạc ETA thật.

### 47. `inc_ahead_max_delay_sec`

- **Ý nghĩa:** Delay nguyên episode lớn nhất trong các episode được chọn.
- **Đóng góp XGB:** Ledger train 708 cây: **2.744% tổng gain**, 1,429 split; 678 cây dùng khi predict: **2.744% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.745 s residual**.
- **Online hiện tại:** Max delay gốc, **không nhân phần overlap**; rỗng=0.
- **Nên tính:** Ghi rõ muốn severity toàn sự cố hay delay phần còn phải đi; giữ đúng cả OFF/ON và cùng version nguồn.
- **Vấn đề:** Có thể lớn hơn total_delay đã nhân overlap; không phải tự mâu thuẫn toán học nhưng dễ hiểu sai. Chạm biên cũng nhận nguyên max delay.

### 48. `inc_ahead_max_magnitude`

- **Ý nghĩa:** Mức nghiêm trọng lớn nhất theo mã magnitude nguồn TomTom.
- **Đóng góp XGB:** Ledger train 708 cây: **0.302% tổng gain**, 204 split; 678 cây dùng khi predict: **0.303% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.443 s residual**.
- **Online hiện tại:** Max magnitude của episode được chọn; thiếu magnitude fill 0.
- **Nên tính:** Giữ mapping nguồn đã version; phân biệt unknown với mức 0, không tự biến category thành một thang đo vật lý.
- **Vấn đề:** Feature đang là số, nhưng khoảng cách giữa các mã không phải số giây delay. Unknown/missing và không sự cố có thể trùng giá trị.

### 49. `inc_ahead_jam_length_m`

- **Ý nghĩa trong code:** Tổng chiều dài overlap của episode với hành lang còn lại.
- **Đóng góp XGB:** Ledger train 708 cây: **0.750% tổng gain**, 913 split; 678 cây dùng khi predict: **0.745% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.095 s residual**.
- **Online hiện tại:** `Σov`; không dùng trường overlap_length_m đã đọc trong tuple để cộng.
- **Nên tính:** Nếu muốn chiều dài đường bị ảnh hưởng, tính hợp các khoảng theo cùng chiều; nếu muốn tổng có lặp thì phải đặt đúng nghĩa. Kiểm tra geometry incident, không mặc định mọi loại incident đều là hàng xe ùn tắc.
- **Vấn đề:** Các episode chồng nhau có thể cộng vượt chiều dài hành lang; khoảng min/max s có thể phủ cả đoạn không thật bị ảnh hưởng.

### 50. `inc_dist_to_nearest_m`

- **Ý nghĩa:** Khoảng cách tới đầu sự cố gần nhất trên đường còn lại.
- **Đóng góp XGB:** Ledger train 708 cây: **0.272% tổng gain**, 476 split; 678 cây dùng khi predict: **0.267% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.289 s residual**.
- **Online hiện tại:** `min(max(0,s_min−s_bus))` trên các episode được chọn; không có dùng 25.000 m.
- **Nên tính:** Cùng geometry/chiều, có cờ nguồn đủ mới và missing; xe đang trong vùng sự cố thì 0.
- **Vấn đề:** Sentinel giống một khoảng cách thật; nguồn không có dữ liệu vẫn trông như không có sự cố gần. Feature hằng trong phiên không chứng minh model bỏ qua nó.

## 9. Profile tuyến và feature kết hợp — 4 feature

### 51. `route_base_speed_kmh`

- **Ý nghĩa:** Tốc độ nền tuyến/chiều, làm prior khi thiếu quan sát.
- **Đóng góp XGB:** Ledger train 708 cây: **1.731% tổng gain**, 1,959 split; 678 cây dùng khi predict: **1.731% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.773 s residual**.
- **Online hiện tại:** DA lấy tổng distance / tổng P50 time trong aggregate baseline rồi ×3,6; thiếu dùng DEFAULT_URBAN_BUS_SPEED_KMPH, cache profile.
- **Nên tính:** Đóng băng cách tổng hợp/nguồn/cutoff cùng baseline, OFF/ON cùng danh mục ô và trọng số.
- **Vấn đề:** Không phải trung bình trực tiếp mọi speed GPS. Tổng qua các ô ngày/giờ phụ thuộc độ phủ baseline; prior sai sẽ đi vào fallback fleet và cả hai feature physics.

### 52. `route_station_spacing_m`

- **Ý nghĩa:** Khoảng cách trung bình giữa các trạm trong hành lang đang dùng.
- **Đóng góp XGB:** Ledger train 708 cây: **1.273% tổng gain**, 1,919 split; 678 cây dùng khi predict: **1.264% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 2.314 s residual**.
- **Online hiện tại:** `max(100,S[last]−S[first])/max(1,n_stations−1)`, làm tròn 0,1 m; dưới hai trạm trả 0.
- **Nên tính:** Chung tập trạm/shape OFF/ON, xử lý catalog thiếu như lỗi/chất lượng dữ liệu, không giả bộ là tuyến có spacing=0.
- **Vấn đề:** Thường là hằng theo tuyến/chiều, có thể giúp nhận diện tuyến hơn là giao thông. Không mô tả khoảng cách cụ thể đoạn ego đang chạy.

### 53. `physics_kinematic_eta_sec`

- **Ý nghĩa:** ETA proxy từ khoảng cách và tốc độ trộn giữa quan sát và lịch sử.
- **Đóng góp XGB:** Ledger train 708 cây: **0.614% tổng gain**, 932 split; 678 cây dùng khi predict: **0.610% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 1.387 s residual**.
- **Online hiện tại:** `v_eff=clip((0.6×roll3+0.4×route_base_speed)/3.6,2,18)` m/s; `min(7200,max(0,remaining)/v_eff)`.
- **Nên tính:** Giữ như feature ước lượng có sàn/trần đã công bố; kiểm chứng riêng xe dừng, gần trạm và horizon xa. Nếu đổi trọng số/sàn thì áp dụng OFF/ON và train lại.
- **Vấn đề:** Xe đứng yên vẫn có vận tốc hiệu dụng≥2 m/s; không mô hình hóa dwell hay đèn đỏ riêng. Tên physics không bảo đảm đúng vật lý; thông tin gốc vẫn là distance, roll3 và prior.

### 54. `physics_probe_corrected_eta_sec`

- **Ý nghĩa:** ETA proxy trộn baseline, tốc độ ego, probe và delay sự cố.
- **Đóng góp XGB:** Ledger train 708 cây: **0.923% tổng gain**, 867 split; 678 cây dùng khi predict: **0.922% tổng gain**; trên 4.990 vector raw cũ: **|SHAP| TB 0.936 s residual**.
- **Online hiện tại:** `wp=0.35×coverage`, `we=0.20×exp(−max(0,remaining)/2500)`, `de=clip(1/max(1e−6,ego_ratio),0.70,1.35)`; `base_p50×(1−wp−we+wp×probe_ratio+we×de)+min(180,0.25×inc_total_delay)`.
- **Nên tính:** Cùng công thức OFF/ON, nhưng chỉ gọi là có probe khi producer traversal thực tồn tại; incident phải có thời điểm nhận/freshness. Các hệ số là giả thiết cần đánh giá, không phải hằng số vật lý.
- **Vấn đề:** ON coverage=0 nên **wp luôn 0**: tên có probe nhưng không dùng probe thực. Trường này vẫn thay đổi do baseline/ego/incident, nên test “output thay đổi” không chứng minh probe hoạt động. Trần/sàn làm tín hiệu bão hòa; chưa có ablation chứng minh lợi ích từng thành phần.

## 10. Phép chiếu offline mới: còn phải thống nhất những gì?

Cùng gọi RouteHMM mới giải quyết được **lõi chọn vị trí**, chưa giải quyết cả pipeline. Các điểm còn lại có thể đổi feature và cả nhãn:

| Vấn đề | Hiện trạng từ code | Việc cần chốt trước khi dựng lại OFF |
|---|---|---|
| Nhịp/timestamp | OFF theo ping lịch sử; ON có nguồn báo thời điểm thiết bị và nguồn chỉ có thời điểm fetch | Lưu t_event, t_received, nguồn, dấu hiệu trùng; không suy heartbeat từ t_fetch |
| Vòng đời lượt | OFF chia trajectory/trip và trim terminal; ON bắt đầu giữa lượt, reset theo chiều/terminal/gap | Chung quy tắc reset và ý nghĩa first_seen; không hồi sinh lịch sử cũ khi đổi chiều |
| Quá khứ đã công bố | OFF projector xuất s ngay mỗi lần update; ON có sửa ring theo best_path của cửa sổ HMM | Quy định replay tại từng thời điểm được biết gì; feature có thể dùng lịch sử được cập nhật bằng dữ liệu đã nhận, không dùng ping tương lai |
| Tốc độ | OFF lùi 3/5 mẫu; ON cửa sổ 240/405 s, gộp/giới hạn ring | Một hàm feature trạng thái theo event time dùng chung hoặc parity replay cho từng vector, không chỉ so s_bus |
| Ép lý trình tăng | OFF builder lấy `np.maximum.accumulate(tr_s)` trước khi tính vị trí/rolling speed; instant lại lấy speed điểm Silver | Chốt có cho phép lùi nhỏ do GPS hay không; cùng vị trí phải tạo cùng speed, tránh một nhóm feature dùng s đã ép và nhóm khác dùng s gốc |
| Arrival / nhãn | OFF suy arrival từ trajectory để tạo target; HMM có thể reject/reset/làm thưa trajectory | Đo coverage, sai số crossing, gap và ca đổi chiều; không nội suy xuyên reset/gap dài để có đủ nhãn |
| Probe / delay tích lũy | OFF có event hoàn tất đoạn và trạm neo; ON chưa tạo | Producer nhân quả chung, kiểm chứng sau completion mới ảnh hưởng dự báo; không dùng arrival tương lai của ego làm input |
| Dữ liệu/model cũ | Silver/Gold/model cũ chưa chuyển đồng bộ sang chính sách mới | Version geometry/projection/baseline/feature; dựng mẫu nhỏ, so sánh từng vector và nhãn rồi mới chạy lại toàn bộ |

Không cần OFF và ON có cùng số ping. Cần cùng ý nghĩa feature, cùng quy tắc khi thiếu thông tin, và kiểm chứng trên cùng chuỗi raw cắt tại từng thời điểm. Nhãn offline được nhìn tương lai để biết xe đến thật lúc nào; **feature tại t không được nhìn tương lai**. Nếu arrival nội suy cần ping sau t, sự kiện đó chỉ được dùng làm probe sau khi ping bằng chứng đã được nhận, không chỉ vì thời điểm arrival nội suy≤t.

## 11. Ưu tiên sửa sau kiểm kê

**Điều chỉnh sau trao đổi ngày 18/11:** danh sách ban đầu bên dưới là các việc cần làm **nếu giữ đủ 54 feature**. Không còn mặc định ưu tiên cài hết producer để cứu schema cũ. Hướng đề xuất mới là thu gọn model theo dữ liệu app thực sự có; xem mục 13 trước khi triển khai. Chưa chốt danh sách feature mới, chưa được coi đây là quyết định tự động bỏ hoặc thay model đang dùng.

1. **Chốt hợp đồng trạng thái thời gian:** timestamp, lượt xe, cửa sổ speed, anchor và snapshot fleet; đo parity OFF/ON trên raw có cold start, mất ping, đổi chiều. Đây là điều kiện để dựng lại feature sau phép chiếu mới.
2. **Cài producer traversal và độ trễ tích lũy thật:** bốn probe feature, trip elapsed và cumulative delay. Test phải có sự kiện đã/ chưa hoàn tất và quan sát feature tương ứng, không chỉ assert đủ 54 key hay model trả số.
3. **Làm rõ nguồn incidents:** freshness, missing, refresh, received time và overlap. Có thể tạm thiếu feed, nhưng phải biểu diễn đúng và đánh giá model trong điều kiện thiếu đó.
4. **Đồng bộ baseline/catalog/mapping:** hash kèm model, cùng tính phần đoạn, xử lý bến/đích và fallback; xác minh không leakage trước khi tuyên bố kết quả huấn luyện.
5. **Sau đó mới dựng lại dữ liệu/train/đánh giá:** so sánh model cũ, model mới, baseline matrix và ablation nhóm feature trên cùng split nhân quả; báo sai số theo số trạm, khoảng cách, nguồn, cold start và độ phủ probe. Gain lớn hay SHAP lớn không thay cho kiểm chứng này.

Tài liệu này không kết luận cả 54 feature đều hữu ích, cũng không kết luận model vô dụng. Nó chỉ ra chính xác model có đầu vào nào, app đang cung cấp gì, số đo đóng góp thực sự nói được gì và phần nào hiện chưa có dữ liệu đúng nghĩa.

## 12. Bảng số đo huấn luyện chi tiết — 678 cây dùng khi predict

Ledger gốc 708 cây đã ghi tại từng feature và giữ nguyên đầy đủ trong JSON. Bảng này tính lại trên phần cây runtime thực sự dùng. Gain/cover giữ đơn vị nội bộ của XGBoost, dấu chấm là dấu thập phân; không phải giây.

| Feature | Gain TB | Tổng gain | Tỷ trọng tổng gain (%) | Split | Cover TB | Tổng cover |
|---|---:|---:|---:|---:|---:|---:|
| `route_id_idx` | 28280.69 | 146861616.00 | 3.789 | 5193 | 12468.26 | 64747692.00 |
| `direction_id` | 27285.81 | 19700354.00 | 0.508 | 722 | 2565.05 | 1851966.62 |
| `current_station_order` | 13827.15 | 17449858.00 | 0.450 | 1262 | 6438.27 | 8125103.00 |
| `target_station_order` | 22298.04 | 19979046.00 | 0.515 | 896 | 11498.70 | 10302836.00 |
| `day_type` | 66127.86 | 55018376.00 | 1.419 | 832 | 3675.98 | 3058414.00 |
| `day_of_week` | 65643.53 | 123147264.00 | 3.177 | 1876 | 8855.57 | 16613047.00 |
| `hour_slot` | 95239.52 | 300290208.00 | 7.747 | 3153 | 11692.01 | 36864900.00 |
| `sin_time` | 60080.57 | 216530368.00 | 5.586 | 3604 | 11082.17 | 39940144.00 |
| `cos_time` | 75426.80 | 278551200.00 | 7.186 | 3693 | 7639.63 | 28213142.00 |
| `s_bus_m` | 19809.81 | 36034040.00 | 0.930 | 1819 | 6043.47 | 10993076.00 |
| `s_target_m` | 15215.91 | 17954770.00 | 0.463 | 1180 | 3689.07 | 4353101.50 |
| `remaining_distance_m` | 17214.37 | 22430326.00 | 0.579 | 1303 | 10964.09 | 14286206.00 |
| `n_stations_ahead` | 37522.96 | 39511680.00 | 1.019 | 1053 | 28412.01 | 29917844.00 |
| `progress_ratio` | 14089.20 | 25078768.00 | 0.647 | 1780 | 6307.78 | 11227851.00 |
| `target_progress_ratio` | 9779.85 | 12312836.00 | 0.318 | 1259 | 6997.66 | 8810058.00 |
| `dist_to_next_station_m` | 31348.62 | 85174200.00 | 2.197 | 2717 | 14127.00 | 38383060.00 |
| `ego_speed_instant_kmh` | 14845.00 | 32376946.00 | 0.835 | 2181 | 13389.83 | 29203208.00 |
| `ego_speed_roll3_kmh` | 14592.20 | 15628246.00 | 0.403 | 1071 | 20543.29 | 22001868.00 |
| `ego_speed_roll5_kmh` | 34476.06 | 50472956.00 | 1.302 | 1464 | 10675.89 | 15629501.00 |
| `ego_accel_kmh_per_min` | 9459.24 | 4757999.50 | 0.123 | 503 | 34878.62 | 17543948.00 |
| `ego_speed_ratio_vs_baseline` | 13952.46 | 23049472.00 | 0.595 | 1652 | 18809.72 | 31073658.00 |
| `ego_trip_elapsed_sec` | 9777.61 | 11684249.00 | 0.301 | 1195 | 12472.68 | 14904858.00 |
| `ego_cum_delay_vs_baseline_sec` | 51990.58 | 126077152.00 | 3.252 | 2425 | 13789.18 | 33438762.00 |
| `lead_bus_dist_ahead_m` | 13734.63 | 16426623.00 | 0.424 | 1196 | 6953.30 | 8316146.00 |
| `lead_bus_time_headway_sec` | 8766.25 | 6180203.00 | 0.159 | 705 | 10364.80 | 7307186.00 |
| `lead_bus_speed_kmh` | 16637.69 | 14042211.00 | 0.362 | 844 | 6842.43 | 5775010.50 |
| `lead_bus_speed_ratio` | 102958.35 | 48390424.00 | 1.248 | 470 | 36326.39 | 17073404.00 |
| `follow_bus_dist_behind_m` | 8268.42 | 7019886.50 | 0.181 | 849 | 9351.41 | 7939345.50 |
| `follow_bus_speed_kmh` | 8019.13 | 5821885.50 | 0.150 | 726 | 7112.55 | 5163711.50 |
| `n_active_buses_on_route` | 9542.00 | 3139317.00 | 0.081 | 329 | 4891.61 | 1609340.25 |
| `n_buses_in_corridor_ahead` | 59680.26 | 17307276.00 | 0.446 | 290 | 30269.80 | 8778241.00 |
| `recent_corridor_tt_sum_sec` | 47313.28 | 62973972.00 | 1.625 | 1331 | 13885.34 | 18481394.00 |
| `recent_corridor_congestion_ratio` | 131951.08 | 276305568.00 | 7.128 | 2094 | 10096.35 | 21141760.00 |
| `recent_seg_coverage_ratio` | 37963.34 | 44644888.00 | 1.152 | 1176 | 1871.20 | 2200529.00 |
| `recent_next_seg_congestion_ratio` | 31602.59 | 23259506.00 | 0.600 | 736 | 19216.32 | 14143212.00 |
| `baseline_eta_p50_sec` | 32216.89 | 24774786.00 | 0.639 | 769 | 20889.49 | 16064016.00 |
| `baseline_eta_mean_sec` | 15831.87 | 6316915.50 | 0.163 | 399 | 23433.99 | 9350163.00 |
| `baseline_eta_p10_sec` | 11220.42 | 9380269.00 | 0.242 | 836 | 17290.76 | 14455076.00 |
| `baseline_eta_p90_sec` | 32421.73 | 22338572.00 | 0.576 | 689 | 12424.12 | 8560221.00 |
| `baseline_eta_iqr_sec` | 99726.91 | 351936256.00 | 9.079 | 3529 | 16027.46 | 56560904.00 |
| `baseline_eta_rss_std_sec` | 30127.48 | 140062640.00 | 3.613 | 4649 | 16900.81 | 78571872.00 |
| `baseline_skew_sec` | 131551.94 | 436884000.00 | 11.271 | 3321 | 29960.83 | 99499928.00 |
| `baseline_max_seg_p90_sec` | 25054.42 | 167012736.00 | 4.309 | 6666 | 7989.90 | 53260676.00 |
| `baseline_tier0_frac` | 59406.35 | 50792432.00 | 1.310 | 855 | 7497.58 | 6410431.00 |
| `inc_ahead_count` | 26186.67 | 11469760.00 | 0.296 | 438 | 45386.85 | 19879440.00 |
| `inc_ahead_total_delay_sec` | 112622.20 | 117014472.00 | 3.019 | 1039 | 39947.56 | 41505512.00 |
| `inc_ahead_max_delay_sec` | 77974.89 | 106357752.00 | 2.744 | 1364 | 32915.25 | 44896396.00 |
| `inc_ahead_max_magnitude` | 60143.20 | 11727923.00 | 0.303 | 195 | 13504.76 | 2633427.75 |
| `inc_ahead_jam_length_m` | 33259.12 | 28868916.00 | 0.745 | 868 | 25403.78 | 22050482.00 |
| `inc_dist_to_nearest_m` | 22882.32 | 10342810.00 | 0.267 | 452 | 14498.53 | 6553334.50 |
| `route_base_speed_kmh` | 35021.27 | 67100760.00 | 1.731 | 1916 | 1553.61 | 2976724.75 |
| `route_station_spacing_m` | 26319.96 | 49007772.00 | 1.264 | 1862 | 2457.80 | 4576417.00 |
| `physics_kinematic_eta_sec` | 26150.55 | 23640094.00 | 0.610 | 904 | 18691.93 | 16897504.00 |
| `physics_probe_corrected_eta_sec` | 43103.54 | 35732836.00 | 0.922 | 829 | 20033.42 | 16607709.00 |

## 13. Đánh giá sơ bộ: thu gọn bài toán ML trước khi bổ sung hạ tầng

Bàn giao phiên tiếp theo: [ML_SIMPLIFICATION_HANDOVER.md](ML_SIMPLIFICATION_HANDOVER.md).

### 13.1. Vấn đề chính là hợp đồng dữ liệu vượt khả năng app

Nhận định sơ bộ: **độ phức tạp đáng lo hiện nay nằm ở việc tạo đầu vào, chưa có bằng chứng XGBoost tự nó là thuật toán quá phức tạp cho bài toán**. Có 54 feature không tự chứng minh overfitting. Điều đã xác nhận là một số đầu vào offline có thông tin lịch sử mà app không quan sát được tương đương; app thay bằng prior hoặc hằng số, rồi vẫn đưa vào model được học với đầu vào giàu thông tin hơn.

Chuỗi “nội suy hoặc đặt mặc định → vector đủ trường → model trả ETA” chỉ chứng minh chương trình thực thi. Nó không chứng minh những trường đó mang thông tin đúng nghĩa. Một giá trị 0 của delay không đồng nghĩa xe đúng giờ; coverage=0 không đồng nghĩa giao thông bình thường. TreeSHAP giải thích model phản ứng với vector đã nhận, không xác nhận vector phản ánh thế giới đúng.

Cũng cần phân biệt nội suy phục vụ **nhãn** (ước lượng giờ đến từ các điểm GPS bao quanh) với nội suy tạo **feature**. Nhãn offline có thể dùng quan sát tương lai nếu công bố sai số và giới hạn gap. Feature tại thời điểm dự báo chỉ được dùng thông tin đã nhận tới thời điểm đó. Đổi phép chiếu không tự giải quyết khác biệt này.

### 13.2. Những nhóm có chi phí kiến trúc, không chỉ thiếu vài hàm

| Nhóm | Điều kiện để cung cấp đúng nghĩa | Khả năng với app hiện tại | Đề xuất sơ bộ |
|---|---|---|---|
| Bốn feature probe, gồm `recent_corridor_tt_sum_sec` | Quan sát đủ xe qua hai trạm, nhận diện cùng lượt, lưu traversal hoàn tất và tuổi dữ liệu; cần thu nhận đều trong thời gian đủ dài | Các đường cập nhật quan sát hiện nằm trong luồng phục vụ/sync request; lịch sử RAM hữu hạn, mở giữa lượt hoặc ngừng hỏi là có thể mất đoạn cần quan sát. Không có hợp đồng collector độc lập bảo đảm coverage này | Bỏ khỏi model gọn đầu tiên; không xây thêm collector chỉ để giữ schema 54 |
| Trip elapsed / cumulative delay | Biết mốc bắt đầu hoặc trạm neo đã thực sự quan sát, giữ state cùng lượt và tính baseline cùng quãng đường | Cold start giữa lượt không biết quá khứ. Baseline inversion là một prior khác nghĩa, không khôi phục được thời gian đã chạy | Bỏ hai trường theo nghĩa hiện tại; nếu cần tuổi lịch sử quan sát thì tạo trường mới tên rõ và train lại |
| Sáu feature incidents và nhánh incident trong physics | Feed đủ mới, quyền/API ổn định, thời điểm nhận, dedup episode, map geometry và chính sách refresh | Reader Parquet cục bộ có cache chưa tạo thành feed live; thiếu dữ liệu đang trộn với không sự cố | Bỏ khỏi model gọn đầu tiên; giữ raw TomTom đã có cho nghiên cứu riêng |
| Fleet trước/sau | Độ phủ snapshot, ID, chiều, tuổi ping và tốc độ từng xe đủ tin cậy | Có producer, nhưng coverage và cold start phụ thuộc nguồn; toàn cảnh offline khác snapshot online | Nhóm mở rộng để đánh giá thêm sau model lõi; không mặc định giữ vì code đã tồn tại |
| Feature physics kết hợp | Đầu vào thành phần có ý nghĩa và hệ số được kiểm chứng | Một số thành phần probe/incident không có; nhiều thông tin lặp với distance, speed, baseline | Bỏ `physics_probe_corrected_eta_sec` trong ứng viên gọn; kinematic là tùy chọn phải so sánh thực nghiệm |
| Baseline và geometry | Snapshot cùng version, fit đúng cutoff, lý trình và trạm nhất quán | Phù hợp vai trò pipeline lịch sử → bản phục vụ local, dù vẫn phải sửa hợp đồng và kiểm chứng | Giữ làm nền cho model và làm đối chứng độc lập |

Probe **không bất khả thi về nguyên lý**. Một phiên chạy đủ lâu, thu đều và gặp xe qua đủ trạm có thể đo được một số traversal. Nhưng biến nó thành nguồn đầu vào thường xuyên, ổn định cho mọi lần mở demo cần thay đổi vòng đời thu nhận/state và cách vận hành. Đó là mở rộng hệ thống, không phải chỉ điền một feature còn thiếu. Không cần buộc nhóm sinh viên chạy máy 24/7 để giải cứu một lựa chọn feature.

### 13.3. Hướng model gọn để thảo luận ở phiên tiếp

Giữ XGBoost residual là một lựa chọn khả thi ban đầu; **giảm yêu cầu dữ liệu trước**, chưa cần đổi thuật toán. Chưa chốt con số feature tối ưu. Một ứng viên khoảng 10–15 trường có thể xuất phát từ các nhóm:

- Tuyến/chiều và thời gian trong ngày/tuần, với mapping đóng băng.
- Khoảng cách còn lại, số trạm còn lại, khoảng cách tới trạm tiếp theo; chỉ giữ thêm vị trí tương đối nếu có lợi ích kiểm chứng được.
- Một hoặc hai tốc độ theo cửa sổ thời gian dùng chung OFF/ON; tuổi/cửa sổ lịch sử thực có và trạng thái thiếu cần được mô tả trung thực. Với nguồn chỉ biết thời điểm fetch, không gọi đó là tuổi GPS thật.
- Baseline P50 cùng tối đa một vài chỉ báo chất lượng/phân tán có ý nghĩa rõ. Không mặc định giữ mọi tổ hợp mean/P10/P90/IQR/skew/physics vì chúng đã có trong model cũ.

Đây là **đề xuất phạm vi**, chưa là danh sách cuối để lập tức train. Tiêu chí chọn: có thể tính tại request đầu hoặc có chính sách thiếu trung thực; tái tạo được từ raw theo cùng logic offline/online; không đòi quan sát quá khứ mà app không có. Một feature chỉ được thêm lại sau khi chứng minh cải thiện ở tập đánh giá phù hợp và xác định được chi phí vận hành của producer.

Không xóa cột khỏi vector rồi nạp model 54 feature cũ. Cần artifact/schema/model mới, giữ model cũ để đối chiếu. Giảm gain từ các nhóm bị bỏ không dự đoán được MAE sẽ tăng hay giảm bao nhiêu; phải train và đo lại.

### 13.4. Cách kiểm chứng hướng gọn mà không chạy lại toàn bộ ngay

1. Chốt schema nhỏ và định nghĩa từng trường, đặc biệt timestamp, tốc độ và trạng thái thiếu. Tách dữ liệu được biết lúc dự báo khỏi dữ liệu chỉ biết khi tạo nhãn.
2. Dùng raw hiện có làm replay nhân quả, gồm cold start, nhịp nguồn khác nhau, mất ping, đứng yên và đổi chiều. Feature offline tại mỗi mốc phải khớp feature serving trên cùng tiền tố dữ liệu. Chưa cần train để phát hiện lệch này.
3. Tạo pilot có nhãn/cutoff rõ; baseline và mọi thống kê chỉ fit phần train. Đánh giá baseline matrix, model cũ và ứng viên gọn trên cùng mẫu hợp lệ; báo riêng coverage, mẫu bị loại và điều kiện đầu vào. Không dùng riêng buổi tối hai tuyến để kết luận tổng quát.
4. Đo sai số theo horizon và thời gian đến thật, phân phối sai lệch %, độ biến động ETA trong cùng chuyến, cold start và từng nguồn. Chuỗi mượt hơn chưa chứng minh đến đúng giờ hơn.
5. Chỉ khi pilot đáng tin mới dựng lại dữ liệu lớn và train global. Fleet/probe/incidents là các thí nghiệm thêm nhóm sau đó, không là điều kiện để model lõi hoạt động.

**Chưa xác định:** số feature tối ưu, mức cải thiện so với baseline, nhóm fleet có nên giữ, và độ chính xác nhãn sau chiếu mới. Trong lần bổ sung này chỉ phân tích và bàn giao; chưa thay producer, chưa rebuild dữ liệu hay huấn luyện/thay model.
