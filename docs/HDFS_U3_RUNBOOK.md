# U3 — Từ batch HF đã nhận đến lịch sử Silver có thể truy vấn

## Kết quả và ý nghĩa

Luồng HF → Bronze → Silver đã chạy trên batch thật. Khi nhận thêm batch có thời gian cũ hơn, hệ thống xây snapshot lịch sử mới chứa hợp của các event, loại trùng xuyên batch, rồi công bố cho reader. Snapshot cũ vẫn đọc được; run chưa công bố không được API chọn. Đây là nền dữ liệu chung để U4 nối baseline và feature store, chưa phải thông báo đã cập nhật model/serving ETA.

Đầu vào kiểm chứng ở revision U1: hai batch bus `batch_161350.jsonl`, `batch_160515.jsonl` của ngày 12/11/2026 và một batch incidents `batch_161350.jsonl`. Batch 16:05 được nhận sau khi đã công bố lịch sử từ batch 16:13 để thử nhận muộn. Tham khảo [publication thật](evidence/hdfs_u3/published_snapshot.json) và [bằng chứng](evidence/hdfs_u3/README.md).

## Lệnh chạy

```powershell
# Xuất reference canonical đầy đủ; database chỉ mở read-only.
.\.venv\Scripts\python.exe scripts/export_hdfs_history_reference.py data/hanoi_bus_system.db runtime/history_reference_u3.json

# Dùng URI reference có hash mà lệnh trên trả về.
docker compose -f docker-compose.hdfs.yml exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.cores.max=2 --conf spark.executor.cores=1 --conf spark.executor.memory=512m --conf spark.executorEnv.PYTHONPATH=/workspace /workspace/scripts/hdfs_build_history_snapshot.py --reference hdfs://namenode:8020/bus-eta/v1/reference/history/sha256=7e1664bb57315eb23875421de7d3b7de7b9982e0fe6cfd6d04037729df24a2aa/reference.json
```

Builder chốt mọi manifest hoàn tất trong `_received/hf_batch/*/manifest.json`, xác minh byte raw và reference trước xử lý. Muốn chọn ngày/phạm vi ở bản này, kiểm soát tập batch đã nhận qua CLI U2; chưa có selector tập con riêng trong builder. Không nạp cả lịch sử HF nếu chưa chủ ý tăng phạm vi.

Snapshot ID cuối đã kiểm chứng:

```text
f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f
```

Chạy lại cùng batch/ref/code/policy trả `noop=true`, không append thêm Silver. Snapshot ID thay đổi khi một thành phần identity thay đổi. Không dùng `latest` ngầm để tránh ghép nguồn đang thay đổi. Dùng ID được trả về từ lượt chạy của mình nếu code hoặc dữ liệu đã đổi.

## Reader và API

```powershell
Invoke-RestMethod 'http://127.0.0.1:8090/api/history/route-speed?route_code=08A&date_from=2026-11-12&date_to=2026-11-12&snapshot_id=f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f'
```

Đã kiểm chứng trả 200, 140 ping, 127 speed samples, tốc độ trung bình 14,127165354330712 km/h. `avg_speed_kmh` chỉ tính trên speed không null; mẫu số count tốc độ được trả riêng. Query không có `snapshot_id` giữ đường P3A cũ để không đổi nguồn ngầm. U4 sẽ chọn snapshot này qua cùng publication contract.

`load_history_snapshot()` chỉ đọc publication manifest rồi đối chiếu với completed snapshot metadata, không đọc một `_runs` tùy ý do client truyền. ID sai định dạng trả 400; chưa có publication/lỗi HDFS trả 503 qua API. Mỗi request vẫn dùng giới hạn thời gian và tài nguyên của API P3A.

## Đối soát

```powershell
docker compose -f docker-compose.hdfs.yml exec -T spark-master /opt/spark/bin/spark-submit --master local[1] /workspace/scripts/verify_hdfs_history_snapshot.py --snapshot f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f --previous a2dc50ad61ac39d1ecfa92ad99ed37dee917eb7b85f996262c2c7dcce6226082
```

Đây là oracle riêng đọc HDFS bằng Spark local để không tranh thêm executor. Builder chính chạy Spark standalone với hai executor. Oracle chạy lại projection boundary chuẩn trên cùng đầu vào ở driver và so mọi cột Silver (trừ partition date), xác minh event cũ vẫn có trong lineage mới, đối chiếu query với Spark SQL. Đây là parity cùng định nghĩa nghiệp vụ; không phải chứng minh GPS đúng ngoài thực địa hoặc parity toàn database local.

## Failure và giới hạn

- `--fail-before-publish` cố ý dừng sau ghi snapshot, trước publication. Đã thử: API chưa thấy snapshot và trả 503; retry ghi attempt mới rồi công bố thành công. Run mồ côi được giữ để điều tra, chưa có garbage collector.
- Bản này recompute toàn bộ tập batch nhận, không phải incremental compute theo partition. Một route được gom trong RAM executor; chưa benchmark toàn bộ nhiều tháng.
- Reference lấy từ canonical SQLite, version bằng hash; history đầu vào lấy HDFS Bronze, không lấy snapshot lịch sử từ SQLite như P3A.
- Incidents có Silver observation riêng giữ JSON/geometry/null và event–batch lineage. Chưa spatial join thành `fact_route_tomtom_incidents`; đó là phần U4.
- Reject đầu vào có reason theo dòng; reject projection có ID/raw kèm reason chung, diagnostics chi tiết theo route từ boundary cũ. Chưa gán từng lý do geometry chi tiết cho từng event.
- Đã kiểm chứng 3 batch thực, không tuyên bố toàn bộ dataset HF đã được nhập. Noop kiểm tra read-back bus count; chưa có cơ chế checksum/repair toàn bộ file Parquet sau publication.
