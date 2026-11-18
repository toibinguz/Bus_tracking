# U2 — Kết quả nhận batch HF vào HDFS Bronze

Ngày kiểm chứng: 2026-11-12. Dataset/revision và hai source batch giữ nguyên theo `docs/evidence/hdfs_u1/hf_inspection.json`.

## Những gì đã chạy thực tế

1. `hf_hdfs_ingest.py stage` với revision `f2e7378002113cb548e194f2e8bd11c97a1b94d9` và hai path U1: exit 0. Bus: 1.990.612 byte; incidents: 186.839 byte. Lệnh đầy đủ trong SPEC-46.
2. Upload với `--failpoint after_raw`: exit 1, lỗi chủ động `injected interruption after raw upload`; chạy lại không failpoint: exit 0, cả hai batch có manifest/receipt verified. Điểm lỗi này kiểm chứng ngắt sau ghi raw hoàn tất, chưa phải kill tiến trình giữa từng byte upload.
3. `verify_hf_bronze_integration.py`: exit 0. Script tạo staging recovery riêng từ đúng byte nguồn, dừng NameNode thật rồi khởi động lại trong finally; không xóa batch, không đổi byte và không ghi lên HF.

| Tình huống | Kết quả |
| --- | --- |
| NameNode dừng | upload exit 1; staging giữ nguyên, không có receipt mới |
| Ngắt trước local receipt | exit 1 có chủ đích; không có receipt recovery |
| Nhận lại sau lỗi | exit 0; hai receipt verified |
| Nhận lặp | exit 0; cả hai `already_received=true` |

Thời gian và batch ID nguyên bản: [result.json](result.json). Log riêng: [outage](actual_outage.txt), [before receipt](before_receipt.txt), [recovered](recovered.txt), [repeated](repeated.txt). Lượt kiểm chứng có sẵn byte object từ lần nhận ban đầu; `already_received=true` ở recovery phản ánh đúng ledger đã có, không phải tạo batch mới. Việc tạo batch lần đầu đã chạy ở bước 2.

## Đối soát hash ngoài receiver

Đã chạy `docker compose -f docker-compose.hdfs.yml exec -T namenode sh -c 'hdfs dfs -cat <hdfs_raw_path> | sha256sum'` cho từng object, exit 0. Kết quả trùng hash nguồn U1:

```text
bus:       fc0d7ee1b9eca673ef4d02cd22a2f8c00ac2400b6079f479d1354728d5f8766e
incidents: 9529bff97b7b455ee3b8cc052b37363fb018c2cbb05a1abf90534fd740421e8d
```

`hdfs_raw_path` đầy đủ nằm trong manifest/descriptor và được xác định bởi hash/category theo SPEC-45. Receiver còn đọc lại byte raw/metadata khi nhận lặp, không chỉ dựa vào receipt trên host.

## Kiểm thử hồi quy

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_hf_bronze.py tests/test_hf_storage_inspection.py tests/test_hdfs_contract.py tests/test_hdfs_p2_transform.py tests/test_hdfs_history_query.py -q -p no:cacheprovider
```

29 passed in 1.59s. Trong đó các test U2 mới kiểm tra cùng path/bytes mới, revision mới/identity cũ, payload hỏng, remote corruption dù có receipt local, outage, lost-create-ack và hai failpoint. Version thay đổi và lost-ack được kiểm tra bằng store giả lập; chưa diễn tập nhiều importer chạy đồng thời. Không giả mạo revision hoặc sửa batch HF thật để gọi là dữ liệu quan sát.

NameNode đã khởi động lại. Chưa thay đổi source Silver/API/ETA, crawler hoặc model. Chưa triển khai event-level dedup, cumulative Silver hay nhận toàn bộ lịch sử; đó là U3 và các bước sau.
