# Module 2 — Lưu trữ lịch sử và dữ liệu phục vụ

HDFS giữ raw bất biến, receipts, snapshot Silver và artifact có lineage.
Spark thực hiện chuẩn hóa/dedup/projection Silver. Baseline/incidents/features
hiện build local từ phạm vi Silver đã chọn, rồi publish/tải verified release.
SQLite/Parquet trong release phục vụ demo offline; web không query HDFS.

- `step_2_4_hdfs_history`: luồng phân tán và release hiện hành.
- `step_2_1_sqlite_operational_store`: operational DB/local catalog hiện hữu.
- `step_2_2_parquet_medallion_lakehouse`: export/audit đường Parquet local.
- `step_2_3_columnar_query_engine`: placeholder, không phải query engine đã triển khai.

[Kiến trúc và bằng chứng](../docs/HDFS_README.md) ·
[Runbook](../docs/HDFS_RUNBOOK.md) ·
[Hợp đồng](../docs/specs/HDFS_DATA_CONTRACTS.md) ·
[Việc còn lại](../docs/specs/41_REMAINING_COMPLETION_AND_TESTING_ISSUES_SPEC.md).

Chạy kiểm tra cấu trúc theo stage, không yêu cầu Gold phải vắng mặt:

```powershell
.\.venv\Scripts\python.exe scripts/verify_canonical_architecture.py --stage silver
.\.venv\Scripts\python.exe scripts/verify_canonical_architecture.py --stage gold
```

Hai lệnh chỉ kiểm tra cấu trúc/readiness, không chứng minh “100% tinh khiết”,
không leakage hay model tốt. Dùng hợp đồng, test biên và đối soát theo SPEC-41
để kiểm chứng hành vi; lấy số đếm từ output/manifest của lần chạy thực tế.
