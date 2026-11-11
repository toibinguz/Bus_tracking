# SPEC-32: ML Model ETA Error Probability Distribution Specification
## Đặc tả Toán học và Trực quan hóa Biểu đồ Phân phối Xác suất Sai số Mô hình ML ETA theo Khoảng cách Trạm

- **Mã tài liệu:** `SPEC-32-PLOTS`
- **Đường dẫn lưu trữ:** `docs/specs/32_ML_EVALUATION_ERROR_DISTRIBUTION_PLOTS_SPEC.md`
- **Phiên bản:** 1.0.0
- **Trạng thái:** Approved Architecture Specification (Sẵn sàng triển khai bởi `@leaf_coder` và nghiệm thu bởi `@blind_tester`)
- **Tác giả:** `@architect`
- **Quy tắc tuân thủ:** AGENTS.md (Evidence-first, Zero-Speculation, Không viết code thực thi trong spec).

---

## 1. Mục tiêu và Bối cảnh Kỹ thuật (Executive Summary)

### 1.1. Yêu cầu Người dùng
Người dùng yêu cầu trực quan hóa và phân tích kết quả dự báo của mô hình Machine Learning (XGBoost ETA) trên tập kiểm thử độc lập (Held-Out Test Set), phân rã cụ thể theo 4 trường hợp khoảng cách trạm: **cách 1, 2, 5, 10 trạm**.
Đối với **mỗi trường hợp trạm**, hệ thống phải lập bảng thống kê và vẽ **hai biểu đồ phân phối xác suất**:
1. **Biểu đồ 1:** Phân phối xác suất của biến ngẫu nhiên chỉ **độ lệch theo đơn vị thời gian** (có dấu: lệch sớm mang dấu `-`, lệch muộn mang dấu `+`).
2. **Biểu đồ 2:** Phân phối xác suất của biến ngẫu nhiên chỉ **độ lệch theo tỉ lệ phần trăm** (có dấu: lệch sớm mang dấu `-`, lệch muộn mang dấu `+`).

### 1.2. Mục đích Phân tích Nghiệp vụ Giao thông Công cộng
Chỉ số sai số tổng hợp như MAE toàn cục (ví dụ MAE $\approx 96.7\text{s}$) không phản ánh được tính biến thiên thực tế và độ bất định khi xe buýt ở các cự ly khác nhau:
- Khi xe chỉ còn **1 trạm** (chuẩn bị cập bến): Sai số phải rất nhỏ (vài chục giây), hành khách nhạy cảm với việc xe đến sớm làm lỡ chuyến.
- Khi xe còn **2, 5, 10 trạm** (hành lang xa): Thời gian hành trình chịu ảnh hưởng tích lũy từ các nút giao cắt, đèn tín hiệu và ùn tắc giao thông, khiến phân phối sai số mở rộng (dải phương sai tăng dần).
- Việc phân tách rõ **lệch sớm (Early arrival)** và **lệch muộn (Delayed arrival)** là tối quan trọng trong việc thiết lập biên an toàn phục vụ hành khách (Conservative Asymmetric ETA - SPEC-11, SPEC-23).

---

## 2. Mô hình Toán học và Định nghĩa Biến Ngẫu nhiên (Mathematical Foundations)

### 2.1. Không gian Mẫu và Dữ liệu Đầu vào
Xét tập quan sát kiểm thử độc lập $\mathcal{D}_{\text{test}}$ gồm $N = 3,704,820$ bản ghi lấy từ phân vùng:
`data/lakehouse/gold/eta_feature_store/split=test/route_code=*/part-00000.snappy.parquet` (khoảng thời gian từ `2026-11-01` đến `2026-11-07`).

Với mỗi quan sát thứ $i \in \mathcal{D}_{\text{test}}$, ta có các đại lượng quan sát và dự báo:
- $y_i = \text{actual\_eta\_sec}_i \in \mathbb{R}^+$: Thời gian di chuyển thực tế từ vị trí hiện tại của xe buýt đến trạm mục tiêu (tính bằng giây). Trong tập dữ liệu, $y_i \ge 5.0\text{s}$.
- $\hat{y}_i = \hat{y}_{\text{pred}, i} \in \mathbb{R}^+$: Thời gian dự báo (ETA) được sinh ra từ mô hình ML (`eta_xgb_global_pruned_r3_big.json` kết hợp baseline):
  $$\hat{y}_i = \max\left(5.0, \, \text{baseline\_eta\_p50\_sec}_i + f_{\text{XGB}}(\mathbf{x}_i)\right)$$
  trong đó $f_{\text{XGB}}(\mathbf{x}_i)$ là phần dư bù trừ được dự báo bởi mô hình XGBoost với 53 đặc trưng tinh gọn (pruned features).
- $k_i = \text{n\_stations\_ahead}_i \in \mathbb{N}^+$: Số trạm mục tiêu còn lại phía trước trên hành trình tuyến.

---

### 2.2. Biến Ngẫu nhiên 1: Độ lệch Thời gian Có dấu ($\Delta t$)

#### Định nghĩa Toán học
Biến ngẫu nhiên độ lệch thời gian $\Delta t$ của quan sát $i$ được định nghĩa bằng hiệu số giữa thời gian thực tế và thời gian dự báo:
$$\Delta t_i = y_i - \hat{y}_i$$
Đơn vị chuẩn: **Giây (seconds, $\text{s}$)**. Đơn vị thứ cấp phục vụ diễn giải: **Phút (minutes, $\text{min}$)** với $\Delta t_{\text{min}, i} = \frac{\Delta t_i}{60}$.

#### Kiểm chứng Nghiêm ngặt Quy ước Dấu ("Lệch sớm dấu -, Lệch muộn dấu +")
Theo đúng yêu cầu của người dùng:
1. **Trường hợp xe đến muộn hơn dự báo (Lệch muộn / Late / Delayed Arrival):**
   - Thực tế xe buýt mất nhiều thời gian hơn dự tính: $y_i > \hat{y}_i$.
   - Khi đó: $\Delta t_i = y_i - \hat{y}_i > 0$.
   - **Mang dấu dương ($+$)** $\implies$ Đúng yêu cầu "lệch muộn dấu +".
   - *Ví dụ:* Mô hình dự báo xe đến sau $120\text{s}$, nhưng thực tế xe chạy mất $180\text{s}$. Khi đó $\Delta t = 180 - 120 = +60\text{s}$ (xe trễ 1 phút so với dự báo).
2. **Trường hợp xe đến sớm hơn dự báo (Lệch sớm / Early Arrival):**
   - Thực tế xe buýt chạy nhanh hơn dự tính: $y_i < \hat{y}_i$.
   - Khi đó: $\Delta t_i = y_i - \hat{y}_i < 0$.
   - **Mang dấu âm ($-$)** $\implies$ Đúng yêu cầu "lệch sớm dấu -".
   - *Ví dụ:* Mô hình dự báo xe đến sau $120\text{s}$, nhưng thực tế xe đã tới nơi sau $90\text{s}$. Khi đó $\Delta t = 90 - 120 = -30\text{s}$ (xe đến sớm 30 giây).
3. **Trường hợp hoàn hảo (On-time):**
   - $y_i = \hat{y}_i \implies \Delta t_i = 0$.

> [!IMPORTANT]
> Lưu ý dành cho `@leaf_coder` và `@blind_tester`: Trong một số tài liệu học thuật về Machine Learning thuần túy, residual thường được viết là $e = \hat{y} - y$. Tuy nhiên, trong bài toán vận tải công cộng và theo yêu cầu trực tiếp từ người dùng, công thức bắt buộc phải là $\Delta t = y_{\text{actual}} - \hat{y}_{\text{pred}}$ để đảm bảo xe trễ mang dấu dương và xe sớm mang dấu âm.

---

### 2.3. Biến Ngẫu nhiên 2: Độ lệch Phần trăm Có dấu ($\Delta\%$)

#### Định nghĩa Toán học
Biến ngẫu nhiên độ lệch phần trăm $\Delta\%$ được định nghĩa là tỷ lệ phần trăm giữa độ lệch thời gian có dấu so với thời gian thực tế:
$$\Delta\%_i = \left( \frac{y_i - \hat{y}_i}{y_i} \right) \times 100\% = \left( \frac{\Delta t_i}{y_i} \right) \times 100\%$$
Đơn vị chuẩn: **Phần trăm ($\%$)**.

#### Kiểm chứng Nghiêm ngặt Quy ước Dấu
1. **Lệch muộn:** $y_i > \hat{y}_i \implies \Delta\%_i > 0$ (**dấu $+$**).
2. **Lệch sớm:** $y_i < \hat{y}_i \implies \Delta\%_i < 0$ (**dấu $-$**).
3. **Chính xác tuyệt đối:** $\Delta\%_i = 0\%$.

#### Xử lý Mẫu số và Ổn định Số học (Numerical Conditioning & Outlier Boundaries)
Trong tập dữ liệu, khi xe buýt đã tiến sát trạm dừng ($y_i$ nhỏ, ví dụ $y_i \in [5, 30]\text{s}$ ở mốc $K=1$), một sai lệch nhỏ tuyệt đối 15 giây có thể tạo ra tỷ lệ phần trăm lớn ($\pm 100\%$).
Để biểu đồ phân phối xác suất có giá trị quan sát trực quan cao, không bị co cụm về một cột siêu hẹp do một vài ngoại lai ở đuôi phân phối (extreme fat tails):
- **Phạm vi hiển thị trục hoành của Biểu đồ 2 ($X$-limits):** Quy định hiển thị trong khoảng hữu hạn đối xứng:
  $$X_{\text{pct}} \in [-100\%, \, +100\%] \quad \text{hoặc} \quad [-150\%, \, +150\%]$$
- **Tỷ lệ bao phủ (Display Coverage Ratio):** Script phải tính toán và in ra tỷ lệ các quan sát rơi vào khung hiển thị (yêu cầu $\text{Coverage} \ge 98.0\%$).
- **Số liệu thống kê:** Mọi số liệu thống kê (Mean, Median, P10, P90, Std) phải được tính trên **toàn bộ dữ liệu thực tế** (không cắt xén mẫu khi tính bảng số liệu, chỉ cắt cửa sổ hiển thị trục tọa độ biểu đồ nếu cần).
- **Chỉ số tham chiếu bổ sung:** Trong bảng tổng hợp, tính thêm metric WAPE (Weighted Absolute Percentage Error):
  $$\text{WAPE} = \frac{\sum_{i=1}^N |y_i - \hat{y}_i|}{\sum_{i=1}^N y_i} \times 100\%$$

---

### 2.4. Phân nhóm Khoảng cách Trạm (Station Horizon Subsets)

Người dùng yêu cầu cụ thể 4 trường hợp: **cách 1, 2, 5, 10 trạm**.
Tương ứng trong tập dữ liệu kiểm thử `data/lakehouse/gold/eta_feature_store/split=test/`, ta trích xuất chính xác 4 tập con độc lập dựa trên cột `n_stations_ahead`:

$$\mathcal{S}_K = \left\{ i \in \mathcal{D}_{\text{test}} \;\middle|\; \text{n\_stations\_ahead}_i = K \right\}, \quad K \in \{1, 2, 5, 10\}$$

#### Bảng Kiểm kê Cỡ mẫu Kiểm định Độc lập trên Toàn bộ 47 Tuyến Xe Buýt:

| Mã Tập con | Điều kiện Lọc | Diễn giải Nghiệp vụ | Cỡ mẫu Thực tế ($N$) | Đủ điều kiện Thống kê ($N \ge 1,000$) |
| :---: | :---: | :---: | :---: | :---: |
| **$K=1$** | `n_stations_ahead == 1` | Cách 1 trạm kế tiếp (Chuẩn bị đến) | **863,984** | **Đạt** ($863\times$ ngưỡng tối thiểu) |
| **$K=2$** | `n_stations_ahead == 2` | Cách 2 trạm (Chặng ngắn) | **124,490** | **Đạt** ($124\times$ ngưỡng tối thiểu) |
| **$K=5$** | `n_stations_ahead == 5` | Cách 5 trạm (Chặng trung bình) | **47,128** | **Đạt** ($47\times$ ngưỡng tối thiểu) |
| **$K=10$** | `n_stations_ahead == 10` | Cách 10 trạm (Chặng dài) | **50,040** | **Đạt** ($50\times$ ngưỡng tối thiểu) |
| **Tổng cộng** | $\bigcup_{K \in \{1,2,5,10\}} \mathcal{S}_K$ | 4 trường hợp khảo sát | **1,085,642** | Toàn bộ đều là dữ liệu held-out test thật |

> [!NOTE]
> Mọi trường hợp $K \in \{1, 2, 5, 10\}$ đều có số lượng quan sát vượt trên $47,000$ mẫu từ 47 tuyến xe buýt khác nhau trong tuần kiểm thử độc lập. Do đó, hoàn toàn sử dụng điều kiện bằng chính xác `n_stations_ahead == K` mà không cần phải gộp dải (pooling) hay nội suy.

---

## 3. Thiết kế Biểu đồ Phân phối Xác suất (Visualization Architecture)

### 3.1. Danh mục 8 Biểu đồ Riêng lẻ và 1 Biểu đồ Tổng hợp

Hệ thống phải sinh ra tổng cộng **8 biểu đồ đơn** (4 trường hợp trạm $\times$ 2 loại biểu đồ) và **1 biểu đồ Dashboard tổng hợp ma trận $4 \times 2$**:

| STT | Tên file hình ảnh | Trường hợp | Loại Biến ngẫu nhiên | Nội dung thể hiện |
| :---: | :--- | :---: | :---: | :--- |
| 1 | `fig_error_dist_k01_time_sec.png` | Cách 1 trạm | $\Delta t$ (Thời gian, s) | Bảng phân phối xác suất độ lệch thời gian khi cách 1 trạm |
| 2 | `fig_error_dist_k01_percent.png` | Cách 1 trạm | $\Delta\%$ (Phần trăm, %) | Bảng phân phối xác suất độ lệch phần trăm khi cách 1 trạm |
| 3 | `fig_error_dist_k02_time_sec.png` | Cách 2 trạm | $\Delta t$ (Thời gian, s) | Bảng phân phối xác suất độ lệch thời gian khi cách 2 trạm |
| 4 | `fig_error_dist_k02_percent.png` | Cách 2 trạm | $\Delta\%$ (Phần trăm, %) | Bảng phân phối xác suất độ lệch phần trăm khi cách 2 trạm |
| 5 | `fig_error_dist_k05_time_sec.png` | Cách 5 trạm | $\Delta t$ (Thời gian, s) | Bảng phân phối xác suất độ lệch thời gian khi cách 5 trạm |
| 6 | `fig_error_dist_k05_percent.png` | Cách 5 trạm | $\Delta\%$ (Phần trăm, %) | Bảng phân phối xác suất độ lệch phần trăm khi cách 5 trạm |
| 7 | `fig_error_dist_k10_time_sec.png` | Cách 10 trạm | $\Delta t$ (Thời gian, s) | Bảng phân phối xác suất độ lệch thời gian khi cách 10 trạm |
| 8 | `fig_error_dist_k10_percent.png` | Cách 10 trạm | $\Delta\%$ (Phần trăm, %) | Bảng phân phối xác suất độ lệch phần trăm khi cách 10 trạm |
| 9 | `fig_error_dist_combined_grid_4x2.png` | Cả 4 trường hợp | Ma trận $4 \times 2$ | Dashboard 4 hàng (K=1, 2, 5, 10), 2 cột ($\Delta t$ và $\Delta\%$) |

---

### 3.2. Cấu trúc và Quy chuẩn Kỹ thuật của Biểu đồ (Plotting Specifications)

Mỗi biểu đồ phân phối xác suất phải tuân thủ nghiêm ngặt các tiêu chuẩn đồ họa thống kê sau:

```
+-----------------------------------------------------------------------------------------+
| Tiêu đề: Phân phối Xác suất Độ lệch [Thời gian / Phần trăm] - Trường hợp Cách K Trạm    |
+-----------------------------------------------------------------------------------------+
| Trục Y: Mật độ Xác suất f(x) (hoặc Xác suất %)                                         |
|  ^                                                                                      |
|  |             [Đường 0: Chuẩn mốc]               +----------------------------------+  |
|  |                      |                         | Hộp Thống kê (Stats Box):        |  |
|  |                      |   [Median]              | - Cỡ mẫu N: ...                  |  |
|  |                      |      |   [Mean]         | - Mean: ... (s / %)              |  |
|  |                 ____/ \_____|_____/ \___       | - Std: ... (s / %)               |  |
|  |                /            |           \      | - Median (P50): ... (s / %)      |  |
|  |               /             |            \     | - IQR (P75 - P25): ...           |  |
|  |              /   Histogram  |  với Đường  \    | - Khoảng 80% [P10, P90]: ...     |  |
|  |         ____/    Mật độ     |    KDE       \   | - MAE: ... (s)                   |  |
|  |        /                    |               \  | - % Lệch sớm (< 0): ... %        |  |
|  |  _____/    Vùng Lệch Sớm    |  Vùng Lệch Muộn\_| - % Lệch muộn (> 0): ... %       |  |
|  +-----------------------------+----------------------------------------------------> X  |
|                              x = 0                                                      |
|           <--- LỆCH SỚM (Dấu -)     LỆCH MUỘN (Dấu +) --->                              |
+-----------------------------------------------------------------------------------------+
```

#### 1. Thành phần Dữ liệu Đồ họa:
- **Histogram chuẩn hóa (Normalized Probability Density Histogram):**
  - Số lượng bins cố định: 60 đến 80 bins phân bổ đều trong khoảng quan sát chủ đạo.
  - Chiều cao cột: Thể hiện mật độ xác suất (Probability Density $f(x)$ với $\int f(x)dx = 1$) hoặc tỷ lệ xác suất thực nghiệm ($\%$ quan sát trong mỗi bin).
  - Màu sắc: Xanh lam đậm/xám trung tính có viền mỏng (`edgecolor='white'`, `alpha=0.65`).
- **Đường cong Mật độ Hạt nhân (Kernel Density Estimation - KDE):**
  - Đường cong mượt ước lượng hàm mật độ xác suất liên tục $f(x)$, vẽ đè lên trên histogram với nét đậm (`linewidth=2.2`, màu đỏ son hoặc xanh thẫm).
  - Sử dụng Gaussian Kernel với quy tắc băng thông chuẩn (Scott's Rule hoặc Silverman's Rule).
- **Vạch chỉ chuẩn 0 (Zero Error Line):**
  - Đường thẳng đứng tại $x = 0$ (`linewidth=2.0`, `linestyle='--'`, `color='crimson'` hoặc `black`).
  - Gắn nhãn: `Mốc lý tưởng (0s / 0%)`.
- **Vạch chỉ số Thống kê Trung tâm (Central Tendency Lines):**
  - Đường Median ($P_{50}$): Vạch nét đứt màu xanh dương (`color='#1f77b4'`, `linestyle=':'`, `linewidth=1.8`).
  - Đường Mean ($\mu$): Vạch nét gạch chấm màu cam đậm (`color='#ff7f0e'`, `linestyle='-.'`, `linewidth=1.8`).
- **Dải tin cậy 80% (P10 - P90 Shaded Band):**
  - Vùng diện tích từ phân vị thứ 10 ($P_{10}$) đến phân vị thứ 90 ($P_{90}$) được tô bóng màu nhạt (`alpha=0.15`), làm nổi bật khoảng giá trị mà 80% các chuyến xe thực tế diễn ra.

#### 2. Phân định Miền Trực trực quan ("Lệch sớm" vs. "Lệch muộn"):
- Phía bên trái trục tọa độ ($x < 0$): Ghi rõ nhãn chỉ hướng **"$\leftarrow$ LỆCH SỚM (Xe đến sớm hơn dự báo, dấu $-$)"**.
- Phía bên phải trục tọa độ ($x > 0$): Ghi rõ nhãn chỉ hướng **"LỆCH MUỘN (Xe đến trễ hơn dự báo, dấu $+$) $\rightarrow$"**.

#### 3. Bảng / Hộp Thông tin Thống kê (Info Box / Stats Box):
Mỗi biểu đồ phải chứa một hộp chú thích (Text box góc trên bên phải hoặc vị trí thoáng) bao gồm:
- $N$ (Số lượng quan sát thực tế)
- $\text{Mean} \pm \text{Std}$
- $\text{Median } (P_{50})$
- $\text{IQR } (P_{75} - P_{25})$
- Khoảng $80\%$ độ tin cậy: $[P_{10}, \, P_{90}]$
- $\text{MAE}$ (đối với biểu đồ thời gian) hoặc $\text{WAPE}$ (đối với biểu đồ phần trăm)
- Tỷ lệ lệch sớm ($\Delta < 0$) so với tỷ lệ lệch muộn ($\Delta > 0$).

---

### 3.3. Giới hạn Khoảng Biến thiên (Display Axis Range & Binning Specifications)

Để đảm bảo các biểu đồ ở từng trường hợp $K$ không bị méo mó do ngoại lai, script vẽ đồ thị tuân theo khoảng giá trị trục hoành khuyến nghị sau:

| Trường hợp | Biểu đồ 1: Độ lệch Thời gian $\Delta t$ ($X$-range) | Bin width ($\Delta t$) | Biểu đồ 2: Độ lệch Phần trăm $\Delta\%$ ($X$-range) | Bin width ($\Delta\%$) |
| :---: | :---: | :---: | :---: | :---: |
| **$K = 1$ trạm** | $[-180\text{s}, \, +180\text{s}]$ (hoặc $[-3\text{m}, +3\text{m}]$) | $5\text{s}$ (72 bins) | $[-100\%, \, +100\%]$ | $2.5\%$ (80 bins) |
| **$K = 2$ trạm** | $[-300\text{s}, \, +300\text{s}]$ (hoặc $[-5\text{m}, +5\text{m}]$) | $10\text{s}$ (60 bins) | $[-100\%, \, +100\%]$ | $2.5\%$ (80 bins) |
| **$K = 5$ trạm** | $[-600\text{s}, \, +600\text{s}]$ (hoặc $[-10\text{m}, +10\text{m}]$) | $15\text{s}$ (80 bins) | $[-80\%, \, +80\%]$ | $2.0\%$ (80 bins) |
| **$K = 10$ trạm** | $[-1200\text{s}, \, +1200\text{s}]$ (hoặc $[-20\text{m}, +20\text{m}]$) | $30\text{s}$ (80 bins) | $[-80\%, \, +80\%]$ | $2.0\%$ (80 bins) |

> [!TIP]
> Tỷ lệ các mẫu nằm ngoài giới hạn trục hiển thị (outliers ngoài range) phải được ghi rõ trong góc biểu đồ (ví dụ: `Tỷ lệ bao phủ hiển thị: 98.7%`). Không được loại bỏ các mẫu này khi tính bảng số liệu thống kê.

---

## 4. Thiết kế Bảng Thống kê Sai số Tương ứng (Summary Tables)

Cùng với biểu đồ, hệ thống phải sinh ra hai bảng dữ liệu tổng hợp lưu tại thư mục kết quả đánh giá (`reports/evaluation/ml_error_distribution/` hoặc `docs/figures/ml_evaluation/`).

### Bảng T1: Tổng hợp Tham số Thống kê và Sai số Trung tâm
**Tên file xuất:** `ml_error_distribution_summary_table.csv` và phiên bản hiển thị `ml_error_distribution_summary_table.md`.

Các trường thông tin bắt buộc trong bảng:

| Cột | Tên trường | Đơn vị | Ý nghĩa Nghiệp vụ |
| :--- | :--- | :---: | :--- |
| 1 | `horizon_case` | - | Trường hợp khoảng cách: `K=1`, `K=2`, `K=5`, `K=10` |
| 2 | `sample_count_N` | Mẫu | Số lượng quan sát thực tế trong tập test |
| 3 | `actual_eta_median_sec` | Giây | Trung vị thời gian thực tế để đến trạm mục tiêu |
| 4 | `pred_eta_median_sec` | Giây | Trung vị thời gian ETA dự báo của mô hình ML |
| 5 | `time_error_mean_sec` | Giây | Kỳ vọng toán học $\mathbb{E}[\Delta t]$ (Bias thời gian) |
| 6 | `time_error_std_sec` | Giây | Độ lệch chuẩn $\sigma(\Delta t)$ (Độ bất định thời gian) |
| 7 | `time_error_median_sec` | Giây | Trung vị độ lệch thời gian $\text{Median}(\Delta t)$ |
| 8 | `mae_sec` | Giây | Sai số tuyệt đối trung bình $\text{MAE} = \mathbb{E}[\|\Delta t\|]$ |
| 9 | `medae_sec` | Giây | Trung vị sai số tuyệt đối $\text{MdAE} = \text{Median}(\|\Delta t\|)$ |
| 10 | `pct_error_mean` | $\%$ | Kỳ vọng độ lệch phần trăm $\mathbb{E}[\Delta\%]$ |
| 11 | `pct_error_std` | $\%$ | Độ lệch chuẩn độ lệch phần trăm $\sigma(\Delta\%)$ |
| 12 | `pct_error_median` | $\%$ | Trung vị độ lệch phần trăm $\text{Median}(\Delta\%)$ |
| 13 | `wape_pct` | $\%$ | Sai số phần trăm có trọng số $\text{WAPE} = \frac{\sum \|\Delta t\|}{\sum y} \times 100\%$ |
| 14 | `pct_early_arrivals` | $\%$ | Tỷ lệ các trường hợp xe đến sớm: $\mathbb{P}(\Delta t < 0)$ |
| 15 | `pct_late_arrivals` | $\%$ | Tỷ lệ các trường hợp xe đến trễ: $\mathbb{P}(\Delta t > 0)$ |
| 16 | `within_tolerance_1m_pct` | $\%$ | Tỷ lệ dự báo chuẩn xác trong vòng $\pm 60$ giây: $\mathbb{P}(\|\Delta t\| \le 60\text{s})$ |
| 17 | `within_tolerance_2m_pct` | $\%$ | Tỷ lệ dự báo chuẩn xác trong vòng $\pm 120$ giây: $\mathbb{P}(\|\Delta t\| \le 120\text{s})$ |

---

### Bảng T2: Phân bố Phân vị Đầy đủ (Quantiles & Risk Tail Distribution)
**Tên file xuất:** `ml_error_distribution_quantiles.csv`.

Mỗi trường hợp $K \in \{1, 2, 5, 10\}$ có 2 dòng tương ứng: đại lượng thời gian ($\Delta t$, giây) và đại lượng phần trăm ($\Delta\%$, $\%$).
Các cột phân vị:
- $P_1$ (Đuôi lệch sớm cực đoan 1%)
- $P_5$ (Đuôi lệch sớm 5%)
- $P_{10}$ (Biên sớm 10%)
- $P_{25}$ (Tứ phân vị thứ nhất $Q_1$)
- $P_{50}$ (Trung vị $Q_2$)
- $P_{75}$ (Tứ phân vị thứ ba $Q_3$)
- $P_{90}$ (Biên muộn 90%)
- $P_{95}$ (Đuôi lệch muộn 5%)
- $P_{99}$ (Đuôi lệch muộn cực đoan 1%)
- $\text{IQR} = P_{75} - P_{25}$

---

## 5. Quy trình Tính toán và Tối ưu Bộ nhớ (Execution & Memory Safety Pipeline)

### 5.1. Nguồn Dữ liệu và Mô hình ML Chuẩn tắc
- **Mô hình ML kiểm thử:** `data/models/eta_xgb_global_pruned_r3_big.json` (hoặc `eta_xgb_global_pruned.json` nếu cấu hình mặc định).
- **Metadata đặc trưng:** `data/models/eta_xgb_metadata_and_calibrator_r3_big.json`, trường `pruned_features` (gồm đúng 53 đặc trưng).
- **Tập kiểm thử:** Toàn bộ 47 file Parquet trong:
  `data/lakehouse/gold/eta_feature_store/split=test/route_code=*/part-00000.snappy.parquet`.

### 5.2. Nguyên tắc Không Tràn Bộ nhớ (Memory-Safe Streaming / Batching)
Tập kiểm thử chứa $3,704,820$ dòng với hơn 60 cột. Việc nạp toàn bộ 3.7 triệu dòng cùng lúc vào RAM có thể gây lỗi Out-Of-Memory (OOM).
Quy trình thực thi bắt buộc phải tuân theo cấu trúc xử lý phân tán / lặp qua từng file tuyến:

```text
Khởi tạo cấu trúc lưu trữ kết quả cho 4 tập con:
data_records = {1: [], 2: [], 5: [], 10: []}

Tải mô hình XGBoost và danh sách 53 pruned_features từ metadata JSON.
Duyệt qua danh sách 47 thư mục route_code trong split=test:
    Đọc file part-00000.snappy.parquet của tuyến hiện tại.
    Lọc nhanh các dòng thỏa mãn: n_stations_ahead thuộc {1, 2, 5, 10}.
    Nếu không có dòng nào thỏa mãn: tiếp tục tuyến kế tiếp.
    
    Chuẩn bị ma trận đặc trưng X_test theo chuẩn:
        Ép kiểu category cho ['route_id_idx', 'direction_id', 'day_type', 'hour_slot'].
    Dự báo phần dư: pred_delta = model.predict(X_test)
    Tính ETA dự báo:
        pred_eta = np.maximum(5.0, baseline_eta_p50_sec + pred_delta)
    Lấy giá trị thực tế: actual_eta = actual_eta_sec
    
    Tính toán sai số:
        delta_t = actual_eta - pred_eta
        delta_pct = (actual_eta - pred_eta) / actual_eta * 100.0
        
    Với mỗi k in [1, 2, 5, 10]:
        Lọc các phần tử có n_stations_ahead == k
        Lưu [actual_eta, pred_eta, delta_t, delta_pct] vào data_records[k]

Sau khi duyệt hết 47 tuyến:
    Chuyển data_records[k] thành mảng NumPy / Pandas DataFrame hoàn chỉnh.
    Tính toán bảng thống kê T1 và T2.
    Vẽ và lưu 8 biểu đồ đơn + 1 biểu đồ tổng hợp vào docs/figures/ml_evaluation/.
    Ghi xuất các file CSV và Markdown tương ứng.
```

---

## 6. Cấu trúc Thư mục và File Đầu ra (Output File Structure)

Tất cả các sản phẩm sinh ra phải được đặt đúng vị trí được quy định:

```text
z:\Desktop\Bus_tracking\
├── docs\
│   ├── figures\
│   │   └── ml_evaluation\
│   │       ├── fig_error_dist_k01_time_sec.png       # 300 DPI, PNG
│   │       ├── fig_error_dist_k01_percent.png        # 300 DPI, PNG
│   │       ├── fig_error_dist_k02_time_sec.png       # 300 DPI, PNG
│   │       ├── fig_error_dist_k02_percent.png        # 300 DPI, PNG
│   │       ├── fig_error_dist_k05_time_sec.png       # 300 DPI, PNG
│   │       ├── fig_error_dist_k05_percent.png        # 300 DPI, PNG
│   │       ├── fig_error_dist_k10_time_sec.png       # 300 DPI, PNG
│   │       ├── fig_error_dist_k10_percent.png        # 300 DPI, PNG
│   │       └── fig_error_dist_combined_grid_4x2.png   # 300 DPI, Ma trận 4x2 tổng hợp
│   └── specs\
│       └── 32_ML_EVALUATION_ERROR_DISTRIBUTION_PLOTS_SPEC.md   # Tài liệu này
├── reports\
│   └── evaluation\
│       └── ml_error_distribution\
│           ├── ml_error_distribution_summary_table.csv   # Bảng T1 định dạng CSV
│           ├── ml_error_distribution_summary_table.md    # Bảng T1 định dạng Markdown
│           ├── ml_error_distribution_quantiles.csv       # Bảng T2 phân vị định dạng CSV
│           └── evaluation_run_manifest.json              # Ghi nhận hash model, thời gian chạy, số mẫu
└── module_3_bus_eta_prediction\
    └── step_3_3_machine_learning_models\
        └── plot_eta_error_distributions.py               # Script thực thi do @leaf_coder viết
```

---

## 7. Tiêu chí Nghiệm thu Đo kiểm (Verifiable Acceptance Criteria)

### 7.1. Trách nhiệm của `@leaf_coder`
1. **Không can thiệp logic huấn luyện:** Không sửa đổi, huấn luyện lại mô hình hay thay đổi trọng số trong `data/models/`. Chỉ đọc artifact đã có.
2. **Tuân thủ đúng công thức và quy ước dấu:**
   - $\Delta t = y_{\text{actual}} - \hat{y}_{\text{pred}}$: Đúng quy ước dấu $+$ cho xe đến muộn, dấu $-$ cho xe đến sớm.
   - $\Delta\% = \frac{y_{\text{actual}} - \hat{y}_{\text{pred}}}{y_{\text{actual}}} \times 100\%$: Đúng quy ước dấu $+$ cho lệch muộn, dấu $-$ cho lệch sớm.
3. **Lọc chính xác 4 tập con:** Đảm bảo dữ liệu vẽ biểu đồ lấy đúng từ các dòng `n_stations_ahead == 1`, `== 2`, `== 5`, `== 10`.
4. **Chất lượng đồ họa:** Hình ảnh xuất ra phải đạt chuẩn xuất bản báo cáo (độ phân giải tối thiểu 300 DPI, cỡ chữ rõ ràng, có đầy đủ trục tọa độ, nhãn đơn vị, vạch số 0, vạch median, và hộp thông số thống kê).
5. **Độ an toàn bộ nhớ:** Chạy script lặp theo route batching, không được làm sập bộ nhớ (RAM < 4GB trong suốt quá trình chạy).

### 7.2. Trách nhiệm của `@blind_tester`
Viết bộ kiểm thử độc lập trong `tests/test_ml_error_distribution_plots.py` (hoặc tương đương) mà **hoàn toàn không đọc code của Leaf Coder**, kiểm tra trực tiếp các file kết quả và bảng số liệu theo các bất biến sau:
1. **Kiểm tra sự tồn tại của đầy đủ 9 file ảnh:**
   - Đảm bảo 8 file hình đơn lẻ và 1 file hình tổng hợp tồn tại trong `docs/figures/ml_evaluation/`.
   - Mỗi file ảnh phải có định dạng hợp lệ (PNG header hợp lệ) và dung lượng file không rỗng ($> 50\text{ KB}$).
2. **Kiểm tra tính nhất quán toán học trong Bảng Thống kê (`ml_error_distribution_summary_table.csv`):**
   - Bảng phải có đủ 4 hàng tương ứng với $K \in \{1, 2, 5, 10\}$.
   - Tổng số mẫu của 4 trường hợp phải xấp xỉ $1,085,642$ dòng ($\pm 1\%$).
   - MAE phải tăng dần theo số trạm: $\text{MAE}_{K=1} < \text{MAE}_{K=2} < \text{MAE}_{K=5} < \text{MAE}_{K=10}$.
   - Tỷ lệ đúng giờ trong vòng 1 phút ($\pm 60\text{s}$) phải giảm dần khi số trạm tăng lên: $\text{Accuracy}_{K=1} > \text{Accuracy}_{K=2} > \text{Accuracy}_{K=5} > \text{Accuracy}_{K=10}$.
   - Tổng tỷ lệ $\text{pct\_early\_arrivals} + \text{pct\_late\_arrivals} + \mathbb{P}(\Delta = 0) = 100.0\%$.
3. **Kiểm tra tính đơn điệu của Bảng Phân vị (`ml_error_distribution_quantiles.csv`):**
   - Với mọi dòng trong bảng: $P_{1} \le P_{5} \le P_{10} \le P_{25} \le P_{50} \le P_{75} \le P_{90} \le P_{95} \le P_{99}$.
   - Phân vị $P_{10}$ phải nhỏ hơn 0 (vùng lệch sớm), phân vị $P_{90}$ phải lớn hơn 0 (vùng lệch muộn).

---

## 8. Hướng dẫn Bàn giao (Handover Note)

Tài liệu đặc tả này đã được phê duyệt làm cơ sở kỹ thuật duy nhất cho việc thực thi vẽ biểu đồ phân phối xác suất sai số ML ETA.
- Bước kế tiếp: Chuyển giao đặc tả cho `@leaf_coder` triển khai script thực thi tại `module_3_bus_eta_prediction/step_3_3_machine_learning_models/plot_eta_error_distributions.py`.
- Song song đó: `@blind_tester` chuẩn bị kịch bản kiểm thử độc lập đối chiếu trực tiếp với các tiêu chí nghiệm thu tại Mục 7.2.
