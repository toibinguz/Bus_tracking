# U3 — Silver tích lũy từ ledger HF Bronze

Trạng thái: đạt S1–S6 trên ba batch HF thực (hai bus, một incidents), có thử batch muộn, fail-before-publication, retry/noop, projection parity và query SQL/HTTP. Chưa nhập toàn bộ HF hoặc tối ưu incremental compute. Đầu vào là batch nhận hoàn tất ở SPEC-46 và reference canonical đầy đủ, không phải fixture P2. [Runbook](../HDFS_U3_RUNBOOK.md) và [evidence](../evidence/hdfs_u3/README.md).

## Quyết định phạm vi

- Mỗi lượt chốt danh sách manifest nhận hoàn tất. Bản đầu recompute toàn bộ batch đã chọn để bảo đảm đúng trajectory khi có batch trễ; chưa tối ưu chỉ tính partition bị ảnh hưởng. Đây là tích lũy logic, không tuyên bố incremental compute.
- Dedup event bus xuyên batch bằng identity SPEC-45; chọn observation có capture time sớm nhất, tie-break nội dung canonical; giữ quan hệ event–batch. Reference trạm ambiguous dùng raw hint đã chốt, không ghi đè mapping.
- Spark group theo route và gọi đúng projection boundary hiện hữu trên executor. Mỗi route được xử lý trong RAM executor: phù hợp phạm vi thử; chưa chứng minh xử lý vô hạn.
- Incidents có Silver observation riêng: giữ JSON nguồn, timestamp, geometry và delay null; loại exact duplicate. Việc spatial join thành fact_route_tomtom_incidents dành cho U4.
- Snapshot immutable gồm Silver bus, incidents, lineage, reject/diagnostics và reference. Chỉ có publication manifest mới cho phép reader nhìn snapshot. Không tự đổi nguồn API cũ hoặc bản serving hiện hữu.
- Key snapshot khóa tập batch/hash, full reference hash, source code và policy. Lỗi trước publication giữ run mồ côi nhưng không làm reader thấy dữ liệu dở; chạy lại dùng attempt mới, không xóa output cũ.

## AC

| ID | Điều kiện |
| --- | --- |
| S1 | Reference export read-only, đầy đủ shapes/stations/routes có hash; raw batch HDFS verify theo manifest |
| S2 | Snapshot chứa toàn bộ tập batch đã chọn; trùng batch/event không nhân đôi; có nguồn gốc event–batch |
| S3 | Direction, timestamp, route thiếu và projection guards theo nghiệp vụ; reject/diagnostics được lưu |
| S4 | Batch trễ được tính cùng lịch sử; cùng tập input/ref/code/policy có cùng key và logical rows bất kể thứ tự nhận |
| S5 | Chỉ đọc snapshot đã công bố; crash trước publish không lộ dữ liệu; retry và noop an toàn |
| S6 | Query route/date trên snapshot khớp Spark độc lập; chạy thực HF → Bronze → Silver, lưu evidence và giới hạn |
