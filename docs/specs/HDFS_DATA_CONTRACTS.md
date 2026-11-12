# Hợp đồng dữ liệu và runtime HDFS

[Kiến trúc/trạng thái](../HDFS_README.md) · [Runbook](../HDFS_RUNBOOK.md). Hợp nhất hợp đồng U1–U6 và runtime P1/P2; không phải lượt nghiệm thu mới. Hành vi xác định bởi code và CLI hiện tại. Các số mẫu trong phần mapping thuộc khảo sát U1, không suy rộng toàn kho.

## Runtime và network

- Compose `hdfs-private` internal, DataNode/receiver không publish port. NameNode UI 9870 chỉ loopback để quan sát. WebHDFS redirect DataNode nên transport chạy trong private container; HF credentials chỉ dùng host.
- Repo mount read-only; staging/release mount ghi theo service. Shared hash/receipt không kéo host spool/timezone vào Python 3.8 container; package facade lazy exports không eager import legacy pandas/pyarrow.
- Spark `apache/spark:3.5.4`, NumPy `1.24.4` cài lúc build; cuối Dockerfile `USER spark`. Không runtime pip/geometry fallback; SQL timezone được đặt trong transform.
- Bronze/reference root-owned, Silver/Gold và checkpoint/publication P2 của Spark thuộc spark, mode 755. Không chmod777, chown đệ quy toàn kho, tắt permissions hay chạy Spark root để chữa lỗi quyền.
- Bulk importer kiểm tra source size/Git blob hoặc LFS digest; upload temp UUID/rename, verify remote trước receipt. Checkpoint chỉ hỗ trợ resume; hoàn tất cần đọc lại byte/manifest/revision toàn kho, fsck khỏe.
- Traffic legacy archive nguyên byte ở Bronze, không ép thành incidents. Builder yêu cầu `--batch-id ...` hoặc chủ động `--all-received`; source-window chỉ truyền batch IDs đã chọn. Không chạy toàn ledger trên laptop trước kiểm chứng RAM.

## Mapping bảng

### Bus

Batch đã qua sanitizer crawler: tọa độ `lat/lon` đã chuẩn hóa; giữ nguyên byte đầu vào, không đảo lại tọa độ như response API. Các trường hiện có trên mọi dòng mẫu: `vehicle_id`, `plate`, `route_id`, `lat`, `lon`, `speed`, `raw_speed`, `calculated_speed`, `direction`, `heading_deg`, `current_station_id`, `next_station_id`, `device_update_time`, `crawled_at`, `quality_status`.

| Trường nguồn | Đích / quy tắc |
| --- | --- |
| `route_id` | Tra route code từ canonical reference version đã chốt; không đoán từ số route |
| `vehicle_id`, `plate` | Giữ giá trị nguồn |
| `device_update_time` | Event time; chuẩn hóa thành epoch ms; giữ chuỗi gốc trong raw/payload |
| `crawled_at` | Capture time, không phải thời điểm importer nạp HDFS; ingestion time là metadata riêng |
| `lat`, `lon` | Tọa độ nguồn đã sanitizer; validate số hữu hạn/range trước projection |
| `direction`, `current_station_id` | Giữ raw direction; resolve direction theo reference và quy tắc phần 3 |
| Các speed nguồn | Giữ trong payload; không giả định chúng bằng `derived_speed_kmh` tính từ trajectory |
| `quality_status` | Giữ raw; Bronze không lọc. Silver ghi diagnostics theo guard nghiệp vụ hiện hữu, không mặc định chỉ nhận ACTIVE_VALID rồi gọi là parity |
| Projection | `s_bus_m`, `cross_track_m`, `derived_speed_kmh` do boundary nghiệp vụ hiện hữu tạo; không có sẵn trong batch HF |

Đích logic: Bronze batch nguyên bản → canonical envelope dẫn xuất → Silver `route_projected_telemetry`. Không bắt buộc qua SQLite mới vào HDFS. Local importer vẫn giữ contract riêng; đối soát bằng business fields, không yêu cầu `ping_id` SQLite bằng event ID.

### Incidents

Đây là loại dữ liệu riêng, không đưa vào `TelemetryEnvelope`. Nguồn gồm `timestamp`, `incident_id`, `icon_category`, `magnitude_of_delay`, `delay_seconds`, `length_meters`, `description`, `geometry_type`, `coordinates`. `timestamp` là thời điểm chụp incident; mẫu có offset ở 192/192 dòng. Không có `device_update_time`, `crawled_at`, start/end time; không tự sinh chúng từ tên file.

`coordinates` giữ thứ tự nguồn `[lon, lat]`; `delay_seconds=null` vẫn là null, không đổi thành 0. Đích là Bronze incidents riêng, sau đó mapping sang bảng incidents chuẩn và `fact_route_tomtom_incidents` bằng projector hiện hữu ở U3/U4. Một `incident_id` có thể được chụp nhiều lần: giữ các observation theo thời điểm, không loại hết chỉ vì cùng ID. Exact duplicate observation có thể loại theo hash của nội dung canonical (gồm timestamp); version thay đổi không bị ghi đè.

## Timestamp, direction và reference

Mẫu bus có offset ở cả hai timestamp trên 5.110/5.110 dòng. Dòng thiếu offset/không parse được giữ ở Bronze nhưng vào rejection/quarantine khi tạo envelope; không suy timezone từ tên thư mục.

Reference hiện tại nhận được route của 5.005/5.110 dòng; 105 dòng không có route tương ứng. Lookup trạm đối chiếu cho thấy:

| Raw direction | Trạm xác định go | Trạm xác định re | Trạm nhiều chiều | Không có mapping trạm |
| --- | --- | --- | --- | --- |
| 0 | 1.916 | 0 | 293 | 15 |
| 1 | 0 | 1.766 | 185 | 15 |
| -1 | 0 | 0 | 0 | 920 |

Các nhóm này chồng với nhóm route chưa biết, không cộng thành số reject. Comments trong sanitizer nói hướng khác nhưng code lưu raw direction nguyên giá trị; mẫu và reference đang khớp helper `0→go`, `1→re`. Không đổi mapping toàn hệ thống dựa trên comment.

Quy tắc cho HF adapter mới, có version: nếu `(route_id, station_id)` chỉ có một direction chuẩn thì dùng nó; nếu ambiguous/missing thì chỉ dùng hint `0→go`, `1→re` đã khai báo trong source contract; `-1` là unknown, không biến thành return. Nếu không xác định được direction sau cả hai bước thì ghi lý do không đưa vào projection. Trạm hai chiều phải được giữ dưới dạng tập mapping; không xây dict làm mất một chiều do ghi đè thứ tự SQL.

Route chưa biết không được làm fail upload batch. Toàn batch vẫn nhận ở Bronze; từng event chưa resolve được ghi reject/reference_pending. Khi có reference mới có thể xử lý lại từ Bronze. U3 phải khóa full reference bundle (route mapping, trạm và shapes), hash/version và source code revision; không dùng fixture route08A cắt ngắn cho mọi tuyến.

## Identity và manifest

### Nhận batch

- Pin HF commit trước lượt scan; xử lý đường dẫn bus/incidents/traffic được chọn trong revision đó. Cửa sổ ngày là bộ lọc tải, không thay timestamp thực của event.
- `batch_id = sha256(canonical_json({dataset, path, content_sha256}))`. Chuỗi canonical dùng UTF-8, sort keys, separator gọn. Revision không nằm trong batch_id để cùng byte/cùng đường dẫn ở revision khác không bị nhận lại thành batch mới.
- Receipt vẫn ghi revision lần nhận và byte count/hash. Cùng path khác hash là batch version mới, giữ cả hai; không overwrite. Hai path khác nhau có thể chứa ping trùng: xử lý ở event identity U3, không dựa vào receipt batch để tuyên bố loại trùng event.
- HDFS byte object: `/bus-eta/v1/bronze/hf_raw/category=<bus|incidents|traffic>/sha256=<content_sha256>/batch.jsonl`. Lưu byte nguyên bản, metadata riêng theo batch_id. Cùng nội dung khác path có thể chia sẻ byte object nhưng không mất lineage nguồn.
- Manifest `hf-batch.v1`: `batch_id`, `dataset`, `revision`, `path`, `category`, `content_sha256`, `bytes`, `hdfs_raw_path`, `received_at_utc`, `schema_version`. Các giá trị thực chỉ điền khi có bằng chứng; không tạo số row hoặc captured_at từ metadata tên file.
- Hoàn tất nhận khi byte object và metadata đã kiểm tra được; crash giữa hai bước phải retry được. Không đánh receipt thành công chỉ vì CREATE trả 201; verify size/hash hoặc readable exact object trước commit.

### Nhận event (U3)

Tái dùng `canonical_event_id` hiện có với source_name `busmap`, source_record_id rỗng vì batch không có ping_id, và route/vehicle/observed epoch/lat/lon. Cùng ping qua nhiều poll/batch có cùng ID; capture time và batch_id không tham gia event identity. Giữ association event↔batch riêng để không mất poll lineage. Không tự thêm ping_id local vào HF event rồi gọi đó là identity chung.


## Quyết định phạm vi

- Mỗi lượt chốt danh sách manifest nhận hoàn tất. Bản đầu recompute toàn bộ batch đã chọn để bảo đảm đúng trajectory khi có batch trễ; chưa tối ưu chỉ tính partition bị ảnh hưởng. Đây là tích lũy logic, không tuyên bố incremental compute.
- Dedup event bus xuyên batch bằng identity ở phần trên; chọn observation có capture time sớm nhất, tie-break nội dung canonical; giữ quan hệ event–batch. Reference trạm ambiguous dùng raw hint đã chốt, không ghi đè mapping.
- Spark group theo route và gọi đúng projection boundary hiện hữu trên executor. Mỗi route được xử lý trong RAM executor: phù hợp phạm vi thử; chưa chứng minh xử lý vô hạn.
- Incidents có Silver observation riêng: giữ JSON nguồn, timestamp, geometry và delay null; loại exact duplicate. Bước domain ETA chạy spatial join từ cache để tạo fact_route_tomtom_incidents.
- Snapshot immutable gồm Silver bus, incidents, lineage, reject/diagnostics và reference. Chỉ có publication manifest mới cho phép reader nhìn snapshot. Không tự đổi nguồn API cũ hoặc bản serving hiện hữu.
- Key snapshot khóa tập batch/hash, full reference hash, source code và policy. Lỗi trước publication giữ run mồ côi nhưng không làm reader thấy dữ liệu dở; chạy lại dùng attempt mới, không xóa output cũ.

## AC

| ID | Điều kiện |
| --- | --- |
| S1 | Reference export read-only, đầy đủ shapes/stations/routes có hash; raw batch HDFS verify theo manifest |
| S2 | Snapshot chứa toàn bộ tập batch đã chọn; trùng batch/event không nhân đôi; có nguồn gốc event–batch |
| S3 | Direction, timestamp, route thiếu và projection guards theo nghiệp vụ; reject/diagnostics được lưu |
| S4 | Batch trễ được tính cùng lịch sử; cùng tập input/ref/code/policy có cùng key và logical rows bất kể thứ tự nhận |
| S5 | Chỉ đọc snapshot đã công bố; crash trước publish không lộ dữ liệu; retry và noop an toàn |
| S6 | Query route/date trên snapshot khớp Spark độc lập; chạy thực HF → Bronze → Silver, lưu evidence và giới hạn |

## U4 — Consumer nghiệp vụ thật

- Đọc publication U3, kiểm tra snapshot/reference; materialize Silver bus/incidents và full reference vào cache versioned. Có thể chọn ngày/route rõ ràng, lựa chọn là một phần identity cache.
- Chạy baseline, incident projector và feature builder hiện hữu trên workspace riêng. Xử lý này chạy local, không gắn nhãn Spark. Module-3 worker phải nhận đúng đường dẫn workspace trên Windows spawn.
- Lưu baseline SQLite, Gold Parquet và feature store cùng manifest/hash/code/split về HDFS dưới một artifact ID bất biến. Chỉ publish sau kiểm tra.
- AC: baseline và feature cùng input/reference/split; schema/keys/count và mọi giá trị đối soát bằng lần chạy local từ cùng cache (exact equality); không có ngày test trong train features; global model thực load/predict được (không suy ra accuracy/parity model từ vài dòng); database/model gốc không bị ghi đè.

## U5 — Offline và bản phục vụ

- Tải artifact đã publish về local release bất biến, verify toàn bộ hash. Một pointer local chỉ đổi atomically khi release đầy đủ. Giữ bản tốt trước nếu tải lỗi; không ghép hai snapshot.
- Local hiện hữu giữ nguyên; cache/release offline dùng nguồn cụ thể và ghi version. Không tự chuyển nguồn âm thầm. Không ép web demo chuyển database trong bước này.
- AC: offline không cần Docker/network để kiểm tra release, đọc baseline/features và dùng model local; cache hỏng bị từ chối; lỗi download không đổi pointer; hai release có thể chuyển an toàn và truy ngược nguồn.

## U6 — Diễn tập có giới hạn

- Một CLI điều phối sync-source snapshot → build → publish → download → activate/inspect, với lệnh độc lập để retry từng phần. Dùng train/test batch HF thật; không tạo nhãn hoặc sửa split để làm đẹp kết quả.
- AC: từ HF revision/batch trace đến Silver và Gold/features, một lần thêm batch đã tạo snapshot nghiệp vụ mới (kế thừa U3 và kiểm tra artifact liên kết); retry không overwrite; offline/corruption/failed refresh có test; runbook duy nhất ghi phạm vi mẫu và phần chưa production-ready.
- Không bắt buộc retrain global model, tải toàn lịch sử HF hay chuyển live serving. Nếu dữ liệu quá ít, ghi số mẫu/coverage thực tế và trạng thái thiếu dữ liệu.


## Phạm vi kiểm chứng

AC chỉ được coi đạt trong phạm vi evidence được dẫn ở chỉ mục. Thay code/phạm vi phải kiểm chứng phần bị ảnh hưởng; số lượng batch/byte không phải số event. Hai DataNode/executor chung laptop không có độc lập lỗi phần cứng hoặc HA NameNode. Chưa có GC/compaction toàn kho; không sửa/xóa nguồn phục vụ để chữa output dở.
