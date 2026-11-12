# SPEC-32: phân rã và trình bày sai số ETA

Đây là hợp đồng phép đo, không phải báo cáo kết quả. Không hardcode N, số tuyến, accuracy hoặc model “chuẩn” từ tài liệu; lấy từ manifest và code của lượt đánh giá.

## Nguồn và phạm vi

- CLI: `scripts/plot_ml_error_distributions.py`; xử lý: `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py`.
- Kiểm tra: `tests/test_spec32_ml_error_distribution_blackbox.py`. Việc file tồn tại không tự xác nhận test đã đạt.
- Code hiện chọn các mốc đúng `n_stations_ahead ∈ {1, 2, 5, 10}`. Đường model mặc định hiện là `eta_xgb_global_pruned_r3_big.json`; không suy rằng model này trùng model full 54 features của lượt smoke HDFS.
- Test rows lấy feature-store split test; nhãn `actual_eta_sec`, baseline `baseline_eta_p50_sec`, số chặng `n_stations_ahead`. Split và feature order phải khớp model/config đã chọn.
- Một chặng là khoảng giữa hai canonical station orders, không phải GPS ping hoặc kilomet. Mỗi bảng phải in N và phạm vi ngày/tuyến.

## Công thức và ý nghĩa

Đặt `y = actual_eta_sec`, `p = prediction_sec`, `e = y - p`, `a = abs(e)`:

| Chỉ số | Công thức | Ý nghĩa |
| --- | --- | --- |
| Signed error (s) | `e = y - p` | Dương: xe đến muộn hơn dự báo; âm: đến sớm hơn dự báo |
| Signed error (%) | `100*e/y` | Lệch tương đối từng hàng, rất nhạy khi y nhỏ |
| MAE / MdAE (s) | mean / median của a | Lệch tuyệt đối trung bình / điển hình |
| RMSE (s) | `sqrt(mean(e²))` | Nhạy với sai số lớn |
| P75/P90/P95 AE (s) | quantile của a | Đuôi sai số tuyệt đối |
| WAPE (%) | `100*sum(a)/sum(y)` | Sai lệch toàn nhóm có trọng số ETA thực |
| Bias (s) | `mean(e)` | Hướng lệch theo cùng quy ước dấu |
| Trong ngưỡng (%) | `100*mean(a <= t)` | t = 30/60/120/180 giây |
| Sớm / muộn (%) | `100*mean(e<0)` / `100*mean(e>0)` | e=0 không tính hai lần |

Ví dụ minh họa, không phải số đo: dự báo 120 giây, thực tế 180 giây → +60 giây, +33,3%; thực tế 90 giây → -30 giây, -33,3%.

Bản đề xuất phân rã cũ dùng `prediction - actual`, dấu ngược. Phải chuẩn hóa trước khi ghép bảng; không dùng tên “bias” mà bỏ công thức dấu. Nhãn null/không hợp lệ phải đếm và loại theo điều kiện rõ ràng, không đổi thành 0. Không gọi MAPE có sàn mẫu số là MAPE thuần.

## Bảng và hình

Cho mỗi horizon hiện có, xuất hai phân phối: giây và phần trăm, kèm N, mean/median, các quantile và tỷ lệ sớm/muộn. Ghi riêng MAE/MdAE/WAPE để không nhầm signed mean gần 0 với sai số nhỏ.

Bảng thống kê tính trên toàn bộ mẫu hợp lệ, không cắt tail theo khung đồ thị. Nếu giới hạn trục để dễ đọc, ghi tỷ lệ mẫu nằm ngoài khung; không che đuôi sai số. Xuất dữ liệu CSV đi cùng hình để đối chiếu. Giây có thể đổi sang phút bằng chia 60, không làm tròn trước tính thống kê.

## Mở rộng chưa tự coi là đã triển khai

- Bổ sung mốc đúng 15 chặng và bucket rời nhau 1, 2, 3–5, 6–10, 11–15, >15, ALL. Phân biệt mốc đơn với bucket; tổng N bucket phải bằng ALL. Bốn mốc hiện tại không đại diện toàn test.
- Báo sai số theo tuyến/ngày/chiều và tỷ lệ trong ngưỡng, ghi N của nhóm ít mẫu, không xếp hạng nhóm quá nhỏ.
- So sánh baseline và ML trên cùng hàng test/split. Không so model khác split như cùng thí nghiệm.
- Nếu báo CI, bootstrap theo vehicle-trip/route-day; thiếu khóa ghi N/A. Không bootstrap từng ping phụ thuộc rồi gọi là CI đáng tin cậy.

## Điều kiện chấp nhận kết quả

1. Manifest lưu model hash, input file inventory/hash, code/version, thời gian chạy, split, filters, feature order và số hàng nhận/loại/đánh giá.
2. Accounting N đúng, tất cả metric/histogram đối chiếu được dữ liệu đầu vào hoặc prediction ledger. Không suy accuracy từ model smoke.
3. Tách rõ kết quả đã chạy và đề xuất mở rộng, giữ số đo thật kể cả coverage thấp/đuôi lớn.
4. Inference theo batch không có nghĩa RAM bị chặn: code hiện giữ mảng sai số theo horizon để tính quantile/vẽ. Phạm vi lớn cần đo RAM hoặc thiết kế lưu prediction ledger/aggregation trước khi chạy.
