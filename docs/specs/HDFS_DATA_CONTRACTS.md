# Hợp đồng HDFS hiện hành

[Kiến trúc/trạng thái](../HDFS_README.md) · [Cách chạy](../HDFS_RUNBOOK.md). Hành vi thực thi nằm trong `step_2_4_hdfs_history/` và CLI được runbook dẫn.

## Bronze

- Pin dataset/revision/path; giữ nguyên byte crawler đã lưu, gồm bus/incidents/traffic legacy.
- `batch_id = sha256(canonical_json({dataset, path, content_sha256}))`, JSON UTF-8/sort keys/separator gọn. Cùng path/bytes ở revision khác thêm sighting; cùng path khác bytes tạo version mới.
- Raw: `/bus-eta/v1/bronze/hf_raw/category=<category>/sha256=<hash>/batch.jsonl`. Ledger: `/bus-eta/v1/_received/hf_batch/<batch_id>/manifest.json`, `revisions/<revision>.json`.
- Upload temp/rename, verify raw và metadata trước receipt. Bulk resume có thể bỏ nhóm đã có receipt; cần verifier đọc lại remote để kết luận hoàn tất. Lỗi giữ staging để retry.

## Silver

- Event time là `device_update_time`, capture time là `crawled_at`. Thiếu offset/field hợp lệ hoặc route chưa có reference đi reject; raw còn ở Bronze.
- Bus dùng `canonical_event_id` theo source/route/vehicle/event-time/tọa độ; capture/batch không tham gia. Dedup chọn capture sớm nhất, tie-break nội dung rồi batch ID; giữ event–batch lineage.
- Projection dùng boundary chung Module 1. Direction lấy mapping duy nhất route/station; thiếu/ambiguous dùng hint `0→go`, `1→re`, còn lại unknown. Reference route/station/shapes export read-only từ canonical SQLite, khóa bằng hash.
- Incidents loại exact duplicate observation, giữ JSON/geometry/null. Traffic chỉ Bronze. Bước domain local spatial join incidents thành facts.
- Snapshot khóa batch/hash/reference/code/policy. Reader chỉ dùng `/_published/history_snapshots/`; attempt dưới `/silver/history/_runs/` chưa public không được chọn.
- Hiện recompute tập batch đã chọn, gom route trong RAM; chưa incremental compute theo partition.

## Gold và release

Baseline/incident/feature algorithms chạy local từ cache Silver đã verify. Artifact giữ snapshot/reference/phạm vi ngày-tuyến/split/code/file hashes; lưu `/gold/eta_artifacts/<id>` với publication riêng.

Download vào pending, verify rồi rename thành release bất biến. Chỉ đổi pointer sau verify; refresh lỗi giữ bản tốt trước. SQLite/Parquet local hoạt động độc lập. Release thử nghiệm không tự thay DB/model web.

## Runtime và kiểm chứng

Compose có hai DataNode, Spark master và hai worker. WebHDFS dùng private network, DataNode không publish port. Repo mount read-only; staging/release mount ghi riêng. Spark image `apache/spark:3.5.4`, NumPy `1.24.4`.

Khi sửa pipeline, kiểm tra phần bị ảnh hưởng: hash/lineage/retry; dedup/late data/projection; run dở không public; query đối soát Silver; baseline/features cùng input/split; corruption bị từ chối và refresh lỗi giữ pointer. [Evidence](../evidence/README.md) ghi kết quả từng lượt; hợp đồng không tự chứng nhận PASS.
