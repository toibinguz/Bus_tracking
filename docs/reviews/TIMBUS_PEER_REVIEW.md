# Peer review nhánh timbus-experiments

Ngày kiểm tra: 2026-11-17. So sánh `origin/main...da087a2a` sau khi fetch;
tập trung thay đổi serving của `281a7214` và việc chuyển artifact ở `afd43d9d`.
Phần HDFS được lưu riêng trong `575c7c63`, không dùng làm bằng chứng đánh giá
tính năng TimBus. Chưa kiểm tra trạng thái CI hoặc cấu hình merge request trên GitHub.

**Cập nhật sau trao đổi và sửa lỗi:** hai lỗi cache/fleet đã được sửa và có test
hồi quy. Rút kết luận coi khác biệt vận tốc rolling là lỗi đã xác nhận: nhịp mẫu
train và serving khác nhau, nên đếm cùng số mẫu chưa đảm bảo cùng ý nghĩa.
Giữ nguyên `online_features.py`; không đổi model hoặc cách làm mượt vận tốc.
Các phép tái hiện dùng dữ liệu giả lập có kiểm soát, không gọi upstream và không
thay đổi SQLite hay trạng thái HDFS. Vị trí dòng ở các phát hiện dưới đây là của
commit được review ban đầu, trước bản sửa.

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

Đã sửa: hợp nhất telemetry trước, sau đó dùng chung `_filter_station_vehicles`
cho cache, truy vấn mới và fallback. Dấu đã vượt trạm chỉ hết hiệu lực theo TTL
hoặc điều kiện chuyến mới. Tọa độ ngoài hành lang không tạo dấu đã vượt trạm.

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

Đã sửa: `_sync_single_direction` cập nhật extractor bằng toàn bộ danh sách
hợp nhất, rồi mới lọc danh sách trả về. Test luân phiên bản đồ và nhiều trạm
xác nhận fleet vẫn đủ hai xe, trong khi danh sách tiếp cận thay đổi đúng theo trạm.

## 3. Rút kết luận lỗi — Khác nhịp mẫu train/serving cần đánh giá riêng

Vị trí: `module_3_bus_eta_prediction/step_3_4_eta_serving_and_evaluation/online_features.py:251–258`.

Train trong `step_3_2_feature_store_extractor/feature_store_builder.py:334–344`
lấy vận tốc tức thời từ `derived_speed_kmh`, rolling từ 3/5 mẫu trước. Serving
dùng cửa sổ thời gian 75/240/405 giây để xử lý telemetry có nhịp khác.
Ba mẫu TimBus cách nhau 5 giây chỉ bao phủ khoảng 15 giây; ba mẫu train có thể
bao phủ vài phút. Vì vậy đổi serving về đếm 3/5 mẫu không phải bản sửa hợp lệ
chỉ dựa trên hai công thức khác nhau.

Tái hiện cùng 7 mẫu, cách nhau 75 giây, vị trí
`[0, 100, 200, 300, 400, 500, 1500]` m:

| Feature | Công thức train (km/h) | Serving (km/h) |
|---|---:|---:|
| rolling 3 | 19,20 | 15,60 |
| rolling 5 | 13,44 | 12,00 |

Bảng trên chỉ chứng minh hai công thức khác nhau trên cùng chuỗi đầu vào giả
lập; nó không kiểm chứng việc chuyển giữa hai nguồn có nhịp lấy mẫu khác nhau.
Chưa có phép đánh giá đủ để kết luận các cửa sổ hiện tại tốt hay xấu, hoặc cần
huấn luyện lại. Muốn chọn cách tính cần đo nhịp mẫu train thực, replay telemetry
theo nhịp serving và so sánh sai số ETA trên tập đánh giá có nhãn. Chưa thực hiện
thí nghiệm này trong bản sửa cache/fleet. Thay đổi đếm mẫu thử trong lúc sửa đã
được gỡ hoàn toàn; `online_features.py` giữ nguyên so với commit review.

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
- `python docs/evidence/timbus_peer_review/reproduce.py`: kiểm tra cache/fleet và so sánh công thức vận tốc;
  kết quả JSON ban đầu trong `docs/evidence/timbus_peer_review/results.json`.
  Phần windows là phép so sánh công thức, không còn được coi là tái hiện lỗi.
- Test hồi quy mới: `tests/test_timbus_station_state_regressions.py`. Chạy tám
  trường hợp về cache/fleet với class production từ commit `082c0236` cho kết quả
  **3 failed, 5 passed**; ba trường hợp lỗi đúng là cache bỏ qua dấu vượt trạm,
  query → cache làm xe xuất hiện lại, và request trạm làm mất fleet.
- Sau sửa, chạy `python -m pytest tests/test_timbus_station_state_regressions.py tests/test_timbus_hybrid_serving.py tests/test_spec24_conservative_eta_blackbox.py -q -p no:cacheprovider`:
  **23 passed**, 20,55 giây. Kết quả chạy lại chương trình tái hiện trong
  `docs/evidence/timbus_peer_review/results_after_fix.json`: fresh/cache cùng trả
  0 xe đã qua trạm; fleet giữ đủ 2 xe trước/sau khi xem trạm; công thức vận tốc
  vẫn giữ nguyên, đúng phạm vi bản sửa.
- Chương trình tái hiện gọi trực tiếp các hàm production, dùng object tối thiểu
  và thay upstream bằng dữ liệu xác định. Phần train ở vấn đề 3 được tính bằng
  công thức của builder; không chạy lại toàn bộ pipeline huấn luyện.
- Chưa chạy thử trình duyệt hoặc đánh giá upstream TimBus thực. Xung đột phản
  hồi khi đổi tuyến/chiều đã có trong SPEC-41 mục 3.3, không đưa thành phát hiện mới.
- Chưa chạy toàn bộ test repository. Kết quả kiểm tra serving không xác nhận
  chất lượng mô hình trên dữ liệu train/serving khác nhịp.
