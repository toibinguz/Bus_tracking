# Phần đầu SPEC-41: nguồn dữ liệu phục vụ demo

## Kết quả và phạm vi

- Web nhận `-ReleasePointer` (hoặc biến môi trường `ETA_RELEASE_POINTER`) tại
  startup; đọc SQLite baseline và Parquet incidents trong release đã verify.
  Catalog/geometry local chỉ được ghép khi route ID, station/order/distance và
  shape khớp chính xác với release trên các tuyến có baseline.
- `-LocalData` bỏ lựa chọn release và dùng dữ liệu local hiện hữu để test nhanh.
  Request không refresh/download, không query HDFS. Đổi active pointer cần restart.
- Release hiện chỉ dùng baseline ETA: chưa chứng minh model/calibrator/mapping
  được ghép đúng. Local vẫn dùng model ứng viên; không có tuyên bố accuracy mới.
- Health báo source/artifact/snapshot/phạm vi baseline/trạng thái model; health
  không gọi kiểm tra upstream. Nhãn chính đã phản ánh GPS BusMap/TimBus.

## Kiểm chứng

- 7 test mới trong `tests/test_eta_release_serving.py`: HTTP lấy baseline 100 giây
  từ release thay vì 999 giây trong operational DB; cấm nạp model rời và gọi
  HDFS/process ngoài; pin nguồn đến restart; từ chối sai geometry, route ID,
  corruption và pointer. Cùng các test trạng thái/release hiện có: **27 passed**.
- Suite local/web: **137 passed, 11 skipped**, 26,77 giây. Các test HTTP facade
  và Chrome cũng thuộc suite này. Test JS async: **7 passed**.
- Lần cố bật 11 test live history API thất bại vì `127.0.0.1:8090` từ chối kết
  nối (WinError 10061); không tính là đạt, không tự khởi động cụm. Chưa kiểm
  chứng lại query HDFS trong phiên này. Đây cũng là môi trường mà demo release
  thực bên dưới vẫn khởi động và phục vụ catalog/geometry được.
- Launcher thật trên cổng riêng, stdin đóng: **3,484 giây cho toàn phiên gồm
  startup, HTTP catalog/shape/stations và shutdown**, graceful, không cưỡng bức,
  identity/artifact không đổi. Không dùng số này làm latency ETA hay SLA.
  Kết quả rút gọn: [JSON vòng đời](eta_release_serving_20261117.json).
- Chưa tái hiện prompt lưu dữ liệu người dùng báo; chưa nghiệm thu B1 cho mọi
  entrypoint. Chưa thu GPS/ETA live hoặc đánh giá nhãn/sai số.

## Lệnh tái lập

```powershell
.\run_demo.ps1 -ReleasePointer runtime/eta_full_history_active.json -NoBrowser
.\run_demo.ps1 -LocalData -NoBrowser
.\.venv\Scripts\python.exe -m pytest tests/test_eta_release_serving.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe scripts/verify_eta_demo_release.py --pointer runtime/eta_full_history_active.json --output runtime/eta_lifecycle_next
.\.venv\Scripts\python.exe scripts/audit_eta_model_artifacts.py --output runtime/model_inventory_next.json
```

Hai lệnh launcher là hai lựa chọn; dừng phiên trước khi chạy phiên kế tiếp.
Verifier yêu cầu output mới. Release/pointer trong `runtime/` là dữ liệu máy
hiện tại, cần dựng/tải theo runbook trên máy khác; không commit DB/model mới.
Inventory ML chỉ định danh artifact, không phải chứng nhận mô hình.
