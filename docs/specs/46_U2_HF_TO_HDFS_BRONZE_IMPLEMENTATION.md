# U2 — Nhận batch Hugging Face vào HDFS Bronze

Hợp đồng nguồn: [SPEC-45](45_U1_HF_BATCH_AND_HISTORY_CONTRACT.md). Kế hoạch chung: [SPEC-44](44_UNIFIED_STORAGE_ARCHITECTURE_AND_EXECUTION_PLAN.md). U2 không làm Silver, projection hay huấn luyện.

**Trạng thái: đạt U2-1–U2-6 trên hai batch thực của U1.** Kiểm chứng cụm thật: nạp sau gián đoạn, NameNode stop/start, retry trước receipt, chạy lặp và hash đọc trực tiếp HDFS. Kiểm chứng unit: cùng path thay bytes, thêm revision, corruption, mất acknowledgement và lỗi nguồn. Báo cáo/log: [evidence U2](../evidence/hdfs_u2/README.md). Chưa thử nhận toàn bộ dataset hoặc đo throughput.

## Thiết kế thực hiện

Một CLI `scripts/hf_hdfs_ingest.py`, hai bước độc lập:

1. `stage`: chốt revision qua HF API, tải các path được chọn hoặc bus/incidents của một ngày, đóng file local và source descriptor bằng fsync/rename. Không gọi Docker. Batch và mỗi revision quan sát có metadata riêng.
2. `upload`: chỉ đọc staging; kiểm tra lại hash/descriptor; gửi nguyên byte vào HDFS riêng tư bằng CLI trong container NameNode. Không truy cập HF, không cần đưa credential HF vào container. Tạo raw object và manifest bất biến, đọc lại xác minh rồi mới ghi receipt local. Chạy lại vẫn kiểm tra HDFS thay vì tin receipt local tuyệt đối.

Chọn HDFS CLI qua Docker Compose cho bước này để không mở thêm cổng hoặc thêm service/dependency vào cluster. Đây là transport thực vào HDFS, không phải ghi thư mục local rồi gọi là HDFS. Uploader WebHDFS/receipt P1 được giữ nguyên vì hợp đồng envelope/spool khác batch gốc U2.

Byte object theo content hash dưới `bronze/hf_raw`; ledger dưới `/bus-eta/v1/_received/hf_batch/<batch_id>/manifest.json`; từng revision có sighting riêng trong `revisions/<revision>.json`. `received_at_utc` thuộc lần nhận đầu; receipt revision tiếp theo không ghi đè manifest đầu. Cùng path/hash ở revision mới chỉ thêm sighting, không tạo batch logical mới. Cùng path khác hash tạo version mới.

Một object được ghi vào tên tạm UUID trước khi rename sang tên đích. Tiến trình chết có thể để lại file tạm riêng; retry không dùng hoặc công bố file tạm đó. Chưa có GC file tạm; không tự xóa rộng để phục hồi. Manifest là mốc nhận batch, không phải publication Silver. Silver chỉ được xây ở U3 sau validate/ref mapping.

## AC

| ID | Điều kiện |
| --- | --- |
| U2-1 | Hai batch bus/incidents HF thật được pin revision và tải nguyên byte; hash khớp bằng chứng U1 |
| U2-2 | Object HDFS và manifest có thể đọc/xác minh; đầy đủ dataset/revision/path/hash/batch_id; không ép incidents vào bus envelope |
| U2-3 | Chạy lặp không tăng logical batch; thêm revision giữ identity; cùng path khác bytes không ghi đè bản trước |
| U2-4 | Gián đoạn sau raw hoặc trước receipt có thể chạy lại; receipt thành công chỉ sau kiểm tra remote |
| U2-5 | Lỗi HDFS không được coi là not-found; staging còn nguyên, lệnh thất bại rõ; khởi động NameNode lại nhận tiếp được |
| U2-6 | Có kiểm thử corruption, revision, versioning và path; log cụm thật và lệnh tái lập; không sửa crawler/serving/model |

## Chạy

```powershell
# Khi chưa bật Docker vẫn tải được. Cùng stage-dir có thể bổ sung các batch/revision sau.
.\.venv\Scripts\python.exe scripts/hf_hdfs_ingest.py stage --stage-dir runtime/hf_bronze_stage --revision f2e7378002113cb548e194f2e8bd11c97a1b94d9 --path raw_data/2026-11-12/bus/batch_161350.jsonl --path raw_data/2026-11-12/incidents/batch_161350.jsonl

# Khi có cụm HDFS, nạp các source descriptor đã đóng.
.\.venv\Scripts\python.exe scripts/hf_hdfs_ingest.py upload --stage-dir runtime/hf_bronze_stage

# Nạp tăng dần theo ngày ở revision được chốt khi bắt đầu lệnh (chưa upload).
.\.venv\Scripts\python.exe scripts/hf_hdfs_ingest.py stage --stage-dir runtime/hf_bronze_stage --date 2026-11-12 --category all
```

Không tự chạy dòng tải cả ngày trong kiểm chứng bounded. `--path` và `--date` loại trừ nhau; `--category` lọc khi chọn ngày. Kết quả staging có path/hash/revision để biết chính xác lượt đã chọn.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_hf_bronze.py tests/test_hf_storage_inspection.py -q -p no:cacheprovider
# Kiểm chứng này chủ động stop/start NameNode, cần cụm không có job khác đang chạy.
.\.venv\Scripts\python.exe scripts/verify_hf_bronze_integration.py --stage-dir runtime/hf_bronze_stage --recovery-stage runtime/hf_bronze_recovery_01 --evidence runtime/hf_bronze_u2_checks
```

## Giới hạn

Nhận batch theo ledger không đồng nghĩa đã loại trùng event giữa batch. U3 phải đọc manifest nhận hoàn tất và xây Silver tích lũy. Chưa có daemon theo dõi HF; chủ động gọi stage/upload theo phiên là đủ phạm vi U2. Transport subprocess có timeout 40 giây mỗi lệnh; đọc/ghi theo file trong RAM, phù hợp batch hiện tại, không phải importer cho một file hàng chục GB. Timeout không là SLA tổng cả lượt nhận nhiều batch.
