# Chỉ mục đặc tả còn giữ

Codebase xác định hành vi. Spec là hợp đồng/thiết kế; nhãn APPROVED/READY/PASS cũ không là bằng chứng hiện trạng. Kết quả HDFS xem [chỉ mục](../HDFS_README.md).

| Chủ đề | Tài liệu | Cách dùng |
| --- | --- | --- |
| HDFS hiện hành | [Hợp đồng](HDFS_DATA_CONTRACTS.md) | Identity/mapping/publication/release/runtime/AC; [runbook](../HDFS_RUNBOOK.md) giữ lệnh |
| HDFS ban đầu | [SPEC-25](25_MINIMUM_VIABLE_HDFS_STORAGE_AND_QUERY_SPEC.md) | Giữ nguyên theo yêu cầu, chỉ tham khảo lịch sử |
| Projection | [SPEC-26](26_FRENET_PROJECTION_BOUNDARY_AND_PARITY_SPEC.md) | Interface/parity; trạng thái tra code/test/evidence |
| BusMap/browser | [SPEC-04](04_BUSMAP_ONLY_DISCRETE_TRACKING_SPEC.md) | Cập nhật browser rời rạc; không lấy lệnh cấm TimBus cũ để xóa thí nghiệm độc lập |
| Shape/trạm | [SPEC-05](05_ROUTE_SHAPE_AND_STATION_INTERACTIONS_SPEC.md) | Endpoint/tuyến/trạm; tên service và số liệu lịch sử cần đối chiếu code |
| ETA/serving | [SPEC-15](15_PHYSICAL_KINEMATICS_AND_SERVING_SPEC.md), [SPEC-16](16_REFACTOR_SPEC_STEP_3_4_SERVING_AND_3_5_WEB_DEMO.md), [SPEC-24](24_CONSERVATIVE_ETA_MODES_AND_ARRIVING_NOW_REMOVAL_SPEC.md) | Giữ nghiệp vụ/interface/quyết định Passenger-Debug; SPEC-24 ưu tiên khi xung đột, không xác nhận tiến độ |
| Đánh giá ML | [SPEC-32 hợp nhất](32_ML_EVALUATION_ERROR_DISTRIBUTION_PLOTS_SPEC.md) | Metric/biểu đồ; số liệu lấy từ manifest thực, không lấy ví dụ trong spec |

Các file 38–40 là công việc riêng của người dùng, không sửa/xóa/commit trong đợt này.

Đã bỏ audit cũ 06/07/12–14, kế hoạch quản trị/triển khai tạm 17–23/31, thiết kế đã thay thế 08/09/10/11, spec runtime 27–29/33–37 và kế hoạch 44–49. HDFS hợp nhất vào hợp đồng/runbook; phần metric không xung đột của hai SPEC-32 được gộp. Xóa spec không có nghĩa đã sửa các lỗi từng nêu. Tra bản cũ bằng `git log -- docs/specs/<tên-file>`, không giữ archive trùng trong cây hiện hành.
