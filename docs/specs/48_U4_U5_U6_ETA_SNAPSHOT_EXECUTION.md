# U4–U6: đưa snapshot lịch sử vào tác vụ ETA và chế độ offline

Trạng thái: đạt U4/U5/U6 trong phạm vi hai tuyến, hai ngày và bốn batch HF bổ sung, không phải hoàn tất migration toàn lịch sử/serving. Có exact domain parity, global-model prediction smoke, release offline, corruption/failed-refresh và replay toàn luồng. [Runbook](../HDFS_U456_RUNBOOK.md), [evidence](../evidence/hdfs_u456/README.md). Không ghi đè database/model vận hành; không sửa config, serving/web hoặc experiments của người dùng.

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
