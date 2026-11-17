# Peer review nhánh timbus-experiments

Ngày kiểm tra: 2026-11-17. So sánh `origin/main...da087a2a` sau khi fetch;
tập trung thay đổi serving của `281a7214` và việc chuyển artifact ở `afd43d9d`.
Phần HDFS được lưu riêng trong `575c7c63`, không dùng làm bằng chứng đánh giá
tính năng TimBus. Chưa kiểm tra trạng thái CI hoặc cấu hình merge request trên GitHub.

**Kết luận: cần sửa các lỗi dưới đây trước khi chấp nhận nhánh.** Không sửa mã
tính năng trong lượt review này. Các phép tái hiện dùng dữ liệu giả lập có kiểm soát,
không gọi upstream và không thay đổi SQLite hay trạng thái HDFS.

## 1. P2 — Cache bỏ qua dấu xe đã vượt trạm

Vị trí: `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py:408–410`.

Nhánh truy vấn TimBus mới kiểm tra `_is_recently_passed_locked`, còn nhánh cache
lại xóa dấu đã vượt trạm khi tọa độ cache nằm trước trạm. Khi GPS lùi nhẹ sau lúc
vượt trạm, bản ghi mới bị loại đúng ở lần đầu nhưng đã được ghi vào cache; lần
gọi tiếp trong TTL 4 giây trả xe trở lại danh sách chờ. Request bản đồ cũng có thể
ghi tọa độ lùi vào cache trước khi request ETA sử dụng nó.

Tái hiện: trạm ở 100 m, xe có dấu đã vượt trạm từ 2 giây trước, bản ghi TimBus
hiện tại ở 90 m (chưa đạt ngưỡng đặt lại chuyến 150 m). Cùng bản ghi đó:
truy vấn mới trả **0 xe**, dùng cache trả **1 xe**, dấu đã vượt trạm bị xóa.

Đề nghị: áp dụng cùng quy tắc vượt trạm cho cache và truy vấn mới; chỉ xóa dấu
khi hết TTL hoặc đủ điều kiện chuyến mới. Thêm kiểm tra chuỗi query → cache.

## 2. P2 — Trạm được xem làm thay đổi ngữ cảnh đội xe của ML

Vị trí: `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/serving_service.py:327–328`.

`_sync_single_direction` đưa danh sách đã lọc theo trạm vào `update_observation`.
Hàm này thay toàn bộ `_fleet[(route_id, dir_int)]`. Vì vậy xe đang chạy nhưng đã
qua trạm người dùng xem bị loại khỏi ngữ cảnh ML, dù vẫn có trên tuyến. Những
feature như `n_active_buses_on_route`, xe dẫn trước và khoảng cách dẫn trước bị
thiếu. Request bản đồ và request ETA của các trạm khác nhau ghi đè cùng trạng thái;
dự báo phụ thuộc vào thứ tự các request.

Tái hiện bằng hai xe ở 90 m và 110 m: đồng bộ bản đồ ghi nhận **2 xe**; chỉ gọi
ETA cho trạm ở 100 m làm `_fleet` còn **1 xe**. Danh sách tiếp cận trạm có 1 xe là
đúng, nhưng số xe hoạt động trên tuyến vẫn phải là 2.

Đề nghị: cập nhật lịch sử và fleet từ toàn bộ telemetry hợp nhất; lọc xe theo trạm
sau đó, trên dữ liệu dùng riêng cho phản hồi.

## 3. P2 — Feature vận tốc chưa đồng nhất giữa train và serving

Vị trí: `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/online_features.py:251–258`.

Train trong `step_3_2_feature_store_extractor/feature_store_builder.py:334–344`
lấy vận tốc tức thời từ `derived_speed_kmh`, rolling từ 3/5 mẫu trước. Serving
đổi sang cửa sổ thời gian 75/240/405 giây. Đây là thay đổi định nghĩa đầu vào cho
cùng mô hình, không phải chỉ đổi tần suất cập nhật. Lấy cửa sổ thời gian điển hình
không đảm bảo tương đương số mẫu khi nhịp dữ liệu thay đổi.

Tái hiện cùng 7 mẫu, cách nhau 75 giây, vị trí
`[0, 100, 200, 300, 400, 500, 1500]` m:

| Feature | Công thức train (km/h) | Serving (km/h) |
|---|---:|---:|
| rolling 3 | 19,20 | 15,60 |
| rolling 5 | 13,44 | 12,00 |

Đề nghị: thống nhất hợp đồng feature giữa offline và online. Nếu chủ ý dùng cửa
sổ thời gian để nhận TimBus 5 giây, cần cập nhật phần tạo feature train và đánh
giá/huấn luyện lại trước khi khẳng định đồng nhất. Kiểm tra hiện tại chưa đo ảnh
hưởng của sai khác này lên MAE, nên không kết luận độ chính xác giảm bao nhiêu.

## 4. P2 — Chuyển artifact nhưng chưa cập nhật bên đọc

Các file đã chuyển từ `reports/evaluation/ml_error_distribution/` sang
`data/evaluation/ml_error_distribution/`, trong khi
`tests/test_spec32_ml_error_distribution_blackbox.py:28` vẫn trỏ đường dẫn cũ.
Chạy bộ này cho kết quả **9 passed, 1 failed, 12 errors**; lỗi trực tiếp là không
tìm thấy các bảng/manifest. Đây là lỗi đã được ghi tại mục 5.3 của SPEC-41, nay
được xác nhận bằng thực thi; không tính là phát hiện mới.

Đề nghị: cập nhật các bên đọc cùng đường dẫn đã chọn, rồi chạy lại bộ kiểm tra;
không sao chép artifact trở lại hai nơi chỉ để làm test qua.

## Bằng chứng và giới hạn

- `python -m pytest tests/test_timbus_hybrid_serving.py tests/test_spec24_conservative_eta_blackbox.py -q -p no:cacheprovider`: **12 passed**, 56,35 giây.
- `python -m pytest tests/test_spec32_ml_error_distribution_blackbox.py -q -p no:cacheprovider`: **9 passed, 1 failed, 12 errors**, 1,23 giây.
- `python docs/evidence/timbus_peer_review/reproduce.py`: tái hiện ba vấn đề đầu;
  kết quả JSON trong `docs/evidence/timbus_peer_review/results.json`.
- Chương trình tái hiện gọi trực tiếp các hàm production, dùng object tối thiểu
  và thay upstream bằng dữ liệu xác định. Phần train ở vấn đề 3 được tính bằng
  công thức của builder; không chạy lại toàn bộ pipeline huấn luyện.
- Chưa chạy thử trình duyệt hoặc đánh giá upstream TimBus thực. Xung đột phản
  hồi khi đổi tuyến/chiều đã có trong SPEC-41 mục 3.3, không đưa thành phát hiện mới.
- Chưa chạy toàn bộ test repository. Kết quả 12 test đạt chỉ xác nhận hai bộ nêu
  trên; không đủ phủ định các tình huống đã tái hiện.
