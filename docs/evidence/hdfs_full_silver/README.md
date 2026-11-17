# Hoàn thiện xử lý lịch sử HDFS — 17/11/2026

**Đã đạt bốn điều kiện nghiệm thu của đợt này.** Cụm chính đã restart, dữ liệu còn đọc được; DB/model/pointer ứng dụng giữ nguyên.

| Điều kiện | Kết quả và bằng chứng |
| --- | --- |
| Bootstrap và phục hồi | Cụm thử mới có hai DataNode, đúng quyền namespace; khôi phục 1.990.612 byte dù còn receipt cũ, retry idempotent; release tra baseline được khi cụm chính dừng. Chỉ volume thử được xóa. [Kết quả](bootstrap_restore.json) |
| Giữ đúng nghiệp vụ | Tách phiên chỉ khi gap vượt ngưỡng stale; qua nửa đêm vẫn liên tục. Sau fail-before-publication, snapshot dở không được công bố; retry khớp mọi giá trị Silver/lineage của bản cũ trên cùng ba batch. [Recovery](publication_recovery.json), [parity](retry_parity.json) |
| Xử lý toàn lịch sử | Đúng tập 6.076 batch/5.433.831.020 byte của inventory đã pin; 7.568.398 dòng bus, 381.180 incident observations, 54 tuyến và 1.463 partition. Accounting/unique events/lineage/index đạt; fsck HEALTHY, không thiếu/hỏng/under-replicated block. [Summary](summary.json), [verifier](full_verification.json), [fsck](fsck.txt), [noop](full_noop.json) |
| ETA và offline | Hai tuyến/hai ngày từ Silver đầy đủ: 40.669 ping, 798 chuyến, 7.599 ô baseline, 3.542 incident facts, 56.196 train + 57.373 test feature rows. Offline repeat giống từng giá trị SQLite/Parquet; corruption bị từ chối, refresh lỗi giữ pointer. [Workflow](domain_workflow.json), [manifest](artifact_manifest.json), [parity/model smoke](consumer_verification.json), [offline](offline_verification.json) |

Lượt Silver thành công mất 1.636,261 giây, 4 core trên hai executor host; RSS Python worker cao nhất 319.808 KiB, không gồm JVM. Tại một thời điểm quan sát, ba RDD lưu 6.940.820.651 byte trên đĩa, cache RDD trong RAM bằng 0. [Storage observation](storage_observation.json).

Lượt đầu bị giới hạn 20.000 event khi gom cả lịch sử xe; chưa có publication. Đã sửa thành phiên theo ngưỡng stale và chạy lại toàn bộ. [Lỗi được giữ lại](first_attempt_failure.json). Truy vấn HTTP lạnh ban đầu vượt 20 giây; sau đọc metadata trực tiếp, schema tường minh và khởi tạo SQL trước HTTP, lần đầu trên API tạo mới trả 200 trong 13,374 giây, đúng 10.345 ping. Deadline giữ 20 giây. [Trước sửa](http_initial_cold.json), [sau sửa/restart](http_after_restart.json).

Hồi quy cuối: [67 kiểm thử liên quan và 11 kiểm thử HTTP thật đạt](validation.json). [Mã nguồn khớp lượt chạy](source_hashes.json), [các file được giữ nguyên](protected_files.json). Log/inventory/manifest đầy đủ và workspace ở `runtime/hdfs_completion_20261117`, `runtime/eta_full_history_20261117`; dữ liệu và log lớn không đưa vào Git.

Đây là cluster Docker chung laptop, không là benchmark nhiều máy. Gold/features chỉ chạy hai tuyến/hai ngày, chưa retrain/promote model hay chuyển web sang release mới. Model chỉ được thử load/predict 16 dòng; không có kết luận accuracy mới. Baseline/incident/feature algorithms chạy local từ cache Silver.
