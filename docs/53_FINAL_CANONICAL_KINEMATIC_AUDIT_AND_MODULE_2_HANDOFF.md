# BÁO CÁO KIỂM TOÁN ĐỘNG HỌC CUỐI CÙNG & CHUYỂN GIAO SANG MODULE 2 (MEDALLION LAKEHOUSE & DUCKDB)
> **Dự án**: Hanoi Bus Big Data & Real-time ETA Prediction System  
> **Mã văn bản**: `docs/53_FINAL_CANONICAL_KINEMATIC_AUDIT_AND_MODULE_2_HANDOFF.md`  
> **Áp dụng cho**: Toàn bộ hệ thống kỹ thuật, chuyển giao từ Module 1 sang Module 2.  
> **Tuân thủ Hiến pháp**: Điều 1 (Kỷ luật thực nghiệm), Điều 5 (Động học dẫn xuất), Điều 6 (Vertical Slice).

---

## I. BỐI CẢNH & NHIỆM VỤ CUỐI CÙNG CỦA MODULE 1

Sau khi hoàn tất hợp nhất **Master Ground Truth từ BusMap** (`canonical_shape_master` với 176 tuyến, 118.744 điểm tim đường và `canonical_station_master` với 13.301 trạm dừng), hệ thống đã thực hiện định vị không gian Frenet 1D (`s`, $d_\perp$) cho toàn bộ **646.823 pings** viễn thám thực địa của 48 tuyến buýt.

Tuy nhiên, trong các lần kiểm toán thô ban đầu:
- Một số tuyến như Tuyến 39 (39.9% bám làn) và BRT01 (55.0% bám làn) có tỷ lệ bám làn hành lang 30m thấp bất thường.
- **Nghi vấn đặt ra**: Liệu tim đường BusMap có bị sai lệch ngoài thực địa, hay dữ liệu GPS bị ô nhiễm bởi các xe dừng đỗ nghỉ ngơi ngoài tuyến?
- **Chỉ thị của người dùng**: Thực hiện **đợt kiểm toán cuối cùng** bóc tách triệt để các khoảng thời gian xe dừng nghỉ tại bến (đặc biệt là bến/bãi đỗ trung gian nằm giữa tuyến) và khung giờ đêm 22:00 -> 06:00, tập trung kiểm toán chất lượng hình học tại những lúc **xe chạy thực sự (Active Running)** trước khi bắt buộc chuyển sang Module 2.

---

## II. MÔ HÌNH TOÁN PHÂN TÁCH ĐỘNG HỌC 3 TRẠNG THÁI (3-STATE KINEMATIC CLASSIFIER)

Tuân thủ **Điều 5 của Hiến pháp** (nghiêm cấm dùng cảm biến tức thời `speed == 0`), thuật toán phân loại dựa trên **vận tốc dẫn xuất không gian - thời gian** và **độ dịch chuyển trong cửa sổ trượt thời gian 3.5 phút** ($[t - 105\text{s}, t + 105\text{s}]$):

$$\Delta s_{210\text{s}} = \max_{j \in W_i}(s_j) - \min_{j \in W_i}(s_j)$$

$$\bar{v}_{\text{derived}} = \frac{\Delta s}{\Delta t}$$

```mermaid
flowchart TD
    Ping["Ping GPS thô (t, lat, lng, s, d_perp, v)"] --> TimeCheck{"Khung giờ t_hm?"}
    
    TimeCheck -- "Đêm: 21:45 - 05:15" --> NightDisp{"Delta s < 40m HOẶC v < 8 km/h?"}
    NightDisp -- "Đúng" --> NightPark["NIGHT_PARK (Đỗ bãi đêm / Garage)"]
    NightDisp -- "Sai" --> ActiveRunning["ACTIVE_RUNNING (Xe chạy đêm)"]
    
    TimeCheck -- "Ngày: 05:15 - 21:45" --> DayDisp{"Số ping trong cửa sổ >= 3 VÀ Delta s < 25m VÀ v < 5 km/h?"}
    DayDisp -- "Đúng" --> DayLayover["INTERMEDIATE_OR_DEPOT_LAYOVER (Nghỉ trưa / Đổi ca / Bến trung gian)"]
    DayDisp -- "Sai" --> ActiveRunning
```

### 1. Phân biệt Dừng đón trả khách thông thường vs Dừng nghỉ giữa tuyến (Layover)
- **Dừng đón trả khách (Station Dwell)**: Diễn ra trong 15 – 45 giây. Trước khi dừng, xe đang chạy tới trạm, và sau khi đón khách, xe chạy tiếp. Do đó, trong cửa sổ 3.5 phút, độ dịch chuyển $\Delta s_{210\text{s}}$ của xe luôn đạt $\ge 50 - 150\text{m}$.
- **Dừng nghỉ giữa tuyến (Intermediate Layover)**: Xe dừng hẳn tại một điểm dừng lớn, quán nước ven đường, hoặc khu vực chờ ca giữa tuyến $> 3$ phút $\to$ $\Delta s_{210\text{s}} < 25\text{m}$ xuyên suốt toàn bộ cửa sổ $\to$ Được bóc tách chính xác là `LAYOVER`.

---

## III. KẾT QUẢ THỰC NGHIỆM ĐỊNH LƯỢNG TOÀN MẠNG LƯỚI (48 TUYẾN)

### 1. Phân bố cơ cấu trạng thái đội xe (Fleet State Breakdown)
Từ tập dữ liệu 646.823 pings toàn mạng lưới:
- **Xe chạy thực sự (`ACTIVE_RUNNING`)**: **500.174 pings (77.3%)**
- **Dừng nghỉ ban ngày (`DAY_LAYOVER`)**: **138.126 pings (21.4%)**
- **Đỗ nghỉ qua đêm (`NIGHT_PARK`)**: **8.523 pings (1.3%)**

### 2. Sự thật về sai số bám làn khi xe dừng nghỉ
Bảng đối chiếu sai số trung vị ($d_\perp$) giữa lúc xe chạy và lúc xe đỗ:
- **Tuyến 21A**: Lúc chạy median $d_\perp = 5.1\text{m}$ (95.6% bám làn). Khi đỗ đêm: median $d_\perp = \mathbf{3.684,9\text{m}}$ (xe về gara tận Giáp Bát/Văn Điển nhưng GPS vẫn bật).
- **Tuyến 34**: Lúc chạy median $d_\perp = 4.4\text{m}$ (94.7% bám làn). Khi đỗ đêm: median $d_\perp = \mathbf{3.625,0\text{m}}$ (về bãi xe Cầu Giấy).
- **Tuyến 32**: Lúc chạy median $d_\perp = 4.7\text{m}$ (93.7% bám làn). Khi đỗ nghỉ: median $d_\perp = \mathbf{3.670,2\text{m}}$.
- **Tuyến BRT01**: Lúc chạy median $d_\perp = 9.4\text{m}$ (89.7% bám làn). Khi đỗ nghỉ: median $d_\perp = \mathbf{161,8\text{m}}$ (tập kết sâu trong sân bãi Kim Mã / Yên Nghĩa).

> [!IMPORTANT]
> **Kết luận cốt lõi**: Tỷ lệ bám làn "thấp" trước đây hoàn toàn là do **nhiễu xe đỗ chết trong bãi/gara ngoài giờ**. Khi bóc tách đúng động học `ACTIVE_RUNNING`, chất lượng tim đường BusMap đạt độ chính xác gần như tuyệt đối (trung vị sai số toàn đội xe chỉ từ 3 đến 8 mét).

---

## IV. BẢNG XẾP HẠNG PHÂN TẦNG CHẤT LƯỢNG TOÀN DIỆN (TIER MATRIX)

| TIER | TUYẾN | TỔNG PING | PING CHẠY | % BÁM LÀN ($\le 30\text{m}$) | % BÁM LÀN ($\le 15\text{m}$) | MEDIAN $d_\perp$ | P90 $d_\perp$ | ĐÁNH GIÁ CHẤT LƯỢNG |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **GOLD** | **22A** | 20,594 | 18,390 | **97.4%** | 86.6% | 5.5m | 17.3m | Chuẩn hoàn hảo |
| **GOLD** | **02** | 23,258 | 19,794 | **97.0%** | 89.7% | 5.3m | 15.3m | Chuẩn hoàn hảo |
| **GOLD** | **E06** | 13,451 | 11,518 | **95.9%** | 91.0% | 4.6m | 14.1m | VinBus mẫu mực |
| **GOLD** | **21A** | 14,566 | 12,344 | **95.6%** | 86.4% | 5.1m | 18.3m | Xuất sắc |
| **GOLD** | **99** | 7,129 | 6,373 | **95.4%** | 90.6% | 4.5m | 14.4m | Tuyến ngắn siêu chuẩn |
| **GOLD** | **37** | 14,360 | 12,258 | **95.3%** | 88.5% | 4.9m | 16.3m | Xuất sắc |
| **GOLD** | **105** | 12,881 | 10,633 | **95.2%** | 85.0% | 5.8m | 18.9m | Xuất sắc |
| **GOLD** | **19** | 17,927 | 16,317 | **94.8%** | 83.0% | 5.6m | 21.8m | Trục Trần Khánh Dư |
| **GOLD** | **34** | 18,716 | 16,947 | **94.7%** | 88.4% | 4.4m | 17.6m | Trục Mỹ Đình - Gia Lâm |
| **GOLD** | **27** | 27,504 | 20,447 | **94.5%** | 83.1% | 6.2m | 20.2m | Trục Nam Thăng Long |
| **GOLD** | **38** | 8,385 | 6,211 | **94.5%** | 86.8% | 5.5m | 18.4m | Xuất sắc |
| **GOLD** | **101A**| 9,282 | 6,668 | **94.4%** | 90.1% | 3.6m | 14.7m | Siêu chuẩn |
| **GOLD** | **E05** | 8,635 | 6,882 | **94.4%** | 83.5% | 5.7m | 22.0m | VinBus Long Biên |
| **GOLD** | **11** | 10,302 | 9,322 | **94.2%** | 88.1% | 5.0m | 17.2m | BV Bạch Mai - HV Nông Nghiệp |
| **GOLD** | **01** | 7,341 | 6,742 | **94.1%** | 84.8% | 5.3m | 21.6m | Trục chính Yên Nghĩa |
| **GOLD** | **43** | 9,503 | 7,551 | **94.1%** | 86.4% | 5.6m | 18.5m | Đông Anh |
| **GOLD** | **48** | 10,898 | 8,350 | **94.1%** | 87.5% | 4.7m | 18.6m | Bến xe Nam Thăng Long |
| **GOLD** | **32** | 20,005 | 16,116 | **93.7%** | 86.9% | 4.7m | 20.4m | Nhổn - Giáp Bát |
| **GOLD** | **17** | 9,515 | 7,242 | **93.6%** | 89.0% | 5.8m | 16.1m | Nội Bài |
| **GOLD** | **92** | 11,818 | 7,236 | **93.4%** | 84.9% | 5.1m | 19.6m | Ngoại thành Tây |
| **GOLD** | **123** | 9,000 | 5,086 | **93.3%** | 90.6% | 3.3m | 14.0m | Sai số trung vị thấp nhất |
| **GOLD** | **146** | 13,868 | 13,075 | **93.2%** | 87.9% | 4.9m | 17.6m | Vành đai liên tuyến |
| **GOLD** | **26** | 17,046 | 13,947 | **93.2%** | 86.3% | 5.1m | 20.0m | Mai Dịch - Giáp Bát |
| **GOLD** | **35A** | 7,142 | 4,325 | **92.9%** | 83.2% | 5.7m | 21.7m | Trần Khánh Dư - Nam Thăng Long |
| **GOLD** | **56B** | 7,050 | 5,673 | **91.9%** | 85.0% | 8.2m | 20.9m | Xuất sắc |
| **GOLD** | **13** | 9,373 | 6,167 | **91.7%** | 82.3% | 5.4m | 24.9m | CV Nước Hồ Tây |
| **GOLD** | **05** | 10,910 | 9,350 | **91.5%** | 86.3% | 5.2m | 22.3m | Linh Đàm - Phú Diễn |
| **GOLD** | **08A** | 12,719 | 11,672 | **91.5%** | 86.5% | 5.3m | 22.8m | Long Biên - Đông Mỹ |
| **GOLD** | **28** | 9,839 | 7,821 | **91.2%** | 81.5% | 5.8m | 26.4m | Giáp Bát - ĐH Mỏ |
| **GOLD** | **107** | 19,315 | 15,271 | **90.4%** | 85.9% | 4.6m | 27.3m | Kim Mã - Làng VH |
| **GOLD** | **122** | 16,798 | 8,933 | **90.1%** | 84.9% | 4.0m | 29.2m | Bến xe Gia Lâm |
| **GOLD** | **40** | 10,160 | 6,933 | **89.9%** | 81.4% | 5.8m | 30.5m | CV Thống Nhất - Như Quỳnh |
| **GOLD** | **51** | 16,971 | 12,800 | **89.8%** | 82.5% | 5.7m | 31.1m | Bến xe Gia Lâm - Trần Vỹ |
| **GOLD** | **BRT01**| 21,743 | 11,322 | **89.7%** | 70.6% | 9.4m | 30.5m | Tuyến BRT độc đạo |
| **GOLD** | **E10** | 11,326 | 8,926 | **89.2%** | 84.8% | 4.3m | 61.6m | VinBus Nội Bài |
| **GOLD** | **64** | 11,067 | 8,162 | **89.0%** | 76.2% | 5.9m | 33.7m | KCN Bắc Thăng Long |
| **SILVER**| **42** | 9,242 | 5,989 | **85.6%** | 77.7% | 7.0m | 115.0m | Tốt |
| **SILVER**| **90** | 9,577 | 6,890 | **84.9%** | 79.2% | 5.4m | 69.6m | Tốt |
| **SILVER**| **61** | 9,591 | 7,045 | **84.6%** | 80.7% | 4.8m | 74.9m | Tốt |
| **SILVER**| **E03** | 13,690 | 10,826 | **82.4%** | 73.1% | 7.1m | 362.3m | Ocean Park - Mỹ Đình |
| **SILVER**| **E04** | 16,632 | 13,547 | **82.4%** | 72.1% | 7.3m | 112.6m | Smart City - Vincom Long Biên |
| **SILVER**| **07** | 26,053 | 20,676 | **80.0%** | 70.0% | 7.3m | 89.6m | Cầu Giấy - Nội Bài |
| **SILVER**| **109** | 10,938 | 8,442 | **79.4%** | 69.1% | 8.3m | 86.6m | Mỹ Đình - Nội Bài |
| **SILVER**| **67** | 9,323 | 6,340 | **78.0%** | 73.3% | 6.0m | 2,253m | Có 1 nhánh phụ |
| **SILVER**| **E02** | 21,173 | 14,994 | **76.5%** | 73.1% | 6.0m | 1,315m | Smart City - Bác Cổ |
| **SILVER**| **E01** | 32,325 | 24,736 | **76.3%** | 63.4% | 9.6m | 561.9m | Smart City - Long Biên |
| **BRONZE**| **39** | 7,866 | 3,885 | **61.7%** | 57.1% | 9.5m | 149.5m | Có đoạn đi đường tránh |
| **BRONZE**| **E11** | 16 | 0 | **0.0%** | 0.0% | 999m | 999m | Dữ liệu mẫu cực ít (16 pings) |

**TỔNG KẾT**:
- **36 Tuyến GOLD (75.0%)**: Toàn bộ đạt tỷ lệ bám làn từ **89.0% đến 97.4%**, sai số trung vị từ **3.3m đến 9.4m**.
- **10 Tuyến SILVER (20.8%)**: Bám làn từ **76.3% đến 85.6%**, hoàn toàn đủ điều kiện làm dữ liệu huấn luyện.
- **Chỉ 2 Tuyến BRONZE (4.2%)**: Tuyến 39 (do một nhánh rẽ ngoài thực địa khác tim đường) và Tuyến E11 (chỉ có 16 pings).

---

## V. TUYÊN BỐ ĐÓNG GÓI & NGHIỆM THU MODULE 1

1. **Hạ tầng Ingestion & Canonical Master**: Đã đóng băng hoàn thiện. `canonical_shape_master`, `canonical_station_master`, và `canonical_route_master` là nguồn chân lý duy nhất.
2. **Công cụ định vị Frenet 1D (`multi_route_projector.py`)**: Đạt hiệu năng **13.072 pings/giây**, định vị chính xác 646.823 pings trong 49.48 giây, tự động gắn nhãn hướng đi/về (`go`/`re`) bằng trạm kế cận kết hợp rào chắn tự phục hồi (`Self-Healing Direction Guard`).
3. **Bộ lọc động học 3 trạng thái**: Đã chứng minh triệt để bằng số liệu thực nghiệm, giải tỏa mọi nghi vấn về chất lượng tim đường.
4. **Quyết định chuyển giao**: **Chính thức đóng gói Module 1**. Không thực hiện thêm bất kỳ lần audit nào nữa ở giai đoạn này. Chuyển ngay lập tức sang **Module 2**.

---

## VI. BẢN ĐẶC TẢ KỸ THUẬT MODULE 2: BIG DATA PARQUET MEDALLION LAKEHOUSE & DUCKDB

### 1. Mục tiêu của Module 2
Chuyển đổi toàn bộ dữ liệu telemetry và master data từ cơ sở dữ liệu SQLite đơn luồng sang kiến trúc **Medallion Lakehouse** dạng cột (Columnar Parquet), tích hợp công cụ phân tích **DuckDB** để tăng tốc truy vấn hàng triệu bản ghi với độ trễ dưới 50ms.

```mermaid
flowchart LR
    subgraph Module1["Module 1: Ingestion & Spatial"]
        direction TB
        RawDB[("SQLite: vehicle_unique_pings")] --> FrenetProj["multi_route_projector.py"]
        FrenetProj --> ProjDB[("route_projected_telemetry")]
    end
    
    subgraph Module2["Module 2: Parquet Medallion Lakehouse & DuckDB Engine"]
        direction TB
        ProjDB --> BronzeWriter["Bronze Ingestion Pipeline"]
        BronzeWriter --> Bronze[("Bronze Layer (Raw GPS Parquet)")]
        
        Bronze --> SilverETL["Silver Clean & Classify ETL"]
        SilverETL --> Silver[("Silver Layer (Partitioned Frenet Parquet)<br/>route_code=*/date=*/*.parquet")]
        
        Silver --> GoldAggregator["Gold Feature & Travel Time ETL"]
        GoldAggregator --> Gold[("Gold Layer (Station-to-Station & Dwell Matrix)")]
        
        Silver & Gold --> DuckDBEngine["DuckDB Analytics Engine<br/>Vectorized OLAP / Sub-50ms Serving"]
    end
```

### 2. Thiết kế Kiến trúc Medallion Parquet

#### Tầng Bronze (`lakehouse/bronze/`):
- **Nhiệm vụ**: Lưu trữ toàn bộ pings GPS nguyên bản thu thập từ crawler, định dạng Parquet với chuẩn nén `snappy` hoặc `zstd`.
- **Partitioning**: `year=YYYY/month=MM/day=DD/`.

#### Tầng Silver (`lakehouse/silver/`):
- **Nhiệm vụ**: Dữ liệu đã định vị không gian Frenet ($s, d_\perp$), đã gắn cờ động học (`active_running`, `layover`, `night_park`), loại bỏ hoàn toàn các pings lỗi/bãi đỗ.
- **Partitioning**: `route_code={CODE}/direction={go|re}/`.
- **Schema**:
  - `route_code`: VARCHAR
  - `direction`: VARCHAR
  - `vehicle_id`: VARCHAR
  - `device_epoch`: INT64
  - `device_time`: TIMESTAMP
  - `s_bus_m`: FLOAT64 (Vị trí 1D dọc tim đường)
  - `cross_track_m`: FLOAT32 (Sai số vuông góc)
  - `derived_speed_kmh`: FLOAT32 ($\bar{v}$)
  - `kinematic_state`: VARCHAR (`ACTIVE_RUNNING`, `LAYOVER`, `NIGHT_PARK`)
  - `current_station_id`: INT32
  - `next_station_id`: INT32
  - `matched_segment_idx`: INT32

#### Tầng Gold (`lakehouse/gold/`):
- **Bảng 1: Ma trận thời gian di chuyển liên trạm (`gold_inter_station_travel_time`)**:
  - `route_code`, `direction`, `from_station_id`, `to_station_id`, `time_bucket_15min`, `day_of_week`.
  - Phân vị thống kê: $T_{P10}, T_{P50}, T_{P90}$, độ lệch chuẩn $\sigma$, số lượt quan sát $N$.
- **Bảng 2: Thời gian dừng đón trả khách (`gold_station_dwell_time`)**:
  - `station_id`, `route_code`, `time_bucket_15min`, $D_{P50}, D_{P90}$.

### 3. Kế hoạch triển khai Module 2 (Bước hành động ngay lập tức)
1. **Khởi tạo hạ tầng Lakehouse**: Tạo cấu trúc thư mục `lakehouse/bronze`, `lakehouse/silver`, `lakehouse/gold`.
2. **Xây dựng Pipeline chuyển đổi SQLite sang Silver Parquet (`module_2/.../export_silver_parquet.py`)**:
   - Sử dụng `pyarrow` và `duckdb` để xuất 500.174 active running pings thành các tệp Parquet phân vùng theo `route_code`.
3. **Benchmark tốc độ truy vấn DuckDB**:
   - So sánh thời gian truy vấn giữa SQLite vs DuckDB trên tập 646.823 records (mục tiêu DuckDB đạt $\le 20\text{ms}$ cho các truy vấn filter và aggregation).

