# Vận hành HDFS và luồng dữ liệu ETA

[Kiến trúc/trạng thái](HDFS_README.md) · [Hợp đồng](specs/HDFS_DATA_CONTRACTS.md). Chạy từ root repository với Python `.venv`. ID bên dưới thuộc cụm đã kiểm chứng, không tự tồn tại ở máy mới.

## Cluster

Docker Desktop ở Linux containers:

```powershell
.\scripts\hdfs_demo.ps1 up
.\scripts\hdfs_demo.ps1 health
docker compose -f docker-compose.hdfs.yml cp scripts/hdfs_p2_provision_namespace.sh namenode:/tmp/hdfs_p2_provision_namespace.sh
docker compose -f docker-compose.hdfs.yml exec -T namenode sh /tmp/hdfs_p2_provision_namespace.sh
```

`health` in report; kiểm tra có **2 live DataNode**, không chỉ exit code. Provision cấp quyền các root P2, không xóa/reset; namespace history mới do exporter/builder quản lý. NameNode UI `http://127.0.0.1:9870`, Spark UI `http://127.0.0.1:8080`. DataNode/WebHDFS private.

Kết thúc bằng `docker compose -f docker-compose.hdfs.yml down` giữ named volumes; không thêm `-v` nếu muốn giữ lịch sử.

## Nhập toàn bộ raw history và resume

```powershell
.\.venv\Scripts\python.exe scripts/hdfs_import_history.py plan --plan runtime/hf_full_history/plan_pinned.json --revision d0a59a0689f375ba72cad1729dd4cb19fd1f7c74
docker compose -f docker-compose.hdfs.yml --profile import build history-import
.\.venv\Scripts\python.exe scripts/hdfs_import_history.py run --plan runtime/hf_full_history/plan_pinned.json --workers 4 --chunk-size 128
docker compose -f docker-compose.hdfs.yml --profile import run --rm --no-deps history-import python3 /workspace/scripts/verify_hdfs_history_import.py --plan /import/plan_pinned.json --workers 8
docker compose -f docker-compose.hdfs.yml exec -T namenode hdfs fsck /bus-eta/v1/bronze/hf_raw
```

Plan đã có thì không tạo lại cùng tên; dùng nguyên plan để resume. Nếu mất plan local, tái lập từ đúng revision vào file mới dưới cùng thư mục. Lượt này pin một revision, không đuổi theo các batch crawler tiếp tục xuất hiện sau thời điểm chốt; không đọc toàn bộ lịch sử Git của repository.



Đã nhận đủ bus 3.649, incidents 2.285, traffic legacy 142. Chỉ JSONL dưới `raw_data/`, không gồm mọi Git commit hay batch sau revision. [Kết quả](evidence/hdfs_full_history/README.md). Plan mới dùng tên mới; cache/staging/checkpoint dưới `runtime/hf_full_history/` được ignore. Resume qua receipt không thay thế verify đọc lại toàn remote.

## Nhập tập batch nhỏ

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



## Silver/query

## Lệnh chạy

```powershell
# Xuất reference canonical đầy đủ; database chỉ mở read-only.
.\.venv\Scripts\python.exe scripts/export_hdfs_history_reference.py data/hanoi_bus_system.db runtime/history_reference_u3.json

# Dùng URI reference có hash mà lệnh trên trả về.
docker compose -f docker-compose.hdfs.yml exec -T spark-master /opt/spark/bin/spark-submit --master spark://spark-master:7077 --conf spark.cores.max=2 --conf spark.executor.cores=1 --conf spark.executor.memory=512m --conf spark.executorEnv.PYTHONPATH=/workspace /workspace/scripts/hdfs_build_history_snapshot.py --reference hdfs://namenode:8020/bus-eta/v1/reference/history/sha256=7e1664bb57315eb23875421de7d3b7de7b9982e0fe6cfd6d04037729df24a2aa/reference.json --batch-id d31126bc150d10c2f4c45504ce5fd15583df641dc5d070cd126fe9ea62285e6b 9a369ce3ed0e6c6203a71f3d8752c4c7854d69931cdc975082de3a7edbc58781
```

Builder đọc manifest nhận hoàn tất trong `_received/hf_batch/*/manifest.json`, xác minh byte raw và reference trước xử lý. Sau khi bổ sung nhập toàn lịch sử, bắt buộc chọn `--batch-id ID1 ID2 ...` để xử lý tập con, hoặc `--all-received` để chủ động yêu cầu recompute toàn ledger. Không dùng `--all-received` cho toàn lịch sử trên laptop khi chưa kiểm chứng tài nguyên. Source-window workflow U4–U6 đã truyền batch IDs cụ thể; lịch sử traffic được giữ ở Bronze, không ép vào incident observations.

Snapshot ID của lượt U3 ban đầu (ba batch); lệnh hai batch phía trên trả ID riêng:

```text
f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f
```

Chạy lại cùng batch/ref/code/policy trả `noop=true`, không append thêm Silver. Snapshot ID thay đổi khi một thành phần identity thay đổi. Không dùng `latest` ngầm để tránh ghép nguồn đang thay đổi. Dùng ID được trả về từ lượt chạy của mình nếu code hoặc dữ liệu đã đổi.

## Reader và API

```powershell
Invoke-RestMethod 'http://127.0.0.1:8090/api/history/route-speed?route_code=08A&date_from=2026-11-12&date_to=2026-11-12&snapshot_id=f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f'
```

Đã kiểm chứng trả 200, 140 ping, 127 speed samples, tốc độ trung bình 14,127165354330712 km/h. `avg_speed_kmh` chỉ tính trên speed không null; mẫu số count tốc độ được trả riêng. Query không có `snapshot_id` giữ đường P3A cũ để không đổi nguồn ngầm. Consumer ETA chọn snapshot qua cùng publication contract.

`load_history_snapshot()` chỉ đọc publication manifest rồi đối chiếu với completed snapshot metadata, không đọc một `_runs` tùy ý do client truyền. ID sai định dạng trả 400; chưa có publication/lỗi HDFS trả 503 qua API. Mỗi request vẫn dùng giới hạn thời gian và tài nguyên của API P3A.

## Đối soát

```powershell
docker compose -f docker-compose.hdfs.yml exec -T spark-master /opt/spark/bin/spark-submit --master local[1] /workspace/scripts/verify_hdfs_history_snapshot.py --snapshot f02a3bbf522eadf3bae1347ba63f0e50fcf54bf1c806e43dedb4c7e16223b57f --previous a2dc50ad61ac39d1ecfa92ad99ed37dee917eb7b85f996262c2c7dcce6226082
```

Đây là oracle riêng đọc HDFS bằng Spark local để không tranh thêm executor. Builder chính chạy Spark standalone với hai executor. Oracle chạy lại projection boundary chuẩn trên cùng đầu vào ở driver và so mọi cột Silver (trừ partition date), xác minh event cũ vẫn có trong lineage mới, đối chiếu query với Spark SQL. Đây là parity cùng định nghĩa nghiệp vụ; không phải chứng minh GPS đúng ngoài thực địa hoặc parity toàn database local.

## Failure và giới hạn

- `--fail-before-publish` cố ý dừng sau ghi snapshot, trước publication. Đã thử: API chưa thấy snapshot và trả 503; retry ghi attempt mới rồi công bố thành công. Run mồ côi được giữ để điều tra, chưa có garbage collector.
- Bản này recompute toàn bộ tập batch nhận, không phải incremental compute theo partition. Một route được gom trong RAM executor; chưa benchmark toàn bộ nhiều tháng.
- Reference lấy từ canonical SQLite, version bằng hash; history đầu vào lấy HDFS Bronze, không lấy snapshot lịch sử từ SQLite như P3A.
- Incidents có Silver observation riêng giữ JSON/geometry/null và event–batch lineage. Chưa spatial join thành `fact_route_tomtom_incidents`; bước domain ETA thực hiện từ cache Silver.
- Reject đầu vào có reason theo dòng; reject projection có ID/raw kèm reason chung, diagnostics chi tiết theo route từ boundary cũ. Chưa gán từng lý do geometry chi tiết cho từng event.
- Silver U3 ban đầu kiểm chứng 3 batch; Bronze hiện đầy đủ revision đã chốt, Silver toàn lịch sử chưa chạy. Noop kiểm tra read-back bus count; chưa có cơ chế checksum/repair toàn bộ file Parquet sau publication.


## ETA/Gold/offline release

## Phạm vi đã chạy

- Bổ sung bốn batch bus/incidents của 27/10 và 01/11 tại revision HF trong [source window](evidence/hdfs_u456/source_window.json). Ledger đã có ba batch U3 trước đó, nên snapshot tổng gồm bảy batch; consumer chỉ chọn hai ngày và tuyến `02`, `27`.
- Consumer dùng 358 ping, tạo 7.599 ô baseline, 14 incident facts và 414 feature rows (180 train, 234 test; 60 cột gồm metadata/target). Nhiều ô baseline phải dùng fallback do mẫu ít: 5.151 ô tier 3. Không dùng kết quả này để tuyên bố chất lượng model toàn hệ thống.
- Chạy lại từ cache khi chặn external process/HDFS cho kết quả baseline, incident facts và mọi Parquet giống từng giá trị. Kiểm tra split train/test theo cấu hình, không đổi split để tăng số mẫu.
- Global model hiện hữu nạp và dự đoán hữu hạn được trên 16 dòng. Đây là smoke test schema/preprocessing, không phải đo accuracy; chưa promote mapping `route_id_idx` của subset hai tuyến vào live serving và không retrain/ghi đè model.

Chi tiết hash, output và kiểm chứng: [evidence](evidence/hdfs_u456/README.md). Artifact đã chạy: `4ee4031b0330c244267f0a249eaa8b49f3151bd664c277945c1179045e500e8a`.

## Chuẩn bị

1. Có canonical SQLite local, HF credential theo cơ chế hiện hữu (`get_hf_token`); không đưa token vào source window hoặc container.
2. Bật Docker khi cần nạp/xử lý/đồng bộ. Khởi động NameNode, hai DataNode, Spark master và hai worker ở phần cluster bên trên.
3. Xuất reference bằng `scripts/export_hdfs_history_reference.py` ở phần Silver bên trên. URI hash trong source window phải khớp reference thực tế; không suy rằng mọi database trên máy khác cho cùng hash.
4. Build service truyền artifact riêng: `docker compose -f docker-compose.hdfs.yml --profile eta build eta-artifacts`. Service chỉ ở mạng HDFS riêng, repo mount read-only, chỉ `runtime/eta_releases` được mount ghi cho download; không mở thêm cổng.

## Một lệnh diễn tập từ HF

```powershell
.\.venv\Scripts\python.exe scripts/run_hdfs_eta_workflow.py --source-window docs/evidence/hdfs_u456/source_window.json --workspace runtime/eta_window_next --dates 2026-10-27 2026-11-01 --routes 02 27 --pointer runtime/eta_active.json
```

Lệnh pin revision, stage/upload batch qua U2, gọi U3 để lấy snapshot đã công bố, materialize nếu chưa có cache, chạy domain builders nếu chưa có output, publish, download/verify rồi mới activate pointer. Chạy lại tái dùng cache/output/release có cùng identity và kiểm tra code baseline/feature/pipeline; không append thêm feature hoặc ghi đè model. Nếu output dở chưa có manifest, chọn workspace mới; chưa có sửa tự động workspace dở.

Sau khi có importer toàn lịch sử, source-window workflow truyền batch IDs cụ thể cho builder; chỉ những batch trong source window được xử lý. Các snapshot kiểm chứng cũ từng gồm bảy batch đã nhận vẫn được giữ nguyên và đọc được, nhưng chạy lại với bộ lọc mới có thể cho snapshot ID mới. Hãy chọn workspace mới và dùng ID builder trả về khi phạm vi/code thay đổi. Không xóa batch ngoài lựa chọn khỏi Bronze; ngày/tuyến consumer vẫn là bộ lọc riêng.

Nếu Silver đã có, bỏ qua việc truy cập HF:

```powershell
.\.venv\Scripts\python.exe scripts/run_hdfs_eta_workflow.py --snapshot fcd8fdaa7f7717b00cf4282f3f9d1a0b7c54981e46b4238b7ae392a89e9ba1f9 --workspace runtime/eta_u456_03 --dates 2026-10-27 2026-11-01 --routes 02 27 --pointer runtime/eta_active.json
```

## Chạy từng bước hoặc offline

CLI `scripts/eta_snapshot_pipeline.py --help` có `materialize`, `build`, `publish`, `download`, `activate`, `inspect`, `baseline`. Bước `build` từ cache, `inspect` và `baseline --source release` không cần Docker/network.

```powershell
# Bản dữ liệu nào đang được chọn? Kiểm tra hash và identity trước khi trả thông tin.
.\.venv\Scripts\python.exe scripts/eta_snapshot_pipeline.py inspect --pointer runtime/eta_active.json

# Baseline từ release đã tải; không cần Docker.
.\.venv\Scripts\python.exe scripts/eta_snapshot_pipeline.py baseline --source release --pointer runtime/eta_active.json --route 02 --direction go --from-order 7 --to-order 8 --day-type 0 --hour-slot 13

# Đường local cũ vẫn có thể tra trực tiếp SQLite vận hành ở chế độ read-only.
.\.venv\Scripts\python.exe scripts/eta_snapshot_pipeline.py baseline --source local --database data/hanoi_bus_system.db --route 02 --direction go --from-order 7 --to-order 8 --day-type 0 --hour-slot 13
```

Hai chế độ hiển thị nguồn rõ ràng; không tự đổi nguồn sau lỗi. Release thử nghiệm không tự thay `data/hanoi_bus_system.db` hay cấu hình web demo. Khi cần nối serving hiện hữu, dùng cơ chế chọn DB của ứng dụng sau quyết định triển khai riêng; không sửa đè các thay đổi serving của người dùng.

## Kiểm chứng lại

```powershell
.\.venv\Scripts\python.exe scripts/verify_eta_snapshot_consumers.py --cache runtime/eta_u456_03/cache --output runtime/eta_u456_03/output --offline-output runtime/eta_u456_offline_next --model data/models/eta_xgb_global_full_54feat.json
.\.venv\Scripts\python.exe scripts/verify_eta_offline_release.py --pointer runtime/eta_active.json --scratch runtime/eta_offline_checks_next
```

Output/scratch mới không được tồn tại. Script thứ nhất chạy lại domain algorithms dưới chặn external calls, đối soát exact values, kiểm tra split và model thật. Script thứ hai đọc baseline từ release thật, tạo bản sao lỗi có chủ đích, xác nhận bị từ chối và pointer cũ còn nguyên khi refresh lỗi. Không dừng các dịch vụ Docker khác của người dùng; khả năng offline được xác minh bằng chặn external calls.

## Các giới hạn còn lại

- Đây là luồng có ích ở phạm vi mẫu, không chứng minh đủ dữ liệu huấn luyện global mới, coverage toàn mạng, phục vụ 24/7 hoặc tốc độ city-scale. Ngày train 27/10 nằm trong giai đoạn validation của trainer hiện hữu; lượt này không huấn luyện lại model.
- U3 vẫn recompute tập batch; materialize qua HDFS CLI theo file có overhead. Artifact nhiều file truyền bằng WebHDFS trong private service; không gọi Docker riêng cho từng file.
- Cache/artifact bị hỏng sẽ fail closed. Không tự chữa file corrupt hoặc xóa run mồ côi; giữ bản đang phục vụ. Release download được ghi vào `pending-UUID`, chỉ đổi tên và pointer sau verify; pending lỗi có thể cần dọn thủ công có chọn lọc.
- Kiểm tra hash toàn release phù hợp CLI/demo, chưa tối ưu thành cơ chế xác minh một lần cho API SLA thấp.
- Global model compatibility không chứng minh mapping route category hoặc accuracy trên subset tương đương model production. Live web/API model chưa được chuyển sang release này.


## Legacy và thử lỗi

Failpoint `HDFS_INGEST_FAULT=after_remote_commit_before_receipt` kiểm tra uploader P1 mất acknowledgement. Integration test U2 chủ động stop/start NameNode, chỉ chạy khi không có job khác. Dùng workspace mới, không sửa receipt đang dùng. API không snapshot ID giữ fixture legacy. Scale test giữ namespace `/bus-eta/v1/experiments/p3b/<run>` riêng, run ID mới cho mỗi lượt; không đưa synthetic vào lịch sử quan sát.
