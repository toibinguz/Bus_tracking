# Thiết kế thống nhất pipeline dữ liệu giữa local và production

**Trạng thái:** Thiết kế cuối để triển khai · **Ngày:** 28/11/2026

Tài liệu này là căn cứ triển khai và nghiệm thu sau khi xem xét [phản biện của Gemini](pipeline_valid.md).

## 1. Quyết định và phạm vi

Local và production phải chạy **một pipeline nghiệp vụ duy nhất**. Một nơi trong mã nguồn định nghĩa thứ tự các bước, quan hệ đầu vào–đầu ra và mọi quy tắc có thể làm thay đổi dữ liệu. Máy dev chạy trực tiếp, không cần Docker, HDFS hoặc Spark cluster. Production dùng Spark để phân phối công việc và HDFS để lưu dữ liệu.

Phạm vi bắt đầu từ các batch raw đã thu thập, bao gồm Silver telemetry, dữ liệu sự cố, Gold baseline, Gold features và bước nạp baseline vào SQLite. Crawler, huấn luyện mô hình từ Gold features và API ETA trực tuyến nằm ngoài phạm vi thay đổi. Tài liệu này là hợp đồng cho lần triển khai tới. Việc xác minh tương đương dữ liệu sẽ thực hiện riêng sau triển khai.

## 2. Một điểm vào nghiệp vụ

Hai CLI gọi cùng điểm vào logic `run_pipeline(spec, adapter)`. Bộ điều phối chung phân giải cấu hình, chọn các bước theo quan hệ phụ thuộc và cố định phiên bản đầu vào. Mỗi bước có một hợp đồng cụ thể để adapter thực thi trên dữ liệu vật lý của mình. Tránh xây một framework mô phỏng DataFrame/RDD hoặc truyền đối tượng điều phối sang Spark worker.

| Thành phần | Trách nhiệm |
|---|---|
| Pipeline chung | Xác định bước nào chạy trước, dữ liệu phụ thuộc, schema logic, quy tắc lọc, khóa nhóm, thứ tự sắp xếp, hàm biến đổi và điều kiện công bố kết quả. |
| `spec` | Khai báo sản phẩm cần tạo, phạm vi tuyến/ngày, múi giờ, cutoff baseline, cửa sổ train/validation/test, nhịp dự báo và tham chiếu đầu vào. Giá trị mặc định nghiệp vụ được định nghĩa một lần và được ghi lại sau khi áp dụng. |
| Adapter local | Đọc JSONL/Parquet, sắp xếp trên đĩa khi cần, phân việc cho tiến trình, ghi Parquet và chuyển manifest bằng `os.replace` trên cùng filesystem. |
| Adapter Spark | Đọc HDFS, áp dụng khóa và điều kiện của core qua Spark SQL/RDD, dùng shuffle, broadcast hoặc cogroup, gọi hàm core trên executor và chuyển manifest bằng atomic rename của HDFS. |
| Đồng bộ serving | Cùng một hàm nạp bản Gold đã chọn vào SQLite cho cả hai nguồn. Chỉ phần mở các part Parquet phụ thuộc nơi lưu. |

**Ranh giới mã nguồn.** Đặt `PipelineSpec`, điều phối và các điểm gọi Silver, incidents, baseline, features trong `modules/lakehouse/pipeline/`. Core tái sử dụng các mô-đun nghiệp vụ thuần sẵn có của repo. Core phải import và chạy trên Python 3.8 của môi trường Spark mục tiêu với các phụ thuộc tính toán đã có (NumPy, Shapely, native bridge). Core không được kéo theo PySpark, pandas, PyArrow, Docker CLI hay kết nối SQLite, kể cả qua import gián tiếp. Hàm chạy trên worker được khai báo ở cấp module; tham số chỉ gồm dữ liệu và cấu hình tuần tự hóa được. Adapter có thể đẩy bộ lọc xuống Parquet/Spark nếu vẫn bảo toàn ngữ nghĩa và thứ tự xử lý do core quy định.

Local có thể chạy thử hai tuyến hoặc một ngày bằng `spec` tường minh. Với cùng `spec`, hai CLI phải chọn cùng tập dữ liệu. Số worker, giới hạn RAM và đường dẫn lưu trữ là cấu hình môi trường. Job Silver, baseline hoặc features có thể chạy riêng để retry bằng cách gọi lại đúng bước của pipeline chung với đầu vào đã xác định.

## 3. Hợp đồng của từng bước

| Bước và đầu vào | Quyết định thuộc mã nguồn chung | Đầu ra logic |
|---|---|---|
| Chuẩn hóa batch raw | Schema, trường bắt buộc, múi giờ, thời điểm quan sát và thu thập, cách tạo định danh, điều kiện nhận hoặc loại và mã lý do. | Sự kiện chuẩn hóa hoặc bản ghi bị loại có thể truy về nguồn. |
| Sự kiện xe + reference tuyến/trạm | Khử trùng trên toàn bộ tập batch đã chọn, chọn bản ghi thắng bằng thứ tự xác định, nhóm theo tuyến và xe, sắp theo thời điểm quan sát với khóa phụ ổn định, cắt phiên và chiếu vị trí lên tuyến. | Silver telemetry, nguồn gốc sự kiện và kết quả loại khi chiếu. |
| Quan sát sự cố + reference | Nhận diện cùng sự cố, xử lý quan sát kế tiếp, dựng khoảng hiệu lực và chiếu lên đoạn tuyến. Khi chọn cửa sổ, giữ cả sự cố bắt đầu trước cửa sổ nhưng còn hiệu lực bên trong. | Khoảng ảnh hưởng theo tuyến, chiều và thời gian. |
| Silver telemetry + reference + cutoff | Xác định tập tuyến, chia chuyến, nội suy thời điểm qua trạm, lọc mẫu, tính thống kê và phân tầng chất lượng. | Gold baseline theo tuyến, chiều, đoạn trạm và khung giờ. |
| Silver + khoảng ảnh hưởng sự cố + bản Gold baseline cụ thể | Dùng cùng bảng ánh xạ chỉ số tuyến, trạng thái đoàn xe, nhịp dự báo, logic thời gian, nhãn, split, thứ tự và kiểu cột. | Gold features kèm định danh chính xác của baseline đã dùng. |
| Bản Gold baseline đã công bố + dữ liệu tĩnh | Dùng cùng schema serving, kiểm tra số dòng và lưu nguồn của bản baseline đã nạp. | SQLite và manifest truy được về bản Gold tương ứng. |

Hai trường hợp minh họa ranh giới này:

- Hai quan sát liên tiếp của cùng một xe nằm ở hai file hai bên nửa đêm vẫn phải được đưa vào cùng phép xét cắt phiên. Tương tự, một sự kiện xuất hiện trong hai batch vẫn chỉ được tính một lần theo quy tắc dedup.
- Khi chỉ trích xuất features cho tuyến `02`, chỉ số của tuyến phải lấy từ danh mục của bản baseline đầu vào. Việc lọc xuống một tuyến không được đánh lại chỉ số.

**Quy tắc giao dữ liệu cho core**

- Cả hai entry point mặc định dùng danh mục tuyến hoạt động từ cùng bản cấu hình đã cố định và giới hạn ngày chuẩn từ `CANONICAL_START_DATE`. Ghi danh sách mã tuyến đã phân giải vào manifest; số lượng 48 tuyến hiện tại không phải hằng số nghiệp vụ. Chế độ mọi tuyến và lựa chọn tuyến con phải biểu diễn được bằng cùng `spec`. Phân biệt phạm vi dữ liệu để tính trạng thái với phạm vi đầu ra: bộ lọc ngày của đầu ra Silver áp dụng sau chiếu; không loại sớm quan sát cần cho phiên đi qua biên.
- Bus được gom toàn cục theo `event_id` trong tập batch đầu vào. Dùng cùng hàm merge hiện có: chọn bản ghi nhỏ nhất theo `(captured_ms, raw_json, batch_id)`, hợp nhất và sắp danh sách batch nguồn. Định danh batch logic phải dùng cùng quy ước ở hai nguồn, độc lập với đường dẫn local/HDFS. Sau dedup, nhóm theo `(route_id, vehicle_id)`, sắp theo `(observed_ms, event_id)`. Tách phiên khi khoảng cách **lớn hơn** `STALE_DELTA_T_MAX_SEC`; trường hợp bằng ngưỡng vẫn cùng phiên.
- Incidents được chọn theo hai bước. Trước tiên tìm các `incident_id` có quan sát trong cửa sổ và khoảng lùi `max(DEFAULT_TTL_SEC, MAX_BATCH_GAP_SEC)`. Sau đó lấy lịch sử của các ID này trong snapshot để core dựng hình học và khoảng hiệu lực, rồi lọc các khoảng giao cửa sổ. Một quan sát cũ hơn khoảng lùi vẫn có thể chứa hình học đầu tiên cần dùng.
- Baseline xác định danh mục tuyến cần xuất trước khi lọc mẫu fit theo `dt <= fit_end_date`; tuyến thiếu mẫu fit đi qua cùng quy tắc fallback. Features nhóm telemetry và khoảng sự cố theo `route_code`. Chỉ số tuyến lấy từ danh mục **thực sự có trong bản Gold baseline đã cố định**, trước khi lọc tập tuyến chạy features.

**Bộ nhớ trên máy dev.** Pass 1 đọc streaming, chuẩn hóa từng bản ghi và ghi trung gian vào thư mục tạm riêng của lần chạy. Pass 2 dùng external sort/merge hoặc chỉ mục trên đĩa để gom toàn bộ sự kiện cùng ID, sau đó cấp sự kiện đúng thứ tự cho core theo xe. Có thể chia bucket theo tuyến để tăng song song khi khóa định danh bảo đảm các bản trùng cùng bucket. Không giả định một tuyến vừa RAM: kích thước file nén hoặc JSONL không phải giới hạn RAM sau giải mã. Giới hạn số worker và kích thước lô là cấu hình máy; worker chỉ dọn vùng staging của chính lần chạy trong `finally`. Với kernel thực sự cần trọn một phiên hoặc tuyến, kiểm tra giới hạn tài nguyên và báo lỗi trước khi công bố.

## 4. Các bất biến khi thực thi

1. **Độc lập với cách chia việc.** Đổi thứ tự file, kích thước batch, số partition hoặc số worker phải giữ nguyên sự kiện được chọn, phiên xe và giá trị đầu ra. Pipeline quy định khóa và phạm vi xử lý. Executor chịu trách nhiệm đưa đủ dữ liệu theo đúng thứ tự đến hàm chung.
2. **Bảo toàn dữ liệu khi thiếu tài nguyên.** Local có thể sắp xếp hoặc lưu trung gian trên đĩa. Nếu không đủ tài nguyên, bước phải báo lỗi trước khi công bố. Cấm tự bỏ bản ghi, cắt phiên hoặc rút ngắn lịch sử để chạy tiếp.
3. **Một đường gọi cho kernel.** C++ native và Python fallback đi qua cùng wrapper. Wrapper chịu trách nhiệm chuẩn bị đầu vào, truyền tham số nghiệp vụ và diễn giải kết quả. Manifest ghi kernel thực tế đã dùng.
4. **Cố định đầu vào của lần chạy.** Mỗi bước phân giải phiên bản đầu vào một lần. Nếu baseline mới được công bố trong lúc job features đang chạy, job hoàn tất bằng baseline đã chọn ban đầu.
5. **Công bố an toàn.** Mỗi lần build ghi vào vị trí riêng. Sau khi kiểm tra schema và số dòng, adapter mới chuyển tham chiếu đang công bố bằng thao tác nguyên tử phù hợp với môi trường. Bản cũ còn đọc được nếu build mới lỗi hoặc bị ngắt. Quy tắc này áp dụng cả khi thay SQLite serving.

## 5. Truy xuất nguồn gốc

Manifest phải đủ để trả lời: “Kết quả này được tính từ dữ liệu nào, bằng quy tắc nào?” Với mỗi sản phẩm, lưu các thông tin áp dụng cho bước đó:

- Danh sách batch hoặc fingerprint bao phủ nội dung của toàn bộ tập raw đã chọn; phiên bản reference tuyến/trạm.
- `spec` hiệu lực sau khi áp dụng giá trị mặc định; phiên bản logic và kernel thực tế.
- Định danh các sản phẩm đầu vào, định danh bản build đầu ra, schema và số dòng đã kiểm tra.
- Gold features ghi `baseline_build_id`. SQLite ghi nguồn, `build_id` của Gold và `snapshot_id` khi nguồn có snapshot. Đầu vào local vẫn phải định danh được qua manifest hoặc fingerprint.

## 6. Tiêu chí nghiệm thu

**Về cấu trúc:** thay đổi quy tắc cắt phiên, khử trùng, cutoff, ánh xạ tuyến hoặc tạo nhãn chỉ cần sửa ở một nơi. Kiểm tra từ cả hai CLI phải lần được đến cùng hàm nghiệp vụ. Việc hai pipeline độc lập tình cờ cho kết quả giống nhau trên một bộ mẫu chưa đáp ứng tiêu chí này.

**Về dữ liệu:** đợt xác minh sau triển khai phải đi qua hai entry point thật với cùng raw, reference và `spec`. Đối chiếu từng bước từ sự kiện nhận/loại và lý do, nguồn gốc, phiên, Silver đến baseline và features. Bộ mẫu phải có bản ghi trùng xuyên batch, chuyến qua nửa đêm, sự cố vắt qua đầu cửa sổ và lần chạy chỉ chọn một tuyến. Chạy lại sau khi đổi cách chia file, đảo thứ tự đọc và đổi số partition.

**Quy tắc so sánh:** định danh nghiệp vụ, khóa, số dòng, lý do loại, nhãn rời rạc, split, `quality_tier` và `route_id_idx` phải khớp chính xác. So sánh theo khóa ổn định và kiểm tra cả vị trí giá trị thiếu. Tọa độ quan sát được sao chép từ raw phải khớp chính xác. Với giá trị tính toán, ngưỡng tuyệt đối tối đa cho tọa độ chiếu là `1e-5` độ, khoảng cách Frenet là `1e-5` mét, thống kê thời gian baseline là `0,05` giây. Áp dụng theo đơn vị của từng cột. Các cột còn lại mặc định so chính xác; mọi ngoại lệ cần được ghi trong bảng dung sai trước khi chạy đối chiếu. Dung sai không được che chênh lệch làm đổi phiên, tier, split hoặc nhãn rời rạc.

Tách phép thử **local so với Spark với cùng kernel** và **native so với fallback với cùng đầu vào**. Phép thử thứ nhất yêu cầu manifest xác nhận đúng cùng kernel. Phép thử thứ hai yêu cầu ghi chính xác hai kernel đã thực thi và giữ cùng tiêu chí đầu ra. Tên file, số part, đường dẫn vật lý, ID riêng của lần build và thời gian chạy được phép khác.

**Về phục hồi:** thử ngắt build trước khi công bố, chạy lại cùng snapshot với phạm vi tuyến khác và công bố baseline mới trong lúc features đang chạy. Bản đã công bố phải còn đọc được; mỗi đầu ra phải trỏ đúng phiên bản thực sự đã dùng.

## 7. Thứ tự triển khai và bàn giao

1. **Cố định hợp đồng.** Lập bản đồ từ các CLI đang dùng đến hàm nghiệp vụ hiện tại. Đưa mặc định, schema, khóa nhóm, manifest, bộ điều phối và quy tắc xác định batch vào core. Giữ các CLI hiện hữu làm điểm vào tương thích.
2. **Chuyển raw → Silver và incidents trước.** Cả hai adapter gọi cùng normalize, merge, chia phiên và chiếu. Local bổ sung sắp xếp trên đĩa; Spark giữ phân tán. Không còn đường chạy tự kết thúc phiên khi hết file ngày.
3. **Chuyển Gold và serving.** Dùng chung hàm tính baseline, features, chọn kernel, kiểm tra tier/split và dựng manifest. Mỗi bản mới ghi vào đường dẫn bất biến theo build, ví dụ `builds/{build_id}/data` cho Gold. Giữ khả năng đọc sản phẩm cũ qua adapter; manifest cũ thiếu thông tin nguồn phải thể hiện là chưa xác định.
4. **Bàn giao để xác minh.** Sau khi các CLI đã đi qua core và đường tính trùng lặp đã được tháo khỏi runner, bàn giao bộ raw mẫu, reference, spec, lệnh chạy hai môi trường và bảng tiêu chí ở mục 6. Đợt kiểm chứng độc lập phải chạy qua các CLI thật và có ít nhất một lần dùng Spark/HDFS trước khi chấp nhận bản production.
