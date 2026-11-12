# Nhập toàn bộ lịch sử HF vào HDFS Bronze

Trạng thái: đạt AC1–AC4. Đã nhận đủ 6.076 batch/5.433.831.020 byte, đọc lại toàn bộ remote bytes và lineage khớp nguồn; fsck HEALTHY, hai replica, không thiếu/hỏng block. [Bằng chứng](../evidence/hdfs_full_history/README.md). Người dùng yêu cầu nhập toàn bộ lịch sử, không yêu cầu retrain hoặc đổi serving.

## Phạm vi đã chốt

Revision HF `d0a59a0689f375ba72cad1729dd4cb19fd1f7c74`, dataset `Toibinguz/hust-bus-data`: 6.076 file JSONL dưới `raw_data/`, tổng 5.433.831.020 byte. Bus 3.649, incidents 2.285, traffic legacy 142. Đây là số file/byte, không phải số event. Khoảng 10,9 GB cho hai replica của raw bytes, chưa tính metadata/cache.

Metadata hiện thời ngoài raw_data (README/quota/catalog) không được tính là lịch sử quan sát. Chốt revision một lần, không kéo theo batch mới xuất hiện giữa lượt nhập.

## Cách thực hiện

- Plan đầy đủ với size/Git blob ID (hoặc LFS hash khi có); pin cùng revision cho mọi download.
- Host tải bốn file đồng thời vào cache/staging. Mỗi nhóm 128 file được receiver trong private Docker network nhận qua WebHDFS, kiểm tra byte và lineage rồi ghi receipt. Không chạy một Docker process cho từng file.
- Giữ nguyên byte thô cả traffic cũ, không ép vào schema bus hoặc incidents. Các file có thể truy ngược dataset/revision/path/hash.
- Lỗi giữ staging, dừng có thông báo. Chạy lại cùng plan tiếp tục qua receipt; sau nhập phải đọc lại toàn bộ object và metadata trên HDFS để không chỉ tin checkpoint local.
- Không xóa dữ liệu gốc/local cache tự động. Không chạy full Silver trên phép group-by-route giữ trong RAM chưa được kiểm chứng ở dung lượng này.

## AC

1. Đủ tập path ở plan; download size/hash nguồn hợp lệ; mỗi path có batch receipt đúng revision/hash.
2. Đọc lại tất cả byte object và nhận lineage từ HDFS, đối chiếu hash; tổng byte logical bằng inventory.
3. HDFS fsck không missing/corrupt/under-replicated block; replica hai DataNode được giữ.
4. Dữ liệu/model/release phục vụ hiện hữu không bị ghi đè. Không gọi Bronze đầy đủ là đã xử lý Silver/Gold đầy đủ.

## Resume và verify

```powershell
.\.venv\Scripts\python.exe scripts/hdfs_import_history.py run --plan runtime/hf_full_history/plan_pinned.json --workers 4 --chunk-size 128
docker compose -f docker-compose.hdfs.yml --profile import run --rm --no-deps history-import python3 /workspace/scripts/verify_hdfs_history_import.py --plan /import/plan_pinned.json --workers 8
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs fsck /bus-eta/v1/bronze/hf_raw
```

Progress/receipts/logs nằm trong `runtime/hf_full_history`, không đưa 5,43 GB raw vào Git. Để tránh vô tình xử lý toàn bộ kho mới, builder Silver nay yêu cầu `--batch-id ...` hoặc `--all-received` rõ ràng. Source-window workflow truyền batch IDs đã chọn; các snapshot đã công bố trước vẫn đọc được.
