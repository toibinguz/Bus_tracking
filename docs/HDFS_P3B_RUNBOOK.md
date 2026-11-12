# P3B: mô phỏng phân tán trên laptop

P3B đã đạt các tiêu chí mô phỏng: generator tái lập, replay giữ identity, namespace riêng, ít nhất ba block trên hai DataNode, xử lý trên hai executor và bằng chứng chạy thật. Lượt chạy `scale_20261112_01` ngày 12/11/2026 dùng Spark 3.5.4 và HDFS thật trên Docker. Kết quả này chứng minh cơ chế chia block, nhân bản và xử lý phân tán ở quy mô nhỏ. Kế hoạch triển khai hiện hành là [SPEC-44](specs/44_UNIFIED_STORAGE_ARCHITECTURE_AND_EXECUTION_PLAN.md).

## Kết quả thực đo

| Chỉ số | Giá trị |
| --- | --- |
| Nguồn Bronze đã ghi | 5 dòng, 4 event duy nhất |
| Seed / multiplier | 42 / 2.000 |
| Synthetic | 8.000 dòng; 4.815.560 byte |
| Block size riêng cho thí nghiệm | 1 MiB |
| HDFS | 5 block; mỗi block có 2 replica trên 2 DataNode |
| Kiểm tra fsck | HEALTHY; 0 missing/corrupt/under-replicated block |
| Executor xử lý dữ liệu | 2 host; lần lượt 4.001 và 3.999 dòng |
| Tổng latitude đối soát | 167882,4500000007; kỳ vọng 167882,45 |
| Replay | 3 batch; 15 dòng; vẫn chỉ 4 event duy nhất |
| Bắt đầu từng batch so với thời điểm bắt đầu tác vụ | 12,1405 / 12,5065 / 12,9536 giây |
| Thời gian đo trong script | 18,5829 giây; không bao gồm khởi tạo Spark session |

Hash SHA-256 dự kiến khớp hash đọc lại byte từ HDFS: `632bc8bbbae6d19696ddafeef73efb76ffd6f2addff24b337f2fd0c4e981dbee`. Nguồn, hash nguồn, các vị trí block và từng executor được ghi trong [báo cáo JSON](evidence/hdfs_p3b/scale_report.json); [fsck](evidence/hdfs_p3b/fsck.txt) và [hash đọc lại](evidence/hdfs_p3b/stored_sha256.txt) là bằng chứng riêng.

## Chạy lại

Yêu cầu cụm P3A đang hoạt động: 2 DataNode, 2 Spark worker; mỗi executor dùng 1 core và 512 MiB RAM. Nguồn dưới đây là fixture đã đưa lên HDFS ở P3A. Nếu dùng cụm mới, phải chạy lại bước ingest fixture P3A trước.

```powershell
docker compose -f docker-compose.hdfs.yml up -d namenode datanode-1 datanode-2 spark-master spark-worker-1 spark-worker-2
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs dfs -mkdir -p /bus-eta/v1/experiments/p3b
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs dfs -chown spark:supergroup /bus-eta/v1/experiments/p3b
docker compose -f docker-compose.hdfs.yml exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.cores.max=2 --conf spark.executor.cores=1 --conf spark.executor.memory=512m /workspace/scripts/hdfs_p3b_scale.py --source hdfs://namenode:8020/bus-eta/v1/bronze/telemetry/dt=2026-10-08/hr=13/p3a.jsonl --run scale_20261112_01
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs fsck /bus-eta/v1/experiments/p3b/scale_20261112_01/provenance=synthetic_scale/bronze -files -blocks -locations
```

Lệnh Spark trên là lệnh đã chạy thành công, application `app-20261112085232-0011`, exit 0. Đổi `--run` khi chạy lượt mới: output đã tồn tại sẽ bị từ chối trước khi ghi; namespace cũng tham gia event identity. Cùng nguồn/run/seed/multiplier cho cùng byte hash; namespace khác chủ ý tạo identity/hash khác. Không xóa hoặc ghi đè lượt cũ để chạy lại.

Generator loại bản trùng trong nguồn trước khi nhân synthetic. Trong mỗi tile, thời gian và GPS giữ nguyên; vehicle ID, plate, provenance, source window và event ID được thay để nhận diện mô phỏng. Seed là thành phần namespace identity, không phải bộ sinh ngẫu nhiên. Replay giữ nguyên event ID, thời gian sự kiện và payload, chỉ gắn nhãn replay; mỗi batch đợi tối thiểu 0,1 giây sau lần ghi trước. Thời gian ghi Spark khiến khoảng cách thực tế lớn hơn 0,1 giây.

Mọi dữ liệu nằm dưới `/bus-eta/v1/experiments/p3b/<run>`, không tạo manifest `_published/bronze_to_silver`, do đó API lịch sử không chọn thí nghiệm. Bộ đánh giá P3A chỉ nhận provenance observed; không đưa synthetic vào thống kê độ chính xác.

## Giới hạn

Đây là phép thử khoảng 4,6 MiB với block 1 MiB, không phải minh chứng đã xử lý hàng trăm GB hoặc 400 event/s. Generator tạo dữ liệu trong RAM driver rồi mới ghi HDFS, phù hợp phép thử nhỏ; chưa phải bộ sinh dữ liệu streaming lớn. Một file được ghi bằng một task; sau đó Spark chia đọc và xử lý trên hai executor. Replay kiểm tra bảo toàn identity và phân biệt số dòng với số event, không đo giới hạn backpressure hay bổ sung kiểm chứng khôi phục mới; các kiểm chứng mất kết nối nằm ở P1/P3A. Mọi container vẫn chung một laptop, chưa chứng minh độc lập phần cứng hoặc hiệu năng nhiều máy.
