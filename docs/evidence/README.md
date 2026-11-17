# Bằng chứng thực nghiệm

Mỗi thư mục ghi kết quả tại dữ liệu/revision/thời điểm của lượt chạy. Câu “chưa triển khai” hoặc “PASS” trong báo cáo cũ chỉ áp dụng lượt đó. Hiện trạng xem [HDFS](../HDFS_README.md), lệnh chạy xem [runbook](../HDFS_RUNBOOK.md).

| Nội dung | Bằng chứng |
| --- | --- |
| Silver toàn lịch sử, ETA, offline và restart — 17/11 | [Kết quả hiện hành](hdfs_full_silver/README.md) |
| Toàn bộ raw của revision cố định | [Full history](hdfs_full_history/README.md) |
| Bronze/retry/outage | [Bronze](hdfs_u2/README.md) |
| Silver/late data/publication | [Silver](hdfs_u3/README.md) |
| ETA Gold/offline release | [ETA](hdfs_u456/README.md) |
| Block/replica/executor, phép thử nhỏ | [Scale simulation](hdfs_p3b/verification.md) |

P1/P2/P3A và integration là kiểm chứng nền trước luồng HF hiện hành; fixture/SQLite snapshot/synthetic trong đó không là kết quả xử lý toàn lịch sử thật.
