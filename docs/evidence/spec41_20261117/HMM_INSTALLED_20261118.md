# HMM đã cài chung cho offline và serving — 18/11/2026

**Đã đổi code thực thi**, không chỉ giữ prototype trong scripts. Chưa nghiệm thu toàn bộ pipeline ML; các thiếu sót probe/incident không được che bằng kết quả phần chiếu.

## Thay đổi đã cài

- Kernel chung: `module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py`. `frenet.py` của serving chỉ còn re-export geometry tương thích; offline `project_points_to_shape` dùng cùng RouteHMM.
- OnlineFeatureExtractor cập nhật matcher theo từng xe/tuyến/chiều. Tốc độ ML, tốc độ hiển thị, lọc xe qua trạm và ETA dùng kết quả chiếu đã chuẩn bị, thay vì tự nearest độc lập. HMM sửa nhánh trong cửa sổ thì lịch sử tốc độ tương ứng được hiệu chỉnh lại.
- Metadata chiếu chỉ ở nội bộ DTO, không thêm trường kỹ thuật vào payload xe công khai. Trace có sự kiện reset để truy lại vòng đời.
- Khi near-terminal có hai quan sát dịch chuyển đủ rõ không phù hợp chiều đang theo dõi, xóa matcher/history/fleet liên quan và đánh dấu chờ chiều mới. Không khẳng định xe tiếp tục tới các trạm của chiều cũ. Tọa độ cache lặp không đủ để xác nhận đảo chiều.
- Khi nhận chiều mới với timestamp mới hơn, xóa lịch sử hai chiều, macro EMA/seed và passed-station/cache của lượt cũ; khởi tạo mới. Gói chiều cũ đến muộn không đảo trạng thái trở lại. Gap lớn và terminal wrap cũng khởi tạo lại theo policy.
- Offline không dùng gói tương lai để đổi nhãn hướng của gói quá khứ. Đổi chiều được coi là ranh lịch sử. Hai fixture cũ đã được sửa để cung cấp xe có ID/chiều hợp lệ cho mỗi chiều; kiểm tra cache và nguyên tắc không đưa xe đã qua trở lại vẫn giữ.
- Fingerprint snapshot HDFS bổ sung file kernel mới. Không tái sử dụng snapshot cũ dưới danh nghĩa policy mới. Chưa chạy lại toàn bộ lịch sử, chưa đổi active release hay model gốc.

## Kiểm chứng bằng dữ liệu live đã thu

### Offline và serving có cùng phép chiếu

Replay cùng chuỗi chuẩn hóa theo thứ tự nhận, cùng các đoạn liên tục theo chiều: **5.264 quan sát / 37 xe–tuyến / 46 đoạn chiều**, **0 khác biệt** giữa adapter offline và matcher serving. Có 5.106 kết quả khớp; phần không khớp cũng nhất quán. Đó là parity của phép chiếu trên cùng input, chưa chứng minh mọi adapter nguồn xác định chiều giống nhau.

Số quan sát khác phép thử 5.266 trước đó vì lần này lọc timestamp cũ trên cùng xe/tuyến trước khi chia chiều; tránh coi hai dòng cùng xe, cùng thời điểm ở hai chiều là hai bằng chứng mới.

Report: [installed_projection_parity.json](installed_projection_parity.json).

### Đi qua service và HTTP thực

Nạp 3.600 snapshot GPS đã ghi và replay **1.440 request station-eta bằng TestClient**. Thay upstream transport và clock bằng dữ liệu/giờ đã thu; matcher, macro speed, feature producer, bộ lọc, model/calibrator và HTTP serialization là code production. Đây là replay tại ranh DTO GPS đã hợp nhất, không phải thử lại việc giải mã/hợp nhất packet upstream, không có traffic Internet mới.

- 1.440 response HTTP 200; 4.976 forecast ML, so với 4.990 forecast gốc.
- 14 forecast cũ bị từ chối vì không có chuyển tiếp hợp lý. Không tạo forecast thay thế để làm đủ số; chưa xác nhận vật lý từng trường hợp bị loại.
- Xe 8837283, trạm thứ 23: hai gói từng nhảy +78,38 giây nay **−0,6 giây**. Giữ được xe trong kết quả; không xử lý bằng cách làm mất riêng ca cần kiểm tra.
- Kiểm tra hết **69 forecast** còn lại của xe/trạm này: mức tăng ETA lớn nhất **6,8 giây**, không đẩy cú nhảy 80 giây sang vài gói sau.
- Ca xe 231970 gần bến: trace xác nhận `direction_change_pending` lúc query 19:19:52,328, generation 1; nhận chiều 0 lúc 19:21:02,362, generation 2, khởi tạo mới. Trong khoảng nguồn chưa chuyển chiều, không tiếp tục dự báo theo chuỗi trạm chiều cũ. Không tuyên bố đã rút ngắn độ trễ xác nhận chiều của upstream.

Report: [installed_http_replay.json](installed_http_replay.json). Toàn bộ request/response replay ở `runtime/installed_hmm_replay_20261118_final/responses.jsonl`; giữ nguyên raw gốc và các lần replay trước.

## Những giới hạn vẫn còn

- Chưa có ground truth ngoại nghiệp về làn/nhánh và dừng đỗ. Không suy ra ETA chính xác hơn chỉ từ parity hoặc chuỗi mượt hơn.
- Model ứng viên giữ nguyên; chưa rebuild Silver/feature store hoặc train lại. Chất lượng ML sau thay policy vẫn cần đánh giá.
- Probe thời gian xe trước chưa triển khai; incident live chưa được xác nhận cập nhật. Acceptance probe vẫn thất bại như đã công bố.
- Lần chạy toàn bộ `pytest tests`: **2 failed, 192 passed, 11 skipped**. Hai lỗi là acceptance probe và test DOM `test_r3_hostile_provider_text_renders_as_literal_dom_text` không thấy payload trong DOM. Chưa xác định xong nguyên nhân test browser, không sửa frontend và không skip test để làm xanh. 11 test HDFS live opt-in không chạy trong lần này. Không tuyên bố bộ test tổng thể đạt.

Test station-state cũ dùng `__new__` và shape giả lập để cô lập pass guard; đã bổ sung adapter projection tường minh trong fixture này. Chúng không phải bằng chứng HMM hoạt động. Bằng chứng HMM là raw parity/HTTP replay nêu trên cùng các kiểm tra geometry/lifecycle riêng.

## Chạy lại

```powershell
python scripts/verify_installed_projection_parity.py --session runtime/eta_live_session_20261117_raw --output runtime/projection_parity_recheck.json
python scripts/verify_installed_hmm_replay.py --session runtime/eta_live_session_20261117_raw --output runtime/installed_http_recheck
python -m pytest tests -q -p no:cacheprovider
```

Bản nguồn trước thay đổi và hash giữ tại `runtime/projection_pre_install_20261118/`. Không ghi đè dữ liệu/raw/model hiện hữu.
