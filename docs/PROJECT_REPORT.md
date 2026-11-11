# BÁO CÁO ĐỒ ÁN

## Hệ thống lưu trữ, xử lý dữ liệu telemetry xe buýt và dự báo ETA

| Trường thông tin | Nội dung |
| --- | --- |
| Cơ sở đào tạo | **[Điền tên trường/khoa/bộ môn]** |
| Học phần | Lưu trữ và xử lý dữ liệu lớn |
| Giảng viên hướng dẫn | **[Điền họ tên]** |
| Nhóm thực hiện | **[Điền thành viên, MSSV, phân công]** |
| Học kỳ / năm học | **[Điền]** |
| Phiên bản | 1.0 |
| Mốc evidence | E1 — 10/11/2026, Asia/Ho_Chi_Minh |
| Snapshot E1 | `cee5324f3cda08dcbe46ed35a7bf4a78ff6c177d` |

> Các ô trong ngoặc vuông là thông tin hành chính không có trong repository. Nhóm
> phải điền theo mẫu của khoa. Mọi số liệu kỹ thuật chỉ áp dụng cho snapshot E1.

---

## Lời cam đoan

Nhóm cam đoan các số liệu trong báo cáo được truy vết về mã nguồn, artifact dữ liệu,
artifact mô hình hoặc lệnh tái lập ở Phụ lục A. Nội dung chưa có phép đo được ghi
*N/A — chưa đo* hoặc *đang tích hợp*, không suy diễn từ proposal, README hay thiết kế.

## Lời cảm ơn

**[Nhóm tự điền lời cảm ơn giảng viên, đơn vị cung cấp dữ liệu và các cá nhân/tổ chức
liên quan.]**

## Tóm tắt

Đồ án xây dựng pipeline thực nghiệm cho dữ liệu vị trí xe buýt: thu nhận và chuẩn
hóa telemetry, chiếu vị trí lên hình học tuyến, lưu trong SQLite và lakehouse
Parquet, rồi huấn luyện mô hình dự báo thời gian đến trạm (ETA). Tại E1, SQLite có
5.565.232 telemetry đã chiếu của 48 tuyến và 481 xe; Silver lakehouse được kiểm toán
trên 1.191 tệp và 5.565.232 hàng. Model-6 là **một model toàn cục**, đạt MAE 96,70
giây, RMSE 170,89 giây và P90 absolute error 244,58 giây trên 3.704.820 hàng temporal
held-out. [E1]

Nhánh lưu trữ phân tán được thiết kế theo `spool → WebHDFS Bronze → Spark
Silver/Gold → historical query`. Tại E1 chưa có evidence ledger cho Spark
Silver/Gold hoặc API historical; báo cáo vì vậy chỉ gọi chúng là đang tích hợp.

**Từ khóa:** telemetry xe buýt; ETA; Frenet; SQLite; Parquet; HDFS; Spark; XGBoost.

## Abstract

This project implements an experimental pipeline for bus-position telemetry: data
collection and normalization, route-geometry projection, operational and Parquet
lakehouse storage, and estimated-time-of-arrival (ETA) modelling. At E1, SQLite
contains 5,565,232 projected telemetry rows from 48 routes and 481 vehicles. The
Silver audit scanned 1,191 files and 5,565,232 rows. Model-6 is a **global** ETA
model; on 3,704,820 temporal held-out rows it records MAE 96.70 seconds, RMSE 170.89
seconds, and P90 absolute error 244.58 seconds. [E1]

The distributed historical-storage path is specified as `spool → WebHDFS Bronze →
Spark Silver/Gold → historical query`. E1 contains no ledgered evidence for Spark
Silver/Gold or the historical API, so those items are reported as in progress.

**Keywords:** bus telemetry; ETA; HDFS; Spark; Parquet; global model.

## Mục lục

1. [Giới thiệu](#1-giới-thiệu)  
2. [Cơ sở và phương pháp](#2-cơ-sở-và-phương-pháp)  
3. [Yêu cầu, phạm vi và kiến trúc](#3-yêu-cầu-phạm-vi-và-kiến-trúc)  
4. [Module 1 — Thu thập và chuẩn hóa](#4-module-1--thu-thập-và-chuẩn-hóa)  
5. [Module 2 — Lưu trữ và lakehouse](#5-module-2--lưu-trữ-và-lakehouse)  
6. [Module 3 — Mô hình ETA toàn cục](#6-module-3--mô-hình-eta-toàn-cục)  
7. [Thực nghiệm và thảo luận](#7-thực-nghiệm-và-thảo-luận)  
8. [Tái lập, giới hạn và đạo đức](#8-tái-lập-giới-hạn-và-đạo-đức)  
9. [Kết luận và kế hoạch](#9-kết-luận-và-kế-hoạch)  
Phụ lục A–D; Tài liệu tham khảo.

## Danh mục hình

| Hình | Nội dung | Trạng thái |
| --- | --- | --- |
| Hình 3.1 | Luồng Module 1 → Module 3 và nhánh HDFS | sơ đồ ASCII trong §3.1; có thể thay bằng hình vẽ khi dàn trang |
| Hình 5.1 | Luồng historical `spool → WebHDFS → Spark` | thiết kế; chưa dùng làm evidence thực nghiệm |

## Danh mục bảng

| Bảng | Nội dung |
| --- | --- |
| 4.1 | Inventory Module 1 |
| 5.1 | Inventory local lakehouse |
| 6.1 | Held-out metric Model-6 global |
| 6.2 | Evaluation Model-4 global theo tuyến 02/27 |
| 6.3 | Phân rã lỗi Model-6 theo số đoạn trạm còn lại (E2) |
| 7.1 | Chứng cứ theo stage pipeline |

## Danh mục chữ viết tắt

| Viết tắt | Nghĩa |
| --- | --- |
| API | Application Programming Interface |
| ETA | Estimated Time of Arrival |
| HDFS | Hadoop Distributed File System |
| MAE | Mean Absolute Error |
| P90 AE | phân vị 90 của sai số tuyệt đối |
| RF | replication factor |
| RMSE | Root Mean Squared Error |

## Xác nhận và phê duyệt

**[Chèn trang giao nhiệm vụ, xác nhận của giảng viên, nhận xét/phê duyệt và chữ ký
theo đúng biểu mẫu của khoa. Repository không chứa các tài liệu hành chính này.]**

---

# 1. Giới thiệu

## 1.1. Bài toán

Dữ liệu vị trí xe buýt là chuỗi quan sát theo thời gian, có tuyến, xe, tọa độ và ngữ
cảnh vận hành. Để phục vụ ETA, vị trí thô cần liên hệ với hình học tuyến, thời gian
và lịch sử di chuyển. Trạng thái gần nhất phục vụ giao diện live không đủ làm nguồn
lịch sử để kiểm toán, phân tích hay huấn luyện mô hình. Đồ án vì vậy đặt chuỗi dữ liệu
và khả năng truy vết từ telemetry đến ETA làm trọng tâm.

Mục tiêu thực nghiệm là chứng minh pings được chuẩn hóa và chiếu theo tuyến, được lưu
trong SQLite/Parquet, rồi được dùng cho đánh giá ETA. Mục tiêu của học phần là phát
triển thêm đường HDFS/Spark có ranh giới ingest và analytical storage rõ ràng. Đây là
mô phỏng tái lập trên thiết bị sinh viên, không phải cam kết dịch vụ đô thị 24/7.

## 1.2. Mục tiêu và câu hỏi đánh giá

1. Repository có tạo telemetry gắn tuyến và thỏa contract hình học hay không?
2. Local operational store và Parquet lakehouse có inventory/audit tái lập hay không?
3. Model ETA toàn cục có metric trên temporal held-out split xác định hay không?
4. HDFS/Spark cần bằng chứng gì trước khi được coi là thành phần hoàn chỉnh?

Không thuộc phạm vi: SLA, NameNode HA, continuous streaming, benchmark scale-out,
hoặc khẳng định bao phủ toàn bộ mạng xe buýt Hà Nội. E1 không có bằng chứng cho chúng.

## 1.3. Đóng góp có thể xác nhận

Tại E1, có thể xác nhận: artifact SQLite gồm master, pings, projected telemetry và
facts; local Parquet Silver/Gold có inventory; audit Silver quét toàn bộ lakehouse;
và Model-6 global có metadata, hash, split và held-out metric. [E1] Ý tưởng không có
artifact/log không được liệt kê là đóng góp hoàn thành.

---

# 2. Cơ sở và phương pháp

## 2.1. Nguyên tắc evidence-first

Codebase, artifact và lệnh tái lập là nguồn chân lý. README, proposal và design spec
chỉ mô tả ý định. Mỗi số liệu `[E1]` tham chiếu tới
[`EVIDENCE.md`](evidence/2026-11-10_report_baseline/EVIDENCE.md), nơi có commit,
đường dẫn artifact, lệnh, đơn vị và raw results. Giá trị chưa có phép đo dùng đúng
cụm **N/A — chưa đo**.

## 2.2. Lakehouse, HDFS, Spark và ETA

Repository lưu dữ liệu nghiệp vụ trong SQLite và xuất dữ liệu phân tích theo Parquet.
Trong báo cáo, Silver local không được đồng nhất với HDFS. Spark SQL là mô-đun xử lý
dữ liệu có cấu trúc qua SQL/DataFrame, có thể đọc nguồn như Parquet và JSON [R2]. HDFS
lưu block trên DataNode, có NameNode quản lý metadata và replication [R1]. Các khái
niệm này giải thích evidence cần có cho nhánh phân tán, không chứng minh repository
đã chạy Spark/HDFS end-to-end.

Pipeline biểu diễn telemetry theo hình học tuyến qua `s_bus_m` và `cross_track_m`.
XGBoost là thư viện gradient boosting dùng cho Model-6 [R3]. Metric ETA được lấy từ
metadata artifact, không được tái tính bằng văn bản.

## 2.3. Thiết kế đánh giá

`data/splits/train_test_split_v1.json` ghi train từ 08/10/2026 đến 01/11/2026 và test
từ 02/11/2026 đến 07/11/2026. Contract split dùng `cross_track_m <= 35,0`. [E1]
Inventory train/validation per-route, missingness per-feature và horizon table là
N/A — chưa đo tại E1.

---

# 3. Yêu cầu, phạm vi và kiến trúc

## 3.1. Ranh giới module

```text
Nguồn ping/crawler
  → Module 1: chuẩn hóa, master data, route/Frenet projection
  → Module 2: SQLite operational store và Parquet Silver/Gold cục bộ
  → Module 3: feature, model và evaluation ETA toàn cục

Nhánh historical phân tán đang tích hợp:
  durable spool → WebHDFS Bronze → Spark Silver/Gold
  → historical query → ETA-history validation
```

SQLite là artifact canonical/operational đã đo. Khi hoàn thiện, HDFS phục vụ lịch sử
analytics, không thay SQLite cho latest state hoặc ETA live. Đây là ranh giới để tránh
đưa truy vấn HDFS trực tiếp vào request path độ trễ thấp.

## 3.2. Hợp đồng và trạng thái

Nhánh HDFS có design envelope gồm `schema_version`, provenance, `source_window_id`,
`event_id`, observed/received time và bus identity. Đây là **contract thiết kế**;
không phải số liệu thực nghiệm E1. Contract phân biệt observed, replayed_observed và
synthetic_scale; dữ liệu tổng hợp chỉ dùng benchmark cơ chế, không báo cáo ETA
accuracy.

| Nhóm yêu cầu | Evidence E1 | Trạng thái |
| --- | --- | --- |
| Master/ping/telemetry/facts | SQLite artifact | có [E1] |
| Corridor quality | metric telemetry | có [E1] |
| Local Parquet Silver | audit | pass [E1] |
| ETA global | hash, split, metric | có [E1] |
| HDFS ingest/transform/query | end-to-end raw log | N/A [E1] |
| SLA/HA/streaming | evidence production | ngoài phạm vi |

---

# 4. Module 1 — Thu thập và chuẩn hóa

## 4.1. Vai trò module

Module 1 tạo nền dữ liệu: pings, master tuyến/shape/trạm, sanitizer và route
projection. Các entry point được ledger hóa gồm `bulk_ping_ingester.py`,
`telemetry_sanitizer.py` và `multi_route_projector.py`. [E1] E1 không có log input
đầy đủ theo nguồn, nên không gán cho API thu thập tần suất, coverage hay SLA.

## 4.2. Inventory dữ liệu

**Bảng 4.1 — Inventory Module 1 tại E1, snapshot
`cee5324f3cda08dcbe46ed35a7bf4a78ff6c177d`.**

| Bảng SQLite | Số hàng | Diễn giải tối thiểu |
| --- | ---: | --- |
| `canonical_route_master` | 176 | master tuyến |
| `canonical_shape_master` | 118.563 | hình học tuyến |
| `canonical_station_master` | 13.301 | master trạm |
| `vehicle_unique_pings` | 7.333.298 | ping sau unique contract |
| `route_projected_telemetry` | 5.565.232 | telemetry đã chiếu |
| `fact_route_tomtom_incidents` | 836.761 | incident fact |
| `agg_segment_travel_times` | 169.830 | aggregate travel-time |

Nguồn toàn bảng: [E1], `COUNT(*)` trên `data/hanoi_bus_system.db`. Chênh lệch giữa
các bảng không phải rejection rate; E1 chưa có denominator/rejection-reason ledger.

## 4.3. Route projection và kiểm tra hình học

Projected telemetry trải từ `2026-10-08T12:55:20+07:00` đến
`2026-11-07T13:53:37+07:00`, gồm 48 route code và 481 vehicle ID. Mean
`cross_track_m` là 7,263 m, maximum là 35,0 m và số hàng có `cross_track_m > 35` là
0. [E1] Kết quả này xác nhận artifact đầu ra thỏa contract `cross_track_m <= 35`,
nhưng không cho biết số ping bị loại trước khi vào bảng hay khẳng định shape tuyệt đối
chính xác.

Direction `go` có 2.777.696 hàng (49,91%) và `re` có 2.787.536 hàng (50,09%). Số
direction invalid và over-corridor trong telemetry cuối cùng đều là 0. [E1] Đây là
đặc tính artifact cuối, không phải coverage của toàn thành phố.

## 4.4. Phần cần đo thêm

Bản nộp cuối cần flow input → accepted → rejected theo stage và reason, duplicate
rate, missingness, time-order violations và phân vị cross-track. Tại E1 tất cả chỉ số
này là N/A — chưa đo; báo cáo không dùng các từ “sạch hoàn toàn” hay “đầy đủ”.

---

# 5. Module 2 — Lưu trữ và lakehouse

## 5.1. SQLite operational/canonical store

`data/hanoi_bus_system.db` có kích thước 3.081.240.576 byte tại E1. [E1] Nó chứa
các bảng đã thống kê ở Chương 4 và là local canonical/operational artifact; nó không
là bằng chứng distributed storage. Phân biệt này giúp báo cáo không thay một kho cục
bộ bằng mô tả “big data” không có số liệu.

## 5.2. Lakehouse Parquet cục bộ

**Bảng 5.1 — Inventory local lakehouse tại E1.**

| Vùng | Số tệp | Kích thước | Evidence |
| --- | ---: | ---: | --- |
| Silver `data/lakehouse/` | 1.361 | 1.719.937.794 byte | [E1] |
| Gold `data/lakehouse/gold/` | 96 | 1.359.923.163 byte | [E1] |

`scripts/audit_silver_lakehouse_purity.py` scan 1.191 tệp Silver, 5.565.232 hàng và
pass; wall time 20,21 s, throughput 275.313 hàng/s. [E1] Throughput này chỉ là
thời gian audit ở môi trường E1, không phải ingest/query throughput hay benchmark
cluster.

## 5.3. HDFS/Spark — mục tiêu kỹ thuật

Nhánh historical được thiết kế là collector đóng spool bền vững, uploader đẩy Bronze
JSONL qua WebHDFS, Spark biến đổi Silver/Gold Parquet và query bounded trả aggregate
lịch sử. HDFS dùng replication để lưu nhiều replica block [R1]; Spark SQL xử lý dữ
liệu cấu trúc [R2]. Đây là lựa chọn kiến trúc phù hợp để tách ingest, historical
storage và analytical processing trong bài tập.

## 5.4. Trạng thái HDFS/Spark tại **E1 snapshot**

E1 **không** có raw evidence ledger cho Bronze retry/outage, Spark
Bronze-to-Silver/Gold, historical query API, throughput hay scale-out benchmark. Các
mục này là **đang tích hợp / N/A — chưa đo**. Do đó báo cáo không tuyên bố HDFS thay
SQLite, API historical hoạt động hay hệ thống production-ready.

Trước khi cập nhật phần kết quả, evidence cần có theo thứ tự: DataNode/RF/block
location; Bronze receipt/hash cùng retry/outage; Spark input `hdfs://`, output schema
và counts; aggregate parity độc lập; history API; sau đó audit black-box/white-box.

---

# 6. Module 3 — Mô hình ETA toàn cục

## 6.1. Phạm vi model

`eta_model_trainer.py` tải partition của tất cả tuyến, huấn luyện và đánh giá một
model toàn cục, sau đó có evaluation theo route. Vì vậy Model-6 là **global model**.
Không có căn cứ gọi nó là tập model riêng từng tuyến; đặc biệt không có căn cứ nói
tuyến 02/27 đã train Model-6 riêng. [E1]

## 6.2. Artifact và temporal split

Metadata Model-6 là `data/models/eta_xgb_metadata_and_calibrator_r3_big.json`,
SHA-256 `2C49778CE1EAF79592B156EB0BF54D7C15E73B535094150932831575E649C35E`.
Pruned global model có SHA-256
`E7992FB52DD4FA6917726F5171DB5517D2EB5FB9944D336CDD7E49138736E688`; full global
model có SHA-256
`EB524DE9E2838880BC9D4CC4CE0BF8F8D77024665E36BBC70B99EBF0D3034EF2`. [E1]

Train window là 08/10/2026–01/11/2026 và held-out test window là
02/11/2026–07/11/2026. Một lần chạy mới phải dùng tag/output directory khác để không
ghi đè artifact đã gắn E1.

## 6.3. Kết quả Model-6 global

**Bảng 6.1 — Held-out metric của `6_XGB_Pruned_53Feat` global tại E1.**

| Test rows | Candidate / retained features | MAE | MedAE | RMSE | P90 AE | MAPE | R² | within 1 / 2 / 3 min |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 3.704.820 | 54 / 53 | 96,70 s | 46,69 s | 170,89 s | 244,58 s | 13,25% | 0,9774 | 56,37% / 74,88% / 84,24% |

Nguồn: [E1], Model-6 metadata artifact. Đây là metric global của snapshot. Bảng
per-route Model-6 và metric theo horizon là N/A — chưa export/review trong E1.

## 6.4. Phân rã lỗi Model-6 theo số đoạn trạm còn lại (E2)

E1 chỉ chứa các metric tổng hợp từ metadata model. Để trả lời sai số có ý nghĩa gì
trong các tình huống ETA khác nhau, một evaluator độc lập đã tạo prediction-level
ledger cho toàn bộ held-out split. Run E2 dùng Model-6 global, kiểm tra cứng cửa sổ
test `2026-11-01`--`2026-11-07`, chỉ chấp nhận `direction` là `go` hoặc `re`, kiểm tra
ETA thực dương, prediction hữu hạn và prediction không nhỏ hơn 5 giây. Không có hàng
nào bị loại: sáu bucket dưới đây cộng đúng 3.704.820 hàng. [E2]

**Bảng 6.2 — Model-6 global theo số đoạn trạm còn lại, E2.** `WAPE` là tổng sai số
tuyệt đối chia tổng ETA thực trong bucket; `≤120 s` là tỷ lệ dự báo có sai số tuyệt đối
không quá hai phút. Nguồn: `data/evaluation/eta_model6/20261110T160528Z_ae640eff/`
(`metrics_by_horizon.csv`, manifest và `run.log`).

| Số đoạn trạm còn lại | N | MAE (giây) | WAPE | Sai số ≤120 giây |
| --- | ---: | ---: | ---: | ---: |
| 1 | 863.984 | 23,74 | 23,14% | 97,57% |
| 2 | 124.490 | 41,05 | 15,57% | 94,24% |
| 3--5 | 962.160 | 60,94 | 12,74% | 88,49% |
| 6--10 | 191.932 | 100,80 | 10,02% | 72,84% |
| 11--15 | 735.276 | 124,62 | 8,90% | 62,92% |
| >15 | 826.978 | 201,90 | 7,21% | 42,60% |
| Toàn bộ | 3.704.820 | 97,77 | 8,79% | 74,67% |

MAE tăng từ 23,74 giây khi còn một đoạn trạm lên 201,90 giây khi còn trên 15 đoạn.
Đây là diễn giải trực tiếp nhất về rủi ro sai lệch theo horizon. Ngược lại, WAPE giảm
theo horizon vì ETA thực ở các bucket xa thường lớn hơn. Do WAPE có mẫu số là ETA thực,
việc WAPE giảm **không** chứng minh model dự báo tốt hơn ở xa; cần đọc nó cùng MAE và
coverage. Không được suy ra một hằng số “sai số mỗi trạm” bằng cách chia MAE cho số trạm.

Phân phối lỗi trên toàn bộ test E2 là: 56,12% có sai số không quá 60 giây, 74,67% không
quá 120 giây, 84,07% không quá 180 giây và 1,39% lớn hơn 600 giây. MdAE là 47,78 giây,
P90 absolute error 247,25 giây và WAPE 8,79%. Các hình `absolute_error_ecdf_by_horizon.png`
và `absolute_error_distribution_stacked_by_horizon.png` trong artifact E2 phải được
chèn vào bản dàn trang cuối: mỗi cột horizon trong hình stacked có tổng 100%, các mảng
màu là các dải sai số tuyệt đối. [E2]

E2 là một measurement run có ledger, hash, `run.log` và nghiệm thu độc lập white-box /
black-box. Giá trị MAE E2 (97,77 giây) không trùng metric metadata E1 (96,70 giây).
Báo cáo giữ cả hai giá trị với provenance riêng, không âm thầm thay E1 bằng E2; trước
khi nộp bản cuối, nhóm cần đối chiếu cấu hình prediction/calibration đã sinh hai phép đo
và ghi kết luận vào evidence snapshot mới.

## 6.5. Hai tuyến 02 và 27

**Bảng 6.3 — Evaluation per-route của Model-4 global; không phải Model-6 per-route.**

| Tuyến | Projected rows | Held-out N | Model-4 global XGB MAE | Model-4 calibrated MAE |
| --- | ---: | ---: | ---: | ---: |
| 02 | 253.626 | 158.756 | 89,54 s | 90,22 s |
| 27 | 252.554 | 167.383 | 91,03 s | 90,53 s |

Nguồn: [E1], SQLite queries và metadata model. Khoảng quan sát tuyến 02 là
08/10/2026 12:55:20–07/11/2026 13:53:15; tuyến 27 là
08/10/2026 12:55:27–07/11/2026 13:52:38 (UTC+07:00). Các con số không thể được
diễn giải như completion hay metric Model-6 của route riêng.

## 6.6. Hai kế hoạch hợp lệ

* **A — global model, per-route evaluation:** tạo manifest theo route gồm input/model/
  split hash, row count, metric, start/end UTC, wall time và exit code. Một route
  chỉ complete sau khi metric và hash được persist.
* **B — route-scoped model:** phải có specification và runner riêng, artifact
  directories tách biệt, checkpoint/resume và split nhất quán. Không thể dùng trainer
  global hiện tại rồi đổi nhãn thành train riêng.

Không dự đoán thời gian chạy job dài; thời lượng chỉ được công bố sau khi có đo thực.

---

# 7. Thực nghiệm và thảo luận

## 7.1. Protocol E1

E1 chạy tại workspace snapshot `cee5324f3cda08dcbe46ed35a7bf4a78ff6c177d` ngày
10/11/2026 (Asia/Ho_Chi_Minh). Ledger ghi lệnh inventory filesystem, SQLite counts,
Silver audit, split/model metadata và file hash. E1 là baseline reproducibility,
không phải benchmark đa máy.

## 7.2. Kết quả theo chuỗi dữ liệu

**Bảng 7.1 — Chứng cứ theo stage tại E1.**

| Chặng | Evidence có | Kết luận được phép | Không được suy ra |
| --- | --- | --- | --- |
| Ping → telemetry | 7.333.298 unique pings; 5.565.232 projected rows | artifact projection tồn tại | rejection rate upstream |
| Telemetry → Silver | audit 1.191 tệp, 5.565.232 rows, pass | local Silver audit pass | HDFS Silver |
| Gold/features → ETA | split, metadata/hash, held-out metrics | global Model-6 được đánh giá | Model-6 per-route |
| HDFS historical | design; không có E1 job log | đang tích hợp | HDFS/Spark/query hoàn chỉnh |

Nguồn: [E1]. Một stage chỉ được coi là hoàn thành khi có output và measurement của
chính stage đó; sự tồn tại code/design không đủ.

## 7.3. Diễn giải metric ETA

MAE 96,70 giây là sai số tuyệt đối trung bình trên 3.704.820 hàng held-out. [E1]
RMSE 170,89 giây lớn hơn MAE và P90 AE là 244,58 giây; điều này mô tả phân phối lỗi
có phần đuôi lớn ảnh hưởng mạnh tới squared error. Nó không giải thích nguyên nhân
outlier vì E1 chưa có error analysis theo horizon, traffic regime hoặc từng route.

Tỷ lệ within 1, 2 và 3 phút là 56,37%, 74,88% và 84,24%. [E1] Đây là các ngưỡng
dung sai bổ sung cho MAE/RMSE, không chứng minh chất lượng mọi tuyến hoặc mọi điều
kiện giao thông.

Phân rã E2 ở §6.4 bổ sung ngữ cảnh còn thiếu cho các metric này: gần điểm đến (một đoạn
trạm), sai số trung bình là 23,74 giây và 97,57% mẫu nằm trong ±120 giây; với trên 15
đoạn trạm, con số tương ứng là 201,90 giây và 42,60%. Đây là phân tích trên số đoạn trạm
thật `n_stations_ahead`, không phải quy đổi từ mét sang trạm. E2 vẫn chưa cho phép quy
nguyên nhân tail error cho kẹt xe, dữ liệu thiếu hay lỗi route projection; các giả thuyết
nhân quả đó cần feature/error audit riêng.

## 7.4. Hạn chế thực nghiệm

1. N/A: missingness per feature, train/validation rows theo route, reject reasons,
   Model-6 per-route/horizon metric, training runtime và serving latency.
2. Artifact public observation không phải census 24/7 của toàn bộ đội xe; E1 không có
   coverage measurement.
3. Local Parquet audit không là benchmark HDFS/Spark.
4. N/A: scale-out benchmark, ledgered DataNode-failure experiment, NameNode HA,
   enterprise security và SLA.

Các giới hạn này là kết quả có ý nghĩa: chúng xác định chính xác ranh giới những gì
đồ án có thể bảo vệ bằng số liệu.

---

# 8. Tái lập, giới hạn và đạo đức

## 8.1. Quy trình tái lập E1

Các lệnh sau chạy trong workspace có artifact E1. Lần tái đo phải lưu stdout/stderr
cùng run ID mới; không được thay E1 mà không đổi snapshot/date.

```powershell
git rev-parse HEAD
Get-FileHash data\models\eta_xgb_metadata_and_calibrator_r3_big.json -Algorithm SHA256
Get-ChildItem data\lakehouse -Recurse -File | Measure-Object Length -Sum
.\.venv\Scripts\python.exe scripts\audit_silver_lakehouse_purity.py
.\.venv\Scripts\python.exe module_3_bus_eta_prediction\step_3_3_machine_learning_models\eta_model_trainer.py
```

Lần chạy trainer mới phải đặt model tag/output directory để không ghi đè output đã
gắn E1. Khi HDFS có kết quả, evidence tối thiểu phải gồm `docker compose ps`,
`hdfs dfsadmin -report`, `hdfs fsck /bus-eta -files -blocks -locations`, upload
receipt/hash, Spark job log và independent aggregate query.

## 8.2. Dữ liệu và diễn giải có trách nhiệm

Repository làm việc với tuyến, xe, thời điểm và vị trí. Báo cáo không công bố dữ liệu
hành khách. Khi xuất artifact/log, nhóm cần kiểm tra API token, secret, đường dẫn máy
cá nhân và điều khoản nguồn dữ liệu trước khi tái phân phối.

ETA có thể có sai số lớn trên phần đuôi phân phối (P90 AE 244,58 giây tại E1), nên
metric không phải cam kết thời gian đến cho hành khách. Nếu phục vụ thật, cần freshness
indicator, uncertainty communication và drift monitoring; đây là yêu cầu tiếp theo,
chưa được đo ở E1.

---

# 9. Kết luận và kế hoạch

## 9.1. Kết luận

E1 xác nhận pipeline cục bộ có thể truy vết: 5.565.232 telemetry đã chiếu, local
Silver audit pass, và Model-6 global được đánh giá trên 3.704.820 held-out rows với
MAE 96,70 giây. [E1] Không có con số nào được diễn giải thành năng lực 24/7, citywide
hay production-ready.

Nhánh HDFS/Spark là phần hữu cơ cần thiết để đưa historical data tới distributed
storage/processing; tuy nhiên tại E1 nó vẫn đang tích hợp. Trình bày đúng trạng thái
này bảo toàn tính khoa học: đo trước, kết luận sau.

## 9.2. Thứ tự hoàn thiện

1. Bổ sung quality-flow và feature/split inventory còn thiếu.
2. Chọn global per-route evaluation hoặc route-scoped training trước khi chạy job dài.
3. Hoàn thiện HDFS Bronze retry/outage evidence, Spark Silver/Gold và history query.
4. Audit độc lập rồi tạo evidence snapshot mới trước khi thay bảng kết quả.

Code/design không tự tạo completion status; mỗi bước cần artifact, command, log và
measurement mới.

---

# Phụ lục A. Ledger evidence E1

Nguồn chính là
[`EVIDENCE.md`](evidence/2026-11-10_report_baseline/EVIDENCE.md). Tất cả số liệu
trong báo cáo dùng `[E1]`. Một update phải tạo `docs/evidence/<run-id>/`, giữ raw
stdout/stderr, commit, timezone, input/model hash và đơn vị đo.

# Phụ lục B. Data dictionary tối thiểu

| Thực thể / trường | Vai trò |
| --- | --- |
| `canonical_route_master` | master tuyến |
| `canonical_shape_master` | hình học tuyến |
| `canonical_station_master` | master trạm |
| `vehicle_unique_pings` | ping sau unique contract |
| `route_projected_telemetry` | telemetry có route geometry |
| `route_id`, `vehicle_id`, `route_code` | định danh nghiệp vụ |
| `s_bus_m` | tọa độ dọc tuyến theo contract |
| `cross_track_m` | lệch khỏi tuyến; E1 tối đa 35 m |
| `device_epoch_ms`, `ingested_at_epoch_ms` | thời điểm source/ingest historical |
| `event_id`, `source_window_id`, `provenance` | envelope truy vết HDFS dự kiến |

Schema chi tiết phải lấy từ code/artifact của snapshot chạy; bảng này không thay
schema migration.

# Phụ lục C. Evidence HDFS tối thiểu

| Claim | Evidence bắt buộc |
| --- | --- |
| Replication | `dfsadmin -report`, `fsck` có RF/block locations |
| Bronze ingest | spool receipt, SHA-256, HDFS path, byte/row count |
| Retry | same input không tạo logical duplicate; interruption log |
| Spark Silver/Gold | `hdfs://` input, output count/schema, job log |
| Historical query | endpoint result đối chiếu Spark SQL độc lập |
| Fault demo | DataNode loss/recovery trace; không gọi là NameNode HA |

# Phụ lục D. Checklist nộp bài

| Hạng mục | Người phụ trách | Trạng thái |
| --- | --- | --- |
| Bìa, xác nhận, danh sách nhóm | **[Điền]** | cần điền |
| Citation/bibliography | **[Điền]** | cần rà soát |
| Re-run evidence cuối | **[Điền]** | cần thực hiện trước nộp |
| HDFS evidence run | **[Điền]** | đang tích hợp |
| Quyết định global/per-route | **[Điền]** | đã xác định global; cần chốt evaluation plan |

# Phụ lục E. Evidence E2 — prediction-level ETA decomposition

Evidence E2 chỉ được coi là một phần của bản nộp sau khi commit
`codex/ml-result-decomposition` được tích hợp vào snapshot nộp bài. Artifact gốc là
`data/evaluation/eta_model6/20261110T160528Z_ae640eff/`, gồm prediction ledger,
manifest/hash, `run.log`, `metrics_by_horizon.csv`, `error_distribution_by_horizon.csv`
và ba hình. SPEC-32 quy định bucket, công thức, guard và điều kiện audit.

Lệnh tái kiểm tối thiểu là chạy evaluator được ghi trong `run.log`, rồi đối chiếu row
count, hash model/script, cửa sổ test, `rejection_counts`, tổng bucket và tổng phần trăm
mỗi horizon. Hai audit độc lập phải pass trước khi thay số liệu trong Bảng 6.2.

# Tài liệu tham khảo

**[E1]** Nhóm dự án. *Report evidence baseline — 2026-11-10*.
`docs/evidence/2026-11-10_report_baseline/EVIDENCE.md`, snapshot
`cee5324f3cda08dcbe46ed35a7bf4a78ff6c177d`.

**[E2]** Nhóm dự án. *Model-6 prediction-level result decomposition — 2026-11-10*.
`data/evaluation/eta_model6/20261110T160528Z_ae640eff/`; contract
`docs/specs/32_ETA_MODEL_RESULT_DECOMPOSITION_SPEC.md`. Artifact phải được merge vào
snapshot nộp bài trước khi dùng như evidence chính thức.

**[R1]** Apache Hadoop. *HDFS Architecture*. Apache Hadoop documentation.
https://hadoop.apache.org/docs/current/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html
(truy cập 10/11/2026).

**[R2]** Apache Spark. *Spark SQL & DataFrames*. Apache Spark documentation.
https://spark.apache.org/sql/ (truy cập 10/11/2026).

**[R3]** XGBoost Contributors. *XGBoost Documentation*.
https://xgboost.readthedocs.io/ (truy cập 10/11/2026).
