# Full HF raw-history import — 2026-11-12

**PASS: toàn bộ `raw_data/` ở revision đã chốt đã được nhận vào HDFS Bronze và đọc lại để xác minh.** Không suy ra đã xử lý Silver/Gold toàn lịch sử.

| Chỉ số | Kết quả thực |
| --- | --- |
| Dataset | `Toibinguz/hust-bus-data` |
| Revision | `d0a59a0689f375ba72cad1729dd4cb19fd1f7c74` |
| Batch bus / incidents / traffic legacy | 3.649 / 2.285 / 142 |
| Tổng file và byte | 6.076; 5.433.831.020 byte |
| Object raw duy nhất | 6.076; cùng tổng byte với inventory |
| Nạp theo lô | Exit 0; 2.034,9 giây trong vòng chạy, chưa tính lập inventory/build image |
| Đối chiếu remote | Exit 0; đọc lại mọi object, so SHA-256 và Git/LFS digest HF, so manifest/revision; 83,6 giây trong phần verify sau chuẩn bị index |
| HDFS fsck | HEALTHY; 6.076 block; replication trung bình 2,0; 0 missing/corrupt/under-replicated |

Raw nằm dưới `/bus-eta/v1/bronze/hf_raw/category=<bus|incidents|traffic>/sha256=<hash>/batch.jsonl`. Ledger nằm dưới `/bus-eta/v1/_received/hf_batch/<batch_id>/`, gồm manifest và từng revision sighting. Hai replica của raw bytes tương đương 10.867.662.040 byte, chưa tính checksum/metadata và dữ liệu khác trong cluster. Hai DataNode cùng laptop, không phải hai máy độc lập.

Bằng chứng nguyên bản: [import summary](import_summary.json), [remote verification](verification.json), [fsck](fsck.txt). Inventory đầy đủ, downloaded cache, staging, receipts và log từng nhóm giữ ở `runtime/hf_full_history/`, đã được ignore để tránh commit nhầm dữ liệu lớn. Không tự xóa dữ liệu local hoặc data cũ.

## Các lệnh thực tế

```powershell
.\.venv\Scripts\python.exe scripts/hdfs_import_history.py plan --plan runtime/hf_full_history/plan_pinned.json --revision d0a59a0689f375ba72cad1729dd4cb19fd1f7c74
docker compose -f docker-compose.hdfs.yml --profile import build history-import
.\.venv\Scripts\python.exe scripts/hdfs_import_history.py run --plan runtime/hf_full_history/plan_pinned.json --workers 4 --chunk-size 128
docker compose -f docker-compose.hdfs.yml --profile import run --rm --no-deps history-import python3 /workspace/scripts/verify_hdfs_history_import.py --plan /import/plan_pinned.json --workers 8
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs fsck /bus-eta/v1/bronze/hf_raw
```

Plan đã có thì không tạo lại cùng tên; dùng nguyên plan để resume. Nếu mất plan local, tái lập từ đúng revision vào file mới dưới cùng thư mục. Lượt này pin một revision, không đuổi theo các batch crawler tiếp tục xuất hiện sau thời điểm chốt; không đọc toàn bộ lịch sử Git của repository.

## Kiểm thử và giới hạn

Trong lúc tải lớn, một truy vấn legacy API vượt deadline 20 giây và trả 503; log ghi rõ `history query deadline exceeded`. Không có lỗi data block. Sau tải, bộ HTTP live 11/11 đạt; lượt hồi quy đầy đủ cuối **70 passed in 16.63s**. Không tăng deadline hoặc sửa dữ liệu để làm test qua.

Traffic cũ chỉ được archive nguyên byte, không diễn giải thành bus hoặc incident. Builder Silver yêu cầu `--batch-id` hoặc `--all-received`; workflow source-window truyền batch IDs cụ thể. Việc recompute mọi route trên toàn 5,43 GB chưa được chứng minh phù hợp RAM laptop nên không chạy trong lượt này. Không retrain hoặc đổi model/database/release phục vụ.

Sau full import, Spark smoke `app-20261112150720-0020` chạy exit 0 với đúng ba batch IDs được chọn (một bus, một incidents, một traffic). Snapshot `2dfb71d8ce99a696ca02385235c8c31bbd91a554ed96256373ba4dc1d8ab5b09` trả 3.324 bus rows, 192 incident observations và `bronze_only_traffic_batches=1`, chứng minh guard không kéo toàn raw vào xử lý và không ép traffic thành incidents. Chỉ tạo snapshot thử nghiệm nhỏ, không kích hoạt nó làm release phục vụ.
