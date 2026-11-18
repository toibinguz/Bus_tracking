# Thiếu kiểm chứng nội dung feature — xác nhận ngày 18/11/2026

**Chưa nghiệm thu pipeline feature live.** Những lần báo 35 test focused đạt chỉ nói về các phạm vi test đã chạy; chúng không bao phủ việc toàn bộ 54 feature nhận được thông tin thực. Không dùng các kết quả đó để kết luận pipeline ML live hoàn thiện.

## 1. Xe trước đi qua đoạn đường: serving chưa triển khai

Trong `OnlineFeatureExtractor.build_features`, bốn giá trị được gán trực tiếp:

```text
recent_corridor_tt_sum_sec        = baseline_eta_p50_sec
recent_seg_coverage_ratio         = 0
recent_corridor_congestion_ratio  = 1
recent_next_seg_congestion_ratio  = 1
```

Không có logic ghi nhận xe qua hai đầu đoạn, tính thời gian hoàn thành đoạn và cập nhật cửa sổ probe. Cả 4.990 forecast trong raw đều nhận các giá trị thay thế này. Khác với serving, builder offline có `seg_completion_events`, `latest_seg_tt`, `latest_seg_epoch`, cập nhật các sự kiện hoàn thành tới thời điểm hiện tại rồi tính feature.

Snapshot vị trí/tốc độ của xe dẫn trong nhóm fleet là một luồng khác; có nhóm fleet không chứng minh có thời gian xe trước thực sự đi hết đoạn.

## 2. Incident: có tính feature, nhưng dữ liệu phiên live không còn hiệu lực

`IncidentsProvider` đọc Parquet theo tuyến và cache trong RAM. `_incident_features` lọc chiều, hiệu lực thời gian, phần đường phía trước và tính count/delay/magnitude/độ dài chồng lấn. Vì vậy kết luận “không có dòng logic incident nào” không đúng cho phần tính feature.

Tuy nhiên dữ liệu đóng băng dùng trong phiên raw ngày 17/11:

| Tuyến | Record incident trong partition | Thời điểm kết thúc lớn nhất, UTC | Có hiệu lực tại đầu phiên |
|---|---:|---|---:|
| 02 | 23.386 | 2026-11-07 07:51:02 | 0 |
| 27 | 30.941 | 2026-11-07 07:51:02 | 0 |

Phiên raw thu packet BusMap/TimBus, không thu packet TomTom live. Trường incident bằng 0 không chứng minh có nguồn incident hiện tại hoặc đường không có sự cố. Provider còn trả kết quả rỗng khi thiếu partition/lỗi đọc, rồi cache kết quả; feature không phân biệt được “không có sự cố” với “nguồn thiếu/hỏng/cũ”. Cache cố định có thể phù hợp release được pin; nó không tự cung cấp luồng incident mới cho demo live.

## 3. Vì sao các test trước không phát hiện?

- Test release xác nhận đọc đúng artifact/baseline, không xác nhận nguồn incident live có dữ liệu hiệu lực.
- Test runtime xác nhận dự báo/replay từ vector cho trước; producer điền default thì model vẫn có thể dự báo và replay khớp.
- Test trace, cache, hình học và HTTP có mục tiêu riêng, không yêu cầu xe trước đã hoàn thành đoạn phải làm probe thay đổi.
- Nhiều input đã thu không chứa incident hiệu lực; replay lại chúng chỉ tiếp tục xác nhận vector zero.

Đây là thiếu acceptance về ý nghĩa và nguồn gốc dữ liệu, không phải bằng chứng mọi test dùng mock đều vô ích. Sai ở chỗ dùng kết quả kiểm tra kỹ thuật để diễn giải quá phạm vi.

## 4. Phép kiểm tra bổ sung đã làm lộ phần thiếu

File `tests/acceptance/test_eta_live_information_contract.py` dùng SQLite/Parquet thật và các class DataAccess/IncidentsProvider/OnlineFeatureExtractor thật. GPS và incident là **fixture tổng hợp có chủ ý, không phải raw observed**, để có kết quả tính tay độc lập; không mock hoặc thay hàm tính feature.

- Xe trước qua s=100 tại t=1001, qua s=200 tại t=1011: đoạn mất 10 giây, baseline 20 giây. Xe sau còn nửa đoạn phải có probe coverage 1, ratio 0,5 và thời gian probe còn lại 5 giây. **Test thất bại:** serving vẫn trả coverage 0, ratio 1, thời gian 10 giây.
- Incident Parquet đang hiệu lực, cùng chiều và phủ toàn bộ phần đường còn lại: delay 60 giây phải đi vào feature; hết hiệu lực phải về 0. **Test qua:** xác nhận phần đọc/tính feature có hoạt động với input phù hợp, không xác nhận TomTom live được kết nối/cập nhật.

Kết quả **1 failed, 1 passed**. Giữ test probe ở trạng thái thất bại, không `xfail`, không sửa expected theo default. Log: `runtime/eta_live_information_acceptance_20261118.log`.

## 5. Điều kiện nghiệm thu còn thiếu

1. Producer probe phải đi từ chuỗi GPS qua trạm tới thời gian hoàn thành đoạn, không nhìn tương lai, không dùng dữ liệu quá hạn, và có test expiry/thiếu bracket/đổi lượt/xe ego.
2. Luồng incident phải xác định nguồn, thời điểm cập nhật/phạm vi phủ; phân biệt thiếu dữ liệu với xác nhận không có sự cố. Kiểm tra xuyên suốt từ incident đầu vào tới vector ML, ngoài test riêng phép tính.
3. Mỗi nhóm feature phải có ca kích hoạt với kết quả độc lập, ca không được kích hoạt, và bằng chứng nguồn thực khi tuyên bố chạy live. “Đủ khóa/không NaN/replay khớp” không đủ.

Chưa sửa producer hoặc tự bật crawler TomTom trong lần rà này. Sửa phép chiếu sẽ không tự hoàn thiện các luồng thông tin còn thiếu.
