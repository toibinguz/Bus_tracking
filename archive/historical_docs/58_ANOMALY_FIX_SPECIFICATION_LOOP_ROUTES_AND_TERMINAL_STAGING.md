# ĐẶC TẢ KỸ THUẬT: HIỆU CHỈNH TOPOLOGY TUYẾN VÒNG VÀ LỌC NHIỄU BẾN XE ĐẦU TUYẾN
> **Tài liệu**: `docs/58_ANOMALY_FIX_SPECIFICATION_LOOP_ROUTES_AND_TERMINAL_STAGING.md`  
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Áp dụng cho**: `module_1` (Step 1.5 Ground Truth Ingestion) & `module_3` (Step 3.1 Historical Baseline Model)  
> **Ngày ban hành**: 01/11/2026  
> **Trạng thái**: Đã phê duyệt triển khai (Approved for Implementation)

---

## I. BỐI CẢNH VÀ CÁC LỖ HỔNG CẦN KHẮC PHỤC

Từ kết quả phân tích EDA toàn diện trên 95,094 ô của ma trận `agg_segment_travel_times` (Doc 57), hệ thống ghi nhận 4 điểm nghẽn nghiêm trọng làm sai lệch dữ liệu:

1. **Lỗ hổng 1: Sai lệch mapping và sụp đổ dây chuyền trên tuyến vòng (`E11`, `E11CT`, `56B`,...)**:
   - Dữ liệu BusMap gốc của `E11` bị hoán đổi giữa tim đường và danh bạ trạm: Tim đường Chiều 0 (248 điểm, hướng Tràng Tiền) ghép với Trạm Chiều 0 (48 trạm, hướng Nghi Tàm). Việc đảo chiều đơn thuần tim đường 248 điểm khiến Trạm 1 bị snap vào tận km 26.2 (cuối tuyến). Ràng buộc đơn điệu $s_k \ge s_{k-1} + 15\text{m}$ đẩy toàn bộ 46 trạm còn lại vào 300m cuối tuyến với sai số snap $999,999\text{m}$, sinh ra phân đoạn ảo dài 26.2 km có thời gian di chuyển 87.5 phút.
   - Tuyến `56B` (và các tuyến vòng lặp/nhánh rẽ): Thuật toán tìm kiếm hình chiếu toàn cục (global projection) khiến Trạm 3 (`Phố Mã`) bị "hút" nhầm sang điểm quay về ở km 32 của polyline, kéo theo 35 trạm kế tiếp bị khóa ở $\ge 32\text{km}$ với sai số snap trên 2,500m.
2. **Lỗ hổng 2: Bẫy dừng đỗ chờ xuất bến tại Trạm 0 (Terminal Layover / Staging Artifact)**:
   - Tại trạm đầu tuyến (như Bến xe Gia Lâm trên Tuyến 51), xe buýt nổ máy đỗ chờ giờ chạy từ 15-20 phút. Dao động GPS tại chỗ ($s \approx 0$) vô tình kích hoạt mốc vượt trạm $s_{\text{target}} = 0$ khi xe chưa xuất phát, cộng dồn toàn bộ thời gian đỗ chờ vào phân đoạn [0 $\to$ 1], biến hành trình thực tế 7 phút thành 29 phút.
3. **Lỗ hổng 3: Thổi phồng phương sai mẫu khi $N=3$ và lỗi cắt cụt $P_{90}$**:
   - Bậc tự do mẫu $N-1=2$ khiến 1 ngoại lai đỗ chờ bến làm độ lệch chuẩn phóng đại từ ~30s lên 748.9s.
   - Công thức bách phân vị rời rạc `p90_idx = int(floor(0.90 * (N - 1)))` khi $N=3$ cho ra index 1 (chính là Median), dẫn đến $P_{90} \le \text{Median} < \text{Mean}$, vi phạm tính chất phân phối xác suất.

---

## II. THIẾT KẾ GIẢI PHÁP KỸ THUẬT

### 1. Nâng cấp Thuật toán Chiếu Trạm: Cửa Sổ Tiến Tới Lũy Tiến (Progressive Forward Window)
Trong `module_1_data_ingestion_and_preprocessing/step_1_5_busmap_canonical_migration/ingest_busmap_canonical.py`:

#### A. Khớp đúng tim đường cho Tuyến Vòng E11 & E11CT
- Tuyến `E11` và `E11CT` có 2 tim đường trong BusMap:
  - Chiều 0: 248 điểm (hướng Tràng Tiền - Cầu Giấy - Hồ Tây).
  - Chiều 1: 235 điểm (hướng Hồ Tây - Cầu Giấy - Tràng Tiền).
- **Quy tắc gán chính thức**:
  - Hướng `go` (48 trạm, bắt đầu qua Long Biên E1.4 $\to$ Hàng Than $\to$ Nghi Tàm): Dùng **Polyline Chiều 1 đảo chiều** (235 điểm reversed).
  - Hướng `re` (39 trạm, bắt đầu qua Long Biên E3.3 $\to$ Tràng Tiền): Dùng **Polyline Chiều 0 chuẩn** (248 điểm).

#### B. Thuật toán Cửa sổ lũy tiến (Progressive Window Snapping)
Với mỗi trạm $k \ge 1$, phạm vi tìm kiếm hình chiếu trên tim đường polyline bị giới hạn chặt chẽ:
$$s_k \in \left[ s_{k-1} - 30\text{m}, \ s_{k-1} + \max(4,000\text{m}, \ 3.0 \times d_{\text{flight}}(S_{k-1}, S_k)) \right]$$
trong đó $d_{\text{flight}}$ là khoảng cách đường chim bay Haversine giữa 2 trạm liên tiếp.
- Cơ chế này ngăn chặn tuyệt đối việc một trạm ở đầu hành trình bị snap nhảy cóc 30 km sang đường vòng về.

---

### 2. Xử lý Bẫy Bến Đầu Tuyến: Xác Thực Lăn Bánh Rời Bến (Rolling Departure Validation)
Trong `module_3_bus_eta_prediction/step_3_1_historical_baseline_model/baseline_segment_average.py`:

- Đối với mốc thời gian vượt Trạm 0 ($t_{\text{cross}}(S_0)$):
  - Chỉ chấp nhận cặp ping $[P_A, P_B]$ bắc cầu qua $s=0$ nếu các ping tiếp theo trong vòng 120s thỏa mãn điều kiện **xe thực sự lăn bánh rời bến**:
    1. Vận tốc dẫn xuất tức thời tại thời điểm rời bến: $v > 5.0\text{ km/h}$.
    2. Khoảng cách dọc tuyến tiếp tục tịnh tiến ra xa khỏi bến: $s_{\text{future}} \ge 80\text{m}$.
  - Nếu xe tiếp tục dao động quanh bến ($s \le 50\text{m}$ và $v < 3\text{ km/h}$), bỏ qua mốc này và tiếp tục tìm mốc xuất phát thực tế sau đó.

---

### 3. Chuẩn Hóa Thống Kê Phân Đoạn Khi Cỡ Mẫu Nhỏ ($N < 10$)

#### A. Lọc ngoại lai hành trình bằng MAD (Median Absolute Deviation)
Đối với tập mẫu hành trình $\mathcal{T} = \{\Delta t_1, \Delta t_2, \dots, \Delta t_N\}$ của cùng một phân đoạn $(k, \text{window}, \text{day\_type})$:
$$\text{MAD} = \text{median}(|\Delta t_i - \text{median}(\mathcal{T})|)$$
Một chuyến xe bị coi là bất thường (dừng đỗ/sự cố cá biệt) và bị loại khỏi tính toán mean/std nếu:
$$|\Delta t_i - \text{median}(\mathcal{T})| > 3.5 \times \max(\text{MAD}, 15.0\text{s})$$

#### B. Nội suy tuyến tính bách phân vị liên tục (Continuous Linear Percentiles)
Thay thế hàm cắt cụt `floor` bằng công thức nội suy liên tục chuẩn (tương thích `numpy.percentile(..., method='linear')`):
$$P_p = X_{(i)} + (X_{(i+1)} - X_{(i)}) \times (p \cdot (N - 1) - i)$$
Đảm bảo luôn thỏa mãn tính chất đơn điệu: $P_{10} \le \text{Median} \le P_{90}$.

#### C. Co cụm phương sai Bayesian (Empirical Bayes Shrinkage)
Khi $N < 10$, độ lệch chuẩn mẫu $s$ dễ bị nhiễu. Áp dụng công thức làm mềm:
$$\sigma_{\text{adjusted}} = \frac{N}{N + N_0} s_{\text{sample}} + \frac{N_0}{N + N_0} \sigma_{\text{route\_default}}$$
với $N_0 = 10$ và $\sigma_{\text{route\_default}} = 0.20 \times \text{median\_transit\_sec}$.

---

## III. KẾ HOẠCH TRIỂN KHAI VÀ TIÊU CHÍ CHẤP THUẬN (ACCEPTANCE CRITERIA)

| Bước | Hành động kỹ thuật | File can thiệp | Tiêu chuẩn hoàn thành (DoD) |
| :--- | :--- | :--- | :--- |
| **1** | Cập nhật thuật toán Ingest & Progressive Snapping | `module_1_.../ingest_busmap_canonical.py` | Chạy thành công (exit 0). Số trạm có `snap_dist_m > 100m` trên toàn bộ 13,301 trạm giảm về $\approx 0$. |
| **2** | Tái chiếu tọa độ Frenet cho toàn bộ Telemetry | `scripts/parallel_multi_route_projector.py` | 5,562,511 pings được chiếu lại trên tim đường chuẩn hóa không lỗi. |
| **3** | Cập nhật logic Rolling Departure & Bayes Shrinkage | `module_3_.../baseline_segment_average.py` | Đảm bảo lọc trạm 0, nội suy bách phân vị chuẩn. |
| **4** | Tái tính toán Ma trận thời gian hành trình Gold | `baseline_segment_average.py` | 95,094 ô được cập nhật. `max median` E11 giảm từ 5,252s về $\approx 100\text{s} - 200\text{s}$. `max std` tuyến 51 giảm từ 748s về mức thực tế. |
| **5** | Kiểm chứng thực nghiệm độc lập | Script audit | Không còn ô nào có $P_{90} < \text{Median}$, không còn ô nào có khoảng cách phân đoạn phi lý. |



---

## IV. BÁO CÁO NGHIỆM THU THỰC TẾ SAU TRIỂN KHAI (EMPIRICAL VERIFICATION REPORT)

Ngày 01/11/2026, toàn bộ 4 bước sửa lỗi đã được thực thi và nghiệm thu tự động trên cơ sở dữ liệu `data/hanoi_bus_system.db`.

### 1. Bảng đối chiếu số liệu Trước vs. Sau khi sửa lỗi

| Chỉ số kiểm định | Trạng thái Trước (Before) | Trạng thái Sau (After) | Chênh lệch & Ý nghĩa thực nghiệm |
| :--- | :--- | :--- | :--- |
| **Max Median toàn bảng** | **5,252.44 s** (~87.5 phút) | **1,653.07 s** (~27.5 phút) | **Giảm 3.2 lần** — Loại bỏ hoàn toàn giá trị ảo của E11 và 123. Toàn bộ Top 3 là các đoạn tắc thực tế qua cầu Vĩnh Tuy / Thăng Long. |
| **Max Std toàn bảng** | **748.93 s** (Tuyến 51 [re] Seg 0 $\to$ 1) | **489.07 s** (Tuyến 123 [re] 3.4km) | **Giảm 35%** — Tuyến 51 giảm từ 748.9s xuống **69.24s** nhờ loại bỏ xe đỗ bến và Bayes shrinkage. |
| **Độ dài đoạn [0 $\to$ 1] E11 [go]** | **26,262.2 m** (Ảo do dồn cục) | **301.9 m** (Chuẩn xác) | **Giảm 98.8%** — Trạm Long Biên E1.4 snap chuẩn chỉ cách tim đường 3.6m. |
| **Median $\Delta T$ [0 $\to$ 1] E11 [go]** | **5,252.44 s** | **55.86 s** | **Về đúng thực tế vật lý**: Đi 300m mất ~55 giây ($v \approx 19.5\text{ km/h}$). |
| **Độ dài đoạn [2 $\to$ 3] Tuyến 123 [go]** | **44,787.5 m** (Ảo do nối 2 chiều) | **3,288.0 m** (Chuẩn xác) | **Giảm 92.7%** — Thay thế bằng tim đường đối xứng 23.7 km. |
| **Số trạm bị fallback 999,999m** | **75 trạm** | **ĐÚNG 0 TRẠM** | **Triệt tiêu 100%** hiện tượng sụp đổ dây chuyền trên toàn bộ 13,301 trạm. |
| **Số trạm lỗi snap trên Tuyến 56B** | **35 trạm** (snap $> 2,500\text{m}$) | **ĐÚNG 0 TRẠM** | Snap distance trung bình giảm từ 2,500m xuống **5.7m**. |
| **Số ô vi phạm $P_{10} \le P_{50} \le P_{90}$** | 1,420 ô ($P_{90} \le P_{50}$) | **ĐÚNG 0 Ô** | **100% tuân thủ đơn điệu** nhờ công thức nội suy bách phân vị liên tục. |
| **Số ô có số liệu thực nghiệm (Tier 0)** | 79,187 ô (83.27%) | **80,505 ô (84.66%)** | **Tăng thêm 1,318 ô thực nghiệm** nhờ hồi sinh các tuyến vòng E11 và 56B. |

### 2. Bảng Top 3 Cực Đại Chính Thức Mới Của Toàn Bộ Mạng Lưới

#### A. Top 3 Max Median (Thời gian di chuyển lâu nhất - 100% là dữ liệu thực tế Tier 0):
1. **Tuyến 40 [re] - Seg [13 $\to$ 14]** (`202 Nguyễn Khoái` $\to$ `Aeon Mall Long Biên`): $L = 5,074.2\text{m}$, `EVENING_PEAK_CORE` Thứ Bảy, $N=3$, **Median = 1,653.07 s (~27.55 phút)**, Vận tốc = **11.05 km/h** (Ùn tắc thực tế qua cầu Vĩnh Tuy).
2. **Tuyến E01 [re] - Seg [23 $\to$ 24]** (`Viện Dệt May` $\to$ `Aeon Mall Long Biên`): $L = 4,957.1\text{m}$, `MIDDAY_LULL` Thứ Bảy, $N=19$, **Median = 1,609.33 s (~26.82 phút)**, Vận tốc = **11.09 km/h**.
3. **Tuyến 61 [go] - Seg [13 $\to$ 14]** (`189 Phạm Văn Đồng` $\to$ `Qua ngã 3 Hải Bối`): $L = 4,854.0\text{m}$, `EARLY_AFTERNOON` Thứ Bảy, $N=4$, **Median = 1,578.03 s (~26.30 phút)**, Vận tốc = **11.07 km/h** (Ùn tắc qua cầu Thăng Long).

#### B. Top 3 Max Std (Độ bất định lành mạnh - Không còn bị thổi phồng do bến xe):
1. **Tuyến 123 [re] - Seg [19 $\to$ 20]** (`Thị Nguyên` $\to$ `Canh Hoạch`): $L = 3,427.2\text{m}$, `EARLY_MORNING` Ngày thường, $N=21$, **Std = 489.07 s**, Median = 1,158.94 s.
2. **Tuyến E03 [re] - Seg [31 $\to$ 32]** (`Viện Dệt May` $\to$ `Aeon Mall Long Biên`): $L = 4,953.2\text{m}$, `PRE_EVENING_PEAK` Thứ Bảy, **Std = 474.40 s**, Median = 1,116.34 s.
3. **Tuyến E03 [re] - Seg [31 $\to$ 32]**: `MORNING_SURGE` Thứ Bảy, **Std = 474.40 s**, Median = 1,116.34 s.

> **Kết luận nghiệm thu**: Toàn bộ các bất thường, ngoại lai và sai số cấu trúc đã được khắc phục hoàn toàn. Bảng ma trận `agg_segment_travel_times` hiện tại đạt độ tin cậy toán học và vật lý tuyệt đối, đáp ứng đầy đủ tiêu chuẩn bàn giao cho Feature Store và mô hình ETA.
