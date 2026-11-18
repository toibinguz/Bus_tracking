# Chạy trên cụm HDFS hiện có

Chạy tại root repository; Docker Desktop Linux containers, Python `.venv` có dependencies. [Trạng thái và giới hạn](HDFS_README.md).

## 1. Bật/tắt cụm

```powershell
.\scripts\hdfs_demo.ps1 up
.\scripts\hdfs_demo.ps1 health
```

Report cần **2 live DataNode**. Kiểm tra cụm bằng health/CLI; API trên host ở cổng 8090 (phần 5). Trên Docker Desktop đã kiểm chứng, cổng UI của core trong mạng private không forward ra host. Tắt bằng `.\scripts\hdfs_demo.ps1 down`: dừng cả profile API và giữ named volumes.

`up` đợi health của cụm, safemode kết thúc rồi chạy `hdfs_provision_namespace.sh`: Bronze/reference/receipt thuộc root, Silver/history publication thuộc spark, mode 755. Script chỉ chỉnh các root được liệt kê, không xóa dữ liệu. Reference canonical vẫn cần được export trước lượt xử lý đầu tiên.

## 2. Resume nhập raw history và kiểm tra

```powershell
docker compose -f docker-compose.hdfs.yml --profile import build history-import
.\.venv\Scripts\python.exe scripts/hdfs_import_history.py run --plan runtime/hf_full_history/plan_pinned.json --workers 4 --chunk-size 128
docker compose -f docker-compose.hdfs.yml --profile import run --rm --no-deps history-import python3 /workspace/scripts/verify_hdfs_history_import.py --plan /import/plan_pinned.json --workers 8
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs fsck /bus-eta/v1/bronze/hf_raw
```

Plan chốt revision. Resume dùng receipt local; verifier mới đọc lại toàn bộ remote bytes/lineage. Nếu đã thay/mất volume HDFS, thêm `--recheck` vào lệnh `run` để không bỏ qua batch chỉ vì còn receipt local. Cache/staging/checkpoint dưới `runtime/hf_full_history/` được ignore.

Muốn revision khác: dùng `scripts/hdfs_import_history.py plan --plan <tên_mới_trong_cùng_thư_mục> --revision <commit_HF>`. Không ghi đè plan cũ. Nhập thêm raw không tự cập nhật Silver/Gold.

## 3. Silver và release

Xuất reference từ canonical SQLite (read-only), rồi chạy Silver. Đây là cấu hình đã chạy toàn kho trên laptop; lưu log và lấy `snapshot_id` từ dòng `U3_RESULT`.

```powershell
$reference = .\.venv\Scripts\python.exe scripts/export_hdfs_history_reference.py data/hanoi_bus_system.db runtime/history_reference_current.json
docker compose -f docker-compose.hdfs.yml exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.cores.max=4 --conf spark.executor.cores=2 --conf spark.executor.memory=768m --conf spark.python.worker.memory=256m --conf spark.executorEnv.PYTHONPATH=/workspace /workspace/scripts/hdfs_build_history_snapshot.py --reference $reference --all-received --partitions 32 --max-session-events 50000
```

Muốn xử lý tập nhỏ, thay `--all-received` bằng `--batch-id ID1 ID2 ...`. Builder giữ trajectory qua nửa đêm; chỉ tách khi gap vượt ngưỡng stale. Lỗi hoặc vượt giới hạn không được công bố. Cùng input/reference/code trả `noop`.

Từ snapshot đã công bố, chọn ngày/tuyến để tạo dữ liệu ETA. Thay `<snapshot_id>` bằng ID builder trả về; dùng workspace mới khi đổi input/code hoặc còn output dở.

```powershell
docker compose -f docker-compose.hdfs.yml --profile eta build eta-artifacts
$snapshotId = 'ID_builder_tra_ve'
.\.venv\Scripts\python.exe scripts/run_hdfs_eta_workflow.py --snapshot $snapshotId --workspace runtime/eta_window_next --dates 2026-10-27 2026-11-01 --routes 02 27 --pointer runtime/eta_demo_active.json
```

Lệnh tải đúng partition từ Silver → baseline/incidents/features local → HDFS Gold → download/verify → activate **pointer demo**. Không thay DB/model ứng dụng. Đường `--source-window` vẫn có trong CLI nếu muốn nạp một cửa sổ HF rồi xử lý, thay vì dùng snapshot đã có.

## 4. Offline

```powershell
.\.venv\Scripts\python.exe scripts/eta_snapshot_pipeline.py inspect --pointer runtime/eta_demo_active.json
.\.venv\Scripts\python.exe scripts/eta_snapshot_pipeline.py baseline --source release --pointer runtime/eta_demo_active.json --route 02 --direction go --from-order 7 --to-order 8 --day-type 0 --hour-slot 13
```

Hai lệnh không cần Docker. `inspect` verify release và trả snapshot/artifact ID. Có thể tra SQLite hiện hữu bằng `--source local --database data/hanoi_bus_system.db` thay nguồn release; không có chuyển nguồn ngầm.

Chạy web từ release đã tải (không query HDFS trong request):

```powershell
.\run_demo.ps1 -ReleasePointer runtime/eta_demo_active.json -NoBrowser
```

Web kiểm tra manifest/hash và so geometry/station/route ID với catalog local trước
khi dùng baseline. Incidents cũng đọc từ release; không lấy Parquet mặc định để
bù ngầm. Các release hiện chưa pin mapping/model/calibrator đã nghiệm thu nên chế
độ này chỉ dùng baseline ETA; `/api/health` công bố artifact/snapshot, các tuyến
có baseline và lý do chưa bật ML. Các tuyến ngoài danh sách ấy không có baseline
quan sát từ release. Chuyển pointer chỉ có hiệu lực ở lần khởi động web tiếp theo.
Release hỏng hoặc geometry khác thì khởi động thất bại, không đổi sang DB khác.

Test nhanh bằng nguồn local hiện hữu, bỏ lựa chọn release từ biến môi trường:

```powershell
.\run_demo.ps1 -LocalData -NoBrowser
```

Model ở chế độ local vẫn là ứng viên chưa nghiệm thu; không coi health `healthy`
là upstream đang tốt hay model đã chính xác. Cả hai chế độ chỉ đọc dữ liệu khi
khởi động/phục vụ, không hỏi xuất dữ liệu lúc dừng.

Các bước riêng xem `scripts/eta_snapshot_pipeline.py --help`. `build` từ cache đã tải chạy local; publish/download cần HDFS. Lỗi refresh không đổi pointer tốt trước.

## 5. Query lịch sử

```powershell
docker compose -f docker-compose.hdfs.yml --profile history up -d --force-recreate --no-deps history-api
```

Đợi API khởi tạo Spark rồi gọi `GET http://127.0.0.1:8090/api/history/route-speed` với `route_code`, `date_from`, `date_to`, **snapshot_id cần đọc**. Bỏ snapshot ID sẽ đọc fixture legacy, không tự chọn snapshot mới nhất. API chỉ đọc publication và partition được chọn; mất HDFS/deadline trả lỗi, không chuyển sang SQLite.
