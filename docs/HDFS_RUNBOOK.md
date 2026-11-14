# Chạy trên cụm HDFS hiện có

Chạy tại root repository; Docker Desktop Linux containers, Python `.venv` có dependencies. [Trạng thái và giới hạn](HDFS_README.md).

## 1. Bật/tắt cụm

```powershell
.\scripts\hdfs_demo.ps1 up
.\scripts\hdfs_demo.ps1 health
```

Report cần **2 live DataNode**. NameNode UI `http://127.0.0.1:9870`; Spark UI `http://127.0.0.1:8080`. Tắt bằng `docker compose -f docker-compose.hdfs.yml down`, giữ named volumes.

Hướng dẫn dùng namespace/reference đã có trên cụm đã kiểm chứng, chưa là bootstrap cụm trắng. Script provision P2 cũ không tạo đầy đủ namespace history hiện hành.

## 2. Resume nhập raw history và kiểm tra

```powershell
docker compose -f docker-compose.hdfs.yml --profile import build history-import
.\.venv\Scripts\python.exe scripts/hdfs_import_history.py run --plan runtime/hf_full_history/plan_pinned.json --workers 4 --chunk-size 128
docker compose -f docker-compose.hdfs.yml --profile import run --rm --no-deps history-import python3 /workspace/scripts/verify_hdfs_history_import.py --plan /import/plan_pinned.json --workers 8
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs fsck /bus-eta/v1/bronze/hf_raw
```

Plan chốt revision. Resume dùng receipt local; verifier mới đọc lại toàn bộ remote bytes/lineage. Cache/staging/checkpoint dưới `runtime/hf_full_history/` được ignore.

Muốn revision khác: dùng `scripts/hdfs_import_history.py plan --plan <tên_mới_trong_cùng_thư_mục> --revision <commit_HF>`. Không ghi đè plan cũ. Nhập thêm raw không tự cập nhật Silver/Gold.

## 3. Chạy tập mẫu đến release

```powershell
docker compose -f docker-compose.hdfs.yml --profile eta build eta-artifacts
.\.venv\Scripts\python.exe scripts/run_hdfs_eta_workflow.py --source-window docs/evidence/hdfs_u456/source_window.json --workspace runtime/eta_window_next --dates 2026-10-27 2026-11-01 --routes 02 27 --pointer runtime/eta_demo_active.json
```

Source window pin revision/bốn batch và reference URI. Reference phải có trong HDFS. Nếu reference đổi, export bằng `scripts/export_hdfs_history_reference.py <canonical.db> <output.json>` và dùng URI trả về trong bản source window riêng.

Luồng chạy: HF → Bronze → Spark Silver → cache → baseline/incidents/features local → HDFS Gold → download/verify → activate **pointer demo**. Dùng workspace mới khi input/reference/code đổi hoặc output cũ còn dở. Không lấy snapshot ID của lượt cũ; dùng `ETA_SOURCE_SNAPSHOT` từ output.

Workflow chỉ truyền batch IDs trong source window. Builder riêng bắt buộc `--batch-id ...` hoặc `--all-received`; chưa dùng lựa chọn toàn kho khi chưa kiểm chứng RAM.

## 4. Offline

```powershell
.\.venv\Scripts\python.exe scripts/eta_snapshot_pipeline.py inspect --pointer runtime/eta_demo_active.json
.\.venv\Scripts\python.exe scripts/eta_snapshot_pipeline.py baseline --source release --pointer runtime/eta_demo_active.json --route 02 --direction go --from-order 7 --to-order 8 --day-type 0 --hour-slot 13
```

Hai lệnh không cần Docker. `inspect` verify release và trả snapshot/artifact ID. Có thể tra SQLite hiện hữu bằng `--source local --database data/hanoi_bus_system.db` thay nguồn release; không có chuyển nguồn ngầm.

Các bước riêng xem `scripts/eta_snapshot_pipeline.py --help`. `build` từ cache đã tải chạy local; publish/download cần HDFS. Lỗi refresh không đổi pointer tốt trước.

## 5. Query lịch sử

```powershell
docker compose -f docker-compose.hdfs.yml --profile history up -d history-api
```

Gọi `GET http://127.0.0.1:8090/api/history/route-speed` với `route_code`, `date_from`, `date_to`, **snapshot_id của lượt chạy cần đọc**. Bỏ snapshot ID sẽ đọc fixture legacy, không tự chọn snapshot mới nhất. API chỉ đọc publication; mất HDFS/deadline trả lỗi, không chuyển sang SQLite.
