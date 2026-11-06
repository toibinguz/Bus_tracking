# BÁO CÁO KIỂM TOÁN CÁC Ô CÓ GIÁ TRỊ BẤT THƯỜNG TRONG MA TRẬN THỜI GIAN HÀNH TRÌNH
> **Mã văn bản**: `docs/56_ANOMALOUS_CELLS_AND_STATION_MONOTONICITY_AUDIT_REPORT.md`  
> **Cơ sở dữ liệu**: `data/hanoi_bus_system.db`  
> **Bảng kiểm toán**: `agg_segment_travel_times` (95,094 cells, 3,522 phân đoạn $\times$ 9 khung giờ $\times$ 3 loại ngày)  
> **Thời điểm kiểm toán**: 2026-11-01  
> **Nguyên tắc tuân thủ**: [AGENTS.md](file:///z:/Desktop/Bus_tracking/AGENTS.md) (Điều 1: Kỷ luật thực nghiệm; Điều 5: Động học dẫn xuất; Độc lập với Dwell Time).

---

## I. TỔNG QUAN TÍNH TOÀN VẸN CỦA TOÀN BỘ 95,094 Ô

Hệ thống đã thực hiện quét tự động 100% toàn bộ **95,094 ô** trong bảng ma trận thời gian lịch sử phân đoạn (`agg_segment_travel_times`) phủ khắp 48 tuyến chính tắc (96 chiều lộ trình).

| Tiêu Chí Kiểm Tra Tính Hợp Lệ | Số Lượng Phát Hiện | Tỉ Lệ | Đánh Giá Tính Toàn Vẹn |
| :--- | :---: | :---: | :--- |
| **Giá trị âm hoặc bằng 0** ($\Delta T \le 0$ hoặc $V \le 0$) | **0** | 0.00% | **Tuyệt đối an toàn**: Không có ô nào bị lỗi tràn số hoặc âm. |
| **Phân vị nghịch đảo** ($P_{10} > P_{50}$ hoặc $P_{50} > P_{90}$) | **0** | 0.00% | **Toàn vẹn 100%**: Thứ tự phân vị hoàn toàn đơn điệu chặt chẽ. |
| **Giá trị NULL / NaN trong các trường metric cốt lõi** | **0** | 0.00% | **Sạch sẽ 100%**: Toàn bộ các trường số học đều đầy đủ. |
| **Cỡ mẫu thực nghiệm thiếu tin cậy** ($1 \le N_{\text{samples}} < 3$) | **0** | 0.00% | **Đạt chuẩn thống kê**: Mọi ô thực nghiệm đều có $\ge 3$ mẫu crossing. |
| **Nghịch lý khung giờ** (Đêm vắng chậm hơn cao điểm sáng) | **0** | 0.00% | **Hợp lý vật lý**: Không có hiện tượng giờ đêm chậm hơn giờ cao điểm. |

---

## II. BẢN CHẤT 4 NHÓM Ô CÓ GIÁ TRỊ "BẤT THƯỜNG" TRÊN TOÀN MẠNG LƯỚI

Qua việc lọc các phân vị biên ($V > 65\text{ km/h}$, $V < 4.0\text{ km/h}$, $P_{50} > 1,200\text{s}$, $\Delta P > 900\text{s}$, $\Delta s \le 10\text{m}$), toàn bộ các ô bất thường được giải mã chính xác thành 4 nhóm bản chất sau:

### 1. Nhóm Bất Thường Hình Học GIS & Trạm (143 Cặp Trạm Bị Vi Phạm Tính Đơn Điệu)
Đây là nhóm bất thường kỹ thuật xuất phát từ cấu trúc dữ liệu hình học gốc của **BusMap** (`data/ground_truth/busmap_canonical/` gồm `hanoi_bus_routes.geojson` và `hanoi_bus_stations.geojson` đã chuẩn hóa theo Doc 52):
- **Nguyên nhân 1: Tuyến vòng tròn ngược chiều (Circular Loop Reversals)**:
  - *Điển hình*: Tuyến buýt điện `E11` [go] (Yên Phụ - Bác Cổ - Hồ Tây - Cầu Giấy - Yên Phụ).
  - Tọa độ tim đường (polyline) được vẽ ngược chiều kim đồng hồ, trong khi thứ tự trạm dừng (`station_order`) lại được đánh số theo chiều kim đồng hồ.
  - Kết quả: Từ trạm số 2 đến trạm số 46, `cum_distance_m` liên tục **giảm lùi** từ $25,164.6\text{m} \to 833.2\text{m}$ ($\Delta s < 0$).
  - Đoạn $1 \to 2$ có cự ly vọt lên **$24,859.6\text{m}$** (chu vi vòng) với $P_{50} = 6,614.3\text{s}$ (~110 phút, ô có $P_{50}$ lớn nhất toàn hệ thống).
  - Các đoạn tiếp theo có $\Delta s \le 0$ nên bị hàm logic clamp về cận dưới an toàn `seg_dist = max(10.0, s_to - s_from) = 10.0m` và $P_{50} = 1.1 - 2.6\text{s}$.
- **Nguyên nhân 2: Snapping nhầm nhánh trên đường vòng/quay đầu (Ambiguous Snapping)**:
  - *Điển hình*: Tuyến `56B` [go] (Học viện Phật giáo - Sóc Sơn).
  - Trạm `Phố Mã` xuất hiện 2 lần: Trạm 3 (chiều đi) và Trạm 36 (chiều về). Khi snap chiếu trạm lên polyline, trạm 3 bị thuật toán gán nhầm vào đỉnh polyline của chiều về tại $s = 32,792.3\text{m}$ thay vì chiều đi tại $s \approx 3,500\text{m}$.
  - Kết quả: Phân đoạn $2 \to 3$ vọt lên $30,212.4\text{m}$, còn phân đoạn $3 \to 4$ bị giật lùi $-28,668.9\text{m}$ (bị clamp về $10.0\text{m}$).
- **Nguyên nhân 3: Các trạm trùng tọa độ hoặc trạm bến đầu cự ly = 0**:
  - Tuyến `40` [re] (Trạm $0 \to 1$ cùng có $s = 0.0\text{m}$), Tuyến `E05` [go] (Trạm $27 \to 28$ Công viên Bách Thảo cùng $s = 15,799.4\text{m}$). Cự ly thực tế giữa 2 trạm là 0m, bị gán `10.0m`.
- **Tổng kết**: Có **143 cặp trạm** trên toàn bộ 176 tuyến của BusMap, nhưng trong **48 tuyến chính tắc đang vận hành chỉ có đúng 60 cặp trạm** có $s_{\text{to}} \le s_{\text{from}}$ (trong đó riêng tuyến E11 đã chiếm tới 38 cặp do ngược chiều tim đường).

### 2. Nhóm Vận Tốc Siêu Cao ($V_{\text{commercial}} > 65\text{ km/h}$)
Toàn mạng lưới 95,094 ô chỉ có duy nhất **3 ô** ghi nhận $V > 65\text{ km/h}$ (0.003%):
1. **Tuyến 19 [re], Đoạn 22 $\to$ 23** (Công ty CP Công trình GT $\to$ ĐH Hà Nội, 435m): `EARLY_MORNING` Chủ Nhật, $N=3$, $P_{50} = 22.3\text{s}$, $V = 70.27\text{ km/h}$.
2. **Tuyến 19 [re], Đoạn 21 $\to$ 22** (Bách hóa Thanh Xuân $\to$ Công ty CP Công trình GT, 853m): `EVENING_PEAK_CORE` Thứ 7, $N=7$, $P_{50} = 45.52\text{s}$, $V = 67.50\text{ km/h}$.
3. **Tuyến 56B [re], Đoạn 37 $\to$ 38** (Phố Mã $\to$ Tiểu học Phù Linh, 1,193m): Ngoại thành Sóc Sơn, `LATE_EVENING_NIGHT` Chủ Nhật, $N=14$, $P_{50} = 64.51\text{s}$, $V = 66.60\text{ km/h}$.
- *Đánh giá*: Tuyến 56B chạy ngoại thành đường trường vắng vào ban đêm đạt 66 km/h là thực tế. Tuyến 19 đường Nguyễn Trãi lúc rạng sáng chủ nhật vắng xe không có khách dừng đỗ nên xe buýt lướt sóng xanh. Cỡ mẫu nhỏ ($N=3-7$).

### 3. Nhóm Vận Tốc Cực Thấp ($V < 4.0\text{ km/h}$) & Thời Gian Kẹt Xe Dị Thường ($P_{50} > 1,200\text{s}$)
Các ô này **HOÀN TOÀN KHÔNG PHẢI LỖI KỸ THUẬT**, mà là phản ánh trung thực hiện tượng tê liệt giao thông tại các nút thắt cổ chai độc đạo của Hà Nội:
- **"Điểm đen ùn tắc số 1" - Vượt sông Hồng qua Cầu Chương Dương**:
  - Xuất hiện đồng loạt trên hàng loạt tuyến: `34`, `E02`, `43`, `48`, `17`, `22A`, `01`, `146`.
  - Phân đoạn: *Trường tiểu học Ái Mộ (Long Biên) $\to$ Cầu Chương Dương $\to$ Trần Quang Khải / Long Biên / Ô Quan Chưởng*.
  - Cự ly $2,100\text{m} - 2,900\text{m}$, nhưng $P_{50}$ lên tới **$1,227\text{s} - 1,482\text{s}$** (~20.5 đến 24.7 phút bò nhích từng mét trên cầu), vận tốc rơi xuống **$5.5 - 7.5\text{ km/h}$** vào chiều Thứ 7 và sáng các ngày trong tuần!
- **Nút giao Giải Phóng - Vành Đai 3 - Bến xe Nước Ngầm**:
  - Tuyến `E06` [go], Đoạn 34 $\to$ 35 (Hoàng Liệt $\to$ Bến xe Nước Ngầm, 387m): Mất tới **420.2 giây** (~7 phút) để di chuyển 387 mét qua nút giao ngã ba Ngọc Hồi - Giải Phóng vào chiều Thứ Bảy, vận tốc chỉ đạt **$3.31\text{ km/h}$** (kỷ lục chậm nhất toàn mạng lưới).
- **Nút giao Ngã tư KCN Thăng Long (Đông Anh)**:
  - Tuyến `61` [re], Đoạn 34 $\to$ 35 (UBND xã Kim Chung $\to$ Ngã tư KCN Thăng Long, 596m): $P_{50} = 643.6\text{s}$, $V = 3.33\text{ km/h}$ vào chiều Chủ Nhật do công nhân và phương tiện đổ về.
- **Phố cổ Hoàn Kiếm / Cửa khẩu Ô Quan Chưởng**:
  - Tuyến `22A` [go], Đoạn 32 $\to$ 33 (3A Phan Đình Phùng $\to$ Ô Quan Chưởng, 897m): $P_{50} = 902.2\text{s}$ (15 phút), $V = 3.58\text{ km/h}$ chiều Thứ Bảy.
  - Tuyến `146` [re], Đoạn 12 $\to$ 13 (Hàng Muối $\to$ 26 Trần Nhật Duật, 550m): $P_{50} = 545.0\text{s}$, $V = 3.63\text{ km/h}$.

### 4. Nhóm Độ Phân Tán Cực Đoan ($\Delta P = P_{90} - P_{10} > 900\text{s}$ Hoặc $\Delta P / P_{50} > 250\%$)
- Các phân đoạn có độ bất định thời gian khổng lồ (chuyến nhanh nhất chỉ mất 2-3 phút, nhưng chuyến chậm nhất mất tới 25-30 phút):
  - **Tuyến 51 [re]**, Đoạn 0 $\to$ 1 (BX Gia Lâm $\to$ Cầu Chui, 1,758m): $\Delta P = 1,344.6\text{s}$ (chênh lệch 22.4 phút giữa $P_{90}$ và $P_{10}$).
  - **Tuyến E03 / E04 [re]**, Đoạn qua cầu Vĩnh Tuy $\to$ Aeon Mall Long Biên (~5km): $\Delta P = 1,139.7\text{s}$.
  - **Tuyến 35A [go]**, Đoạn 1 $\to$ 2 (Gần Đỗ Nhuận $\to$ 218 Phạm Văn Đồng, 988m): Tỉ lệ phân tán tương đối đạt **$506.9\%$** ($P_{50} = 192\text{s}$ nhưng $\Delta P = 975\text{s}$).

---

## III. BẢNG CHI TIẾT TRUNG VỊ VÀ ĐỘ PHÂN TÁN TUYẾN 02 (35 PHÂN ĐOẠN, CHIỀU ĐI)

Dưới đây là bảng trích xuất chi tiết từ View `v_segment_dispersion_matrix` trên tuyến đường trục mẫu **Tuyến 02 [Chiều đi: BX Yên Nghĩa $\to$ Bác Cổ]** trong ngày thường (`WEEKDAY`), so sánh giữa 3 khung giờ trọng điểm:
- **AM**: Cao điểm sáng (`MORNING_PEAK`, 07:00 - 08:30)
- **Noon**: Thấp điểm trưa (`MIDDAY_LULL`, 11:30 - 13:30)
- **PM**: Cao điểm chiều (`EVENING_PEAK_CORE`, 17:00 - 18:30)

> **Ghi chú**:  
> - Độ tản mát = $\Delta P = P_{90} - P_{10}$ (giây).  
> - V_commercial = $\frac{\Delta s}{P_{50}} \times 3.6$ (km/h).  
> - Hai phân đoạn đầu cuối ($0 \to 1$ và $34 \to 35$) được giữ nguyên Tier 2 Fallback theo đúng chỉ thị kỹ thuật của người dùng.

| Phân Đoạn | Cự Ly (m) | $P_{50}$ AM (s) | Độ Tản AM (s) | $V$ AM (km/h) | $P_{50}$ Noon (s) | Độ Tản Noon (s) | $V$ Noon | $P_{50}$ PM (s) | Độ Tản PM (s) | $V$ PM | Tên Phân Đoạn (Từ Trạm $\to$ Đến Trạm) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **0 $\to$ 1** | 614 | 127.7 | 57.5 | 17.3 | 127.7 | 57.5 | 17.3 | 127.7 | 57.5 | 17.3 | *(B) BX Yên Nghĩa $\to$ Trường TC Kinh tế* (Tier 2 Fallback) |
| **1 $\to$ 2** | 535 | 78.1 | 21.1 | 24.6 | 73.6 | 21.3 | 26.2 | 73.5 | 24.4 | 26.2 | Trường TC Kinh tế $\to$ Đối diện Nissan Hà Đông |
| **2 $\to$ 3** | 696 | 152.7 | 97.6 | 16.4 | 152.6 | 109.8 | 16.4 | 175.5 | 167.4 | 14.3 | Đối diện Nissan Hà Đông $\to$ 807 Quang Trung |
| **3 $\to$ 4** | 380 | 108.4 | 90.7 | 12.6 | 121.5 | 121.8 | 11.2 | 124.3 | 145.2 | 11.0 | 807 Quang Trung $\to$ 707-709 Quang Trung |
| **4 $\to$ 5** | 591 | 177.3 | 133.3 | 12.0 | 178.6 | 141.6 | 11.9 | 178.8 | 143.9 | 11.9 | 707-709 Quang Trung $\to$ Ga La Khê |
| **5 $\to$ 6** | 249 | 46.9 | 17.1 | 19.1 | 43.5 | 16.6 | 20.6 | 48.2 | 23.0 | 18.6 | Ga La Khê $\to$ Chợ La Khê |
| **6 $\to$ 7** | 410 | 121.2 | 112.7 | 12.2 | 92.4 | 77.0 | 16.0 | 108.0 | 108.5 | 13.7 | Chợ La Khê $\to$ Công ty CPLH Thực Phẩm |
| **7 $\to$ 8** | 543 | 90.9 | 28.5 | 21.5 | 80.9 | 29.0 | 24.2 | 93.4 | 22.7 | 20.9 | Công ty CPLH Thực Phẩm $\to$ Ga Hà Đông |
| **8 $\to$ 9** | 304 | 63.3 | 42.2 | 17.3 | 56.2 | 32.5 | 19.5 | 100.7 | 122.4 | 10.9 | Ga Hà Đông $\to$ Bưu điện Hà Đông |
| **9 $\to$ 10** | 624 | 193.3 | 153.0 | 11.6 | 147.3 | 96.1 | 15.2 | **304.8** | **216.8** | **7.4** | **Bưu điện Hà Đông $\to$ Sở Tư Pháp (Cầu Trắng)** |
| **10 $\to$ 11** | 296 | 57.3 | 19.7 | 18.6 | 51.5 | 17.1 | 20.7 | 62.0 | 28.3 | 17.2 | Sở Tư Pháp $\to$ Ga Văn Quán |
| **11 $\to$ 12** | 323 | 60.9 | 110.5 | 19.1 | 53.8 | 14.0 | 21.6 | 63.5 | 50.2 | 18.3 | Ga Văn Quán $\to$ Siêu thị Nguyễn Kim |
| **12 $\to$ 13** | 282 | 58.8 | 35.3 | 17.3 | 50.0 | 20.3 | 20.3 | 65.2 | 80.4 | 15.5 | Siêu thị Nguyễn Kim $\to$ ĐH Kiến trúc Hà Nội |
| **13 $\to$ 14** | 306 | 65.2 | 41.1 | 16.9 | 61.5 | 39.3 | 17.9 | 73.9 | 52.2 | 14.9 | ĐH Kiến trúc Hà Nội $\to$ Học viện An Ninh |
| **14 $\to$ 15** | 200 | 42.2 | 21.9 | 17.1 | 38.2 | 19.6 | 18.9 | 42.8 | 19.6 | 16.9 | Học viện An Ninh $\to$ Ga Phùng Khoang |
| **15 $\to$ 16** | 551 | 106.7 | 42.0 | 18.6 | 92.6 | 31.8 | 21.4 | 114.7 | 58.8 | 17.3 | Ga Phùng Khoang $\to$ 521A Nguyễn Trãi |
| **16 $\to$ 17** | 280 | 50.7 | 19.9 | 19.9 | 47.5 | 17.6 | 21.2 | 56.1 | 24.3 | 18.0 | 521A Nguyễn Trãi $\to$ TCT Sông Đà |
| **17 $\to$ 18** | 311 | 59.7 | 63.8 | 18.8 | 54.8 | 21.8 | 20.4 | 57.7 | 22.1 | 19.4 | TCT Sông Đà $\to$ HV Khoa học Xã hội |
| **18 $\to$ 19** | 586 | 204.2 | 207.3 | 10.3 | 167.8 | 140.9 | 12.6 | 183.0 | 155.2 | 11.5 | HV Khoa học Xã hội $\to$ Công ty Giày Thượng Đình |
| **19 $\to$ 20** | 373 | 73.0 | 102.9 | 18.4 | 62.0 | 17.6 | 21.7 | 66.6 | 20.9 | 20.1 | Công ty Giày Thượng Đình $\to$ Nhà máy thuốc lá Thăng Long |
| **20 $\to$ 21** | 461 | **168.2** | **341.1** | **9.9** | 72.7 | 21.2 | 22.8 | 83.4 | 30.2 | 19.9 | **Thuốc lá Thăng Long $\to$ Ga Thượng Đình (Ngã Tư Sở)** |
| **21 $\to$ 22** | 319 | 117.0 | 126.9 | 9.8 | 58.2 | 24.5 | 19.7 | 66.5 | 28.2 | 17.3 | Ga Thượng Đình $\to$ 129T Nguyễn Trãi |
| **22 $\to$ 23** | 1272 | 289.1 | 222.6 | 15.8 | 199.3 | 72.3 | 23.0 | 259.4 | 116.9 | 17.6 | 129T Nguyễn Trãi $\to$ Trường ĐH Thủy Lợi (Tây Sơn) |
| **23 $\to$ 24** | 359 | 111.3 | 77.7 | 11.6 | 96.5 | 68.1 | 13.4 | 110.4 | 85.6 | 11.7 | Trường ĐH Thủy Lợi $\to$ ĐH Công Đoàn |
| **24 $\to$ 25** | 838 | 247.4 | 164.7 | 12.2 | 181.3 | 71.6 | 16.6 | 215.8 | 71.6 | 14.0 | ĐH Công Đoàn $\to$ 83 Nguyễn Lương Bằng |
| **25 $\to$ 26** | 387 | 148.0 | 104.8 | 9.4 | 102.7 | 76.3 | 13.6 | 144.7 | 101.4 | 9.6 | 83 Nguyễn Lương Bằng $\to$ UBND quận Đống Đa |
| **26 $\to$ 27** | 481 | 98.3 | 35.8 | 17.6 | 85.8 | 28.0 | 20.2 | 107.2 | 38.5 | 16.1 | UBND quận Đống Đa $\to$ Đối diện Nhà thờ Hàng Bột |
| **27 $\to$ 28** | 575 | 197.7 | 140.1 | 10.5 | 134.8 | 75.8 | 15.4 | 164.8 | 118.2 | 12.6 | Đối diện Nhà thờ Hàng Bột $\to$ Văn Miếu Quốc Tử Giám |
| **28 $\to$ 29** | 548 | 145.0 | 113.2 | 13.6 | 123.3 | 62.3 | 16.0 | 148.9 | 91.8 | 13.2 | Văn Miếu Quốc Tử Giám $\to$ Tiểu Học Lý Thường Kiệt |
| **29 $\to$ 30** | 439 | 170.2 | 219.1 | 9.3 | 131.2 | 150.1 | 12.0 | 103.8 | 46.0 | 15.2 | Tiểu Học Lý Thường Kiệt $\to$ Cửa Nam |
| **30 $\to$ 31** | 567 | 241.8 | 156.6 | 8.4 | 181.7 | 110.3 | 11.2 | 191.4 | 82.7 | 10.7 | Cửa Nam $\to$ Tháp Hà Nội (Hai Bà Trưng) |
| **31 $\to$ 32** | 373 | 122.1 | 81.3 | 11.0 | 115.9 | 76.5 | 11.6 | 104.8 | 44.3 | 12.8 | Tháp Hà Nội $\to$ BV Hữu Nghị Việt Đức |
| **32 $\to$ 33** | 429 | 145.5 | 76.1 | 10.6 | 139.5 | 64.4 | 11.1 | 139.1 | 57.5 | 11.1 | BV Việt Đức $\to$ Tràng Tiền Plaza |
| **33 $\to$ 34** | 332 | 103.7 | 61.0 | 11.5 | 111.0 | 63.1 | 10.8 | 107.4 | 80.6 | 11.1 | Tràng Tiền Plaza $\to$ Nhà hát Lớn Hà Nội |
| **34 $\to$ 35** | 634 | 131.9 | 59.3 | 17.3 | 131.9 | 59.3 | 17.3 | 131.9 | 59.3 | 17.3 | *Nhà hát Lớn Hà Nội $\to$ (A) Bác Cổ* (Tier 2 Fallback) |

---

## IV. BÀI HỌC VẬT LÝ TỪ BẢNG THỐNG KÊ TUYẾN 02

1. **Hiệu ứng Nghẽn Cổ Chai Ngã Tư Sở (Đoạn 20 $\to$ 21)**:
   - Cự ly chỉ 461m từ Nhà máy thuốc lá Thăng Long $\to$ Ga Thượng Đình.
   - Buổi trưa: $P_{50} = 72.7\text{s}$, Độ tản chỉ $21.2\text{s}$, Vận tốc đạt $22.8\text{ km/h}$.
   - Cao điểm sáng (07:00 - 08:30): $P_{50}$ nhảy vọt lên **$168.2\text{s}$**, đặc biệt Độ tản mát vọt lên **$341.1\text{s}$** (gấp đôi trung vị!), Vận tốc tụt xuống **$9.9\text{ km/h}$**. Điều này thể hiện sự bất định tột độ của dòng phương tiện đổ dồn từ Hà Đông vào nút giao Ngã Tư Sở.
2. **Hiệu ứng Giờ Tan Tầm Hà Đông (Đoạn 9 $\to$ 10, Cầu Trắng Hà Đông)**:
   - Buổi trưa: $P_{50} = 147.3\text{s}$, Vận tốc $15.2\text{ km/h}$.
   - Cao điểm chiều (17:00 - 18:30): $P_{50}$ tăng lên **$304.8\text{s}$** (hơn 5 phút cho đoạn 624m), Vận tốc chỉ còn **$7.4\text{ km/h}$** do xung đột rẽ tại Cầu Trắng / Sở Tư Pháp.

---

## V. KIẾN NGHỊ XỬ LÝ DỮ LIỆU SẠCH (DATA SANITIZATION ACTION PLAN)

Để ma trận đạt độ hoàn mỹ trước khi làm đầu vào cho mô hình suy luận ETA:
1. **Đối với 143 cặp trạm vi phạm tính đơn điệu ($\Delta s \le 0$)**:
   - Ghi nhận cờ lọc `is_geometry_anomalous = 1` cho các cặp trạm này để mô hình Machine Learning loại bỏ hoặc tự động fallback sang giá trị trung bình toàn tuyến.
2. **Đối với 3 ô có vận tốc siêu cao ($V > 65$ km/h)**:
   - Đặt ngưỡng trần (speed cap) $V_{\max} = 55.0\text{ km/h}$ cho xe buýt nội đô, điều chỉnh lại $P_{50} = \frac{\Delta s}{55/3.6}$ để tránh dự báo ETA quá lạc quan bất khả thi.
3. **Đối với các ô kẹt xe cực độ ($V < 4.0$ km/h, Cầu Chương Dương, Bến xe Nước Ngầm)**:
   - **Giữ nguyên 100%**, vì đây là giá trị thực nghiệm phản ánh chân lý giao thông Hà Nội.

