# Chạy lại kiểm chứng P3A

API: `docker compose -f docker-compose.hdfs.yml --profile history up -d history-api`.
Truy vấn: `http://127.0.0.1:8090/api/history/route-speed?route_code=08A&date_from=2026-10-08&date_to=2026-10-08`.
API giữ một Spark session, dùng tối đa hai core và 512 MiB mỗi executor. Một truy vấn chạy tại một thời điểm, deadline 20 giây; khi hết hạn API hủy job group và trả 503. Nếu tác vụ nền chưa thoát, truy vấn tiếp theo nhận 503 busy.

## Dữ liệu quan sát

Chọn hai ngày có dữ liệu thực. Lần nghiệm thu dùng tuyến 08A, train 2026-10-27 và test 2026-11-01. Ngày 2026-10-30 chỉ có một ping, nên lần thử đầu trả inconclusive; không dùng lần đó để tuyên bố độ chính xác.

Điều kiện đầu vào: cluster HDFS có hai DataNode khỏe, Spark có hai worker, checkpoint P2 ở đường dẫn trong lệnh dưới đã tồn tại. Với cluster mới, tạo root Gold và cấp quyền cho user Spark trước khi ghi; các lệnh chỉ tác động namespace của dự án:

```powershell
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs dfs -mkdir -p /bus-eta/v1/gold
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs dfs -chown spark:supergroup /bus-eta/v1/gold
```

```powershell
.\.venv\Scripts\python.exe scripts/hdfs_p3_stage_observed_snapshot.py data/hanoi_bus_system.db runtime/p3a_observed_v2 08A 2026-10-27 2026-11-01
docker compose -f docker-compose.hdfs.yml cp runtime/p3a_observed_v2 namenode:/tmp/p3a_observed_v2
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs dfs -put /tmp/p3a_observed_v2 /bus-eta/v1/reference/p3a_observed_v2
docker compose -f docker-compose.hdfs.yml exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.cores.max=2 /workspace/scripts/hdfs_p3_validate.py hdfs://namenode:8020/bus-eta/v1/reference/p3a_observed_v2/observed_projected.jsonl hdfs://namenode:8020/bus-eta/v1/reference/p3a_observed_v2/stations.json hdfs://namenode:8020/bus-eta/v1/reference/p3a_observed_v2/manifest.json hdfs://namenode:8020/bus-eta/v1/gold/p3a_observed_v3 hdfs://namenode:8020/bus-eta/v1/_checkpoints/bronze_to_silver/60ed5c1457557a6adea9f959437348efd9232cd49e806e87f72aadf8a42d42e2.json
```

Lần chạy mới dùng tên thư mục HDFS output chưa tồn tại; chương trình cố ý không ghi đè. Snapshot là bản nhập dữ liệu đã chiếu từ SQLite, không phải bằng chứng toàn bộ lịch sử đã đi qua ingest P1. Manifest ghi database, điều kiện chọn, SHA-256 và source_window_id. Spark kiểm tra hash, nhập snapshot thành Silver Parquet trên HDFS rồi đọc lại; Gold cũng được ghi và đọc lại trước khi tính sai số.

Gold dùng median của các đoạn trạm trong ngày train. Quy tắc phân chuyến, bỏ trạm đầu/cuối và nội suy lấy từ hàm hiện hữu. Đây không phải toàn bộ baseline theo loại ngày/giờ của Module 3. MAE đoạn tính trên các đoạn test có lịch sử; coverage phải đọc cùng mẫu số. MAE chuyến là sai lệch tổng thời gian các đoạn liền trạm hợp lệ trong một chuyến; có thể có khoảng trống không nội suy được, nên không diễn giải là thời gian toàn tuyến từ bến đầu đến bến cuối.

Checkpoint tùy chọn liên kết bộ bốn ping đã publish với báo cáo: bộ này chỉ dùng kiểm tra API và số chuyến hợp lệ, không dùng đánh giá độ chính xác. Dữ liệu hai ngày nhập riêng không được tự động publish vào API P2.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_hdfs_history_query.py tests/test_hdfs_p3_observations.py -q -p no:cacheprovider
```
