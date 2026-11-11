# BÁO CÁO TIẾN ĐỘ DỰ ÁN

## 1. Bài toán và pipeline dự kiến

Dự án xây dựng pipeline thực nghiệm cho dữ liệu telemetry xe buýt nhằm biến ping vị trí thô thành dữ liệu có thể truy vết, phân tích và dự báo thời gian đến trạm (ETA). Bài toán trọng tâm là liên kết quan sát vị trí theo thời gian với hình học tuyến, trạng thái xe và các trạm; từ đó tạo dữ liệu lịch sử có chất lượng đủ để huấn luyện và đánh giá mô hình ETA. Phạm vi là đồ án học phần trên dữ liệu API công khai và thiết bị sinh viên, không cam kết dịch vụ 24/7 hay bao phủ toàn bộ mạng xe buýt.

Pipeline đích là: **crawler/API → chuẩn hóa và khử trùng lặp → đối chiếu route/Frenet → SQLite vận hành + Parquet lakehouse → đặc trưng và Model ETA toàn cục → kết quả ETA/đánh giá**. Nhánh lưu trữ lịch sử phân tán đang được tích hợp theo luồng: **durable spool → WebHDFS Bronze → Spark Silver/Gold → truy vấn lịch sử → đối soát ETA**. Nhánh này bổ sung cho SQLite/lakehouse cục bộ, không thay thế trạng thái live. Mọi trạng thái bên dưới chỉ được gọi là hoàn thành khi có artifact, phép đo hoặc audit tái lập.

## 2. Trạng thái module và hạng mục theo nhóm

| Nhóm / module | Phạm vi | Tình trạng | Thành quả khi đã hoàn thành |
| --- | --- | --- | --- |
| Module 1 — thu thập & chuẩn hóa | Ping, master tuyến/shape/trạm, sanitizer | Hoàn thành | 7.333.298 unique pings; master route/shape/station được lưu trong SQLite. |
| Module 1 — chiếu tuyến | Route projection, `s_bus_m`, `cross_track_m`, direction | Hoàn thành | 5.565.232 telemetry đã chiếu; 48 tuyến, 481 xe; không có hàng vượt ngưỡng `cross_track_m` 35 m. |
| Module 2 — operational store | SQLite canonical/operational | Hoàn thành | SQLite chứa telemetry, master và fact phục vụ pipeline. |
| Module 2 — local lakehouse | Parquet Silver/Gold và audit | Hoàn thành | Audit Silver pass: 1.191 tệp, 5.565.232 hàng. |
| Module 2 — HDFS/Spark | Spool, WebHDFS Bronze, Spark Silver/Gold, query lịch sử | Đang triển khai | — |
| Module 3 — ETA | Feature pipeline, huấn luyện và đánh giá Model-6 global | Hoàn thành | 3.704.820 hàng held-out; E1 MAE 96,70 giây, RMSE 170,89 giây. |
| Module 3 — diễn giải kết quả | Ledger prediction-level, phân rã theo số đoạn trạm | Hoàn thành | E2 audit pass; MAE từ 23,74 giây (1 đoạn) đến 201,90 giây (>15 đoạn). |
| Phục vụ/giao diện demo | API phục vụ, web demo live | Tạm dừng | — |
| Tích hợp & báo cáo | Evidence ledger, tái lập, báo cáo kỹ thuật | Hoàn thành | Báo cáo và artifact E1/E2 truy vết được nguồn số liệu. |

