# HDFS — bắt đầu từ đây

## Kiến trúc và lộ trình hiện hành

[SPEC-44: kiến trúc thống nhất và U1–U6](specs/44_UNIFIED_STORAGE_ARCHITECTURE_AND_EXECUTION_PLAN.md) là kế hoạch chung: GitHub Actions thu thập → Hugging Face giữ batch thô → HDFS tổ chức lịch sử → dữ liệu phục vụ ETA. SQLite/local Parquet vẫn hỗ trợ phục vụ và phát triển offline.

| Phần | Tài liệu | Trạng thái có bằng chứng |
| --- | --- | --- |
| U1 — Hợp đồng batch HF | [SPEC-45](specs/45_U1_HF_BATCH_AND_HISTORY_CONTRACT.md) | Khảo sát bus/incidents ở revision cố định |
| U2 — Nhận HF vào Bronze | [SPEC-46 và cách chạy](specs/46_U2_HF_TO_HDFS_BRONZE_IMPLEMENTATION.md) | Nhận batch thật; retry/outage/hash |
| U3 — Silver tích lũy | [SPEC-47](specs/47_U3_CUMULATIVE_SILVER_PLAN.md), [runbook](HDFS_U3_RUNBOOK.md) | Snapshot từ ba batch thật; late/dedup/publication/query |
| U4 — Baseline/feature dùng snapshot chung | SPEC-44 | Chưa hoàn tất; mới có thử nghiệm cache baseline cũ |
| U5 — Đồng bộ phục vụ/offline | SPEC-44 | Chưa hoàn tất |
| U6 — Diễn tập toàn luồng | SPEC-44 | Chưa hoàn tất |

Không suy ra U4–U6 đã hoàn thành từ việc các kiểm chứng U1–U3 đạt trên mẫu nhỏ.

## Runbook và bằng chứng được giữ

- [Cluster/P1 ban đầu](HDFS_DEMO_RUNBOOK.md), [phục hồi ingest](HDFS_P1_RECOVERY_ADDENDUM.md).
- [P3A query/validation](HDFS_P3A_RUNBOOK.md), [P3B mô phỏng block/executor](HDFS_P3B_RUNBOOK.md): kiểm chứng lịch sử, không phải lộ trình triển khai tiếp theo.
- Evidence [P1](evidence/hdfs_p1/), [P2](evidence/hdfs_p2/), [P3A](evidence/hdfs_p3a/README.md), [black-box P3A](evidence/HDFS_P3A_BLACKBOX_REPORT.md), [P3B](evidence/hdfs_p3b/verification.md).
- Thử nghiệm [baseline thật và cache offline](evidence/hdfs_integration/verification.md): lệnh/đối soát đã chạy, chưa thay thế consumer U4.
- Evidence [U1](evidence/hdfs_u1/hf_inspection.json), [U2](evidence/hdfs_u2/README.md), [U3](evidence/hdfs_u3/README.md).

SPEC-25 được giữ nguyên theo yêu cầu người dùng, cùng các contract kỹ thuật P1/P2 cần cho code/test. Các bản kế hoạch P3A/P3B, kế hoạch snapshot cũ và handover tạm dừng đã được dọn khỏi cây tài liệu; kết quả thử nghiệm vẫn được giữ ở runbook/evidence. Sơ đồ kiến trúc hiện hành nằm ở SPEC-44.
