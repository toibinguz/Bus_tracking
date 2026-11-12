# U1 — Hợp đồng batch HF và lịch sử HDFS

Trạng thái: U1 hoàn tất khảo sát có giới hạn và chốt hợp đồng cho U2; chưa triển khai importer U2 hoặc Silver tích lũy U3. Kế hoạch chung: [SPEC-44](44_UNIFIED_STORAGE_ARCHITECTURE_AND_EXECUTION_PLAN.md).

## 1. Nguồn đã kiểm tra

Đọc trực tiếp dataset `Toibinguz/hust-bus-data`, cố định revision `f2e7378002113cb548e194f2e8bd11c97a1b94d9`. Không ghi lên HF/GitHub. Danh sách tại revision này có 6.027 file; trong đó 3.616 đường dẫn batch bus. Đây là inventory file, không phải số event.

| Mẫu thực | Đường dẫn tại revision đã chốt | Kết quả |
| --- | --- | --- |
| Bus | `raw_data/2026-11-12/bus/batch_161350.jsonl` | 5.110 dòng; 1.990.612 byte |
| Incidents | `raw_data/2026-11-12/incidents/batch_161350.jsonl` | 192 dòng |

Hash, schema, mẫu dòng, thống kê timestamp và reference: [raw inspection](../evidence/hdfs_u1/hf_inspection.json). File batch đầy đủ giữ ở `runtime/hdfs_u1_inspection_02/`, không chép dữ liệu lớn vào docs. Khảo sát một batch mỗi loại, không suy rộng thành toàn bộ lịch sử đều sạch.

Lệnh tái lập (output mới):

```powershell
.\.venv\Scripts\python.exe scripts/inspect_hf_storage_contract.py --revision f2e7378002113cb548e194f2e8bd11c97a1b94d9 --reference-db data/hanoi_bus_system.db --output runtime/hdfs_u1_inspection_next
```

Script lấy revision một lần trước khi liệt kê/tải file. Chỉ dùng credential cho truy cập HF, không ghi token vào report. Reference SQLite mở `mode=ro`. Kiểm tra reference chỉ hash mapping route/station đã đọc, chưa phải hash toàn bộ shape bundle để chạy projection U3.

## 2. Mapping bảng

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

## 3. Timestamp, direction và reference

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

## 4. Identity và manifest cho U2

### Nhận batch

- Pin HF commit trước lượt scan; chỉ xử lý đường dẫn bus/incidents được chọn trong revision đó. Cửa sổ ngày là bộ lọc tải, không thay timestamp thực của event.
- `batch_id = sha256(canonical_json({dataset, path, content_sha256}))`. Chuỗi canonical dùng UTF-8, sort keys, separator gọn. Revision không nằm trong batch_id để cùng byte/cùng đường dẫn ở revision khác không bị nhận lại thành batch mới.
- Receipt vẫn ghi revision lần nhận và byte count/hash. Cùng path khác hash là batch version mới, giữ cả hai; không overwrite. Hai path khác nhau có thể chứa ping trùng: xử lý ở event identity U3, không dựa vào receipt batch để tuyên bố loại trùng event.
- HDFS byte object: `/bus-eta/v1/bronze/hf_raw/category=<bus|incidents>/sha256=<content_sha256>/batch.jsonl`. Lưu byte nguyên bản, metadata riêng theo batch_id. Cùng nội dung khác path có thể chia sẻ byte object nhưng không mất lineage nguồn.
- Manifest `hf-batch.v1`: `batch_id`, `dataset`, `revision`, `path`, `category`, `content_sha256`, `bytes`, `hdfs_raw_path`, `received_at_utc`, `schema_version`. Các giá trị thực chỉ điền khi có bằng chứng; không tạo số row hoặc captured_at từ metadata tên file.
- Hoàn tất nhận khi byte object và metadata đã kiểm tra được; crash giữa hai bước phải retry được. Không đánh receipt thành công chỉ vì CREATE trả 201; verify size/hash hoặc readable exact object trước commit.

### Nhận event (U3)

Tái dùng `canonical_event_id` hiện có với source_name `busmap`, source_record_id rỗng vì batch không có ping_id, và route/vehicle/observed epoch/lat/lon. Cùng ping qua nhiều poll/batch có cùng ID; capture time và batch_id không tham gia event identity. Giữ association event↔batch riêng để không mất poll lineage. Không tự thêm ping_id local vào HF event rồi gọi đó là identity chung.

## 5. Inventory và phạm vi thay đổi tối thiểu

| Nhóm hiện có | Giữ / thay đổi tiếp |
| --- | --- |
| workflow relay, `cloud_crawler_step.py`, `cloud_crawler_runner.py`, `hf_lake_sync.py` | Giữ, chưa cần sửa ở U2: đã có batch nguồn đủ để nạp |
| `dataset_sync.py`, `sync_from_hf.py` | Giữ đường local. Không dùng trực tiếp làm ledger ingest: hiện tải main và di chuyển file, chưa pin revision/receipt hash |
| `hdfs_bronze_adapter.py`, contract envelope | Giữ cho dẫn xuất bus; chưa phù hợp incidents và batch nguyên bản. Không ép hai schema vào một envelope |
| `spool.py`, `webhdfs.py`, `hdfs_ingest_runner.py` | Giữ path P1 cũ; U2 thêm importer batch HF qua CLI riêng, dùng lại primitive upload/hash khi hợp đồng phù hợp. Không đổi format receipt cũ ngầm |
| `p2_transform.py`, `hdfs_p2_transform.py` | U3 bổ sung HF adapter, reference đầy đủ, mapping ambiguity, dedup/cumulative publication; không sửa ở U1 |
| P3A/P3B, `eta_history_baseline.py`, verify scripts | Giữ evidence/consumer test. U4 thay nguồn snapshot; không dùng script benchmark làm importer production |
| `inspect_hf_storage_contract.py` | Công cụ read-only tái lập U1, không phải orchestrator ingest |

Phạm vi U2: một module batch identity/manifest + CLI pin revision/stage/upload + kiểm thử retry/hash/offline. Chưa làm projection, huấn luyện hoặc chỉnh serving trong U2. U3 phải giải quyết direction/reference trước khi công bố Silver; đây là dependency đã xác định, không phải lý do chặn U2 lưu batch gốc.

## 6. Điều kiện bàn giao U1

Đã truy được hai batch HF thực ở cùng revision, lưu hash/schema/sample; mapping rõ tới Bronze và bảng nghiệp vụ; xác định direction/timezone/reference thiếu; chốt batch identity/manifest và ranh giới incidents. Có inventory thay đổi tối thiểu. Không khẳng định đã đối soát projection toàn lịch sử hoặc đã chạy ingest HDFS bằng dữ liệu này.
