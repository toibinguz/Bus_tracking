# 50. MA TRẬN PHÂN BỔ 48 TUYẾN & QUY TRÌNH QUẢN TRỊ THỰC NGHIỆM
> **Mục tiêu**: Thiết lập khung làm việc tối giản, chuyển giao 48 tuyến xe buýt thành bảng ma trận phân việc thực nghiệm rõ ràng, tích hợp trực tiếp vào **GitHub Projects** và **Obsidian** mà không phát sinh thêm công cụ cồng kềnh.  
> **Căn cứ**: [AGENTS.md](../AGENTS.md) (Hiến pháp tối cao) & [Doc 49](49_HISTORICAL_TRAVEL_TIME_MATRIX_SPECIFICATION_AND_STRATEGY.md).

---

## I. MA TRẬN 48 TUYẾN ĐỐI SOÁT THỰC ĐỊA

Dữ liệu được trích xuất trực tiếp từ Master Ground Truth TimBus và 285.621 pings Frenet 1D thực nghiệm trong cơ sở dữ liệu hệ thống:
*Tệp CSV sẵn sàng nhập vào GitHub Projects / Excel*: [`data/metadata/route_handover_matrix_48.csv`](../data/metadata/route_handover_matrix_48.csv)

### 1. GÓI 1: TUYẾN TRỤC LÕI ĐÔ THỊ (8 Tuyến - Hành lang đông đúc)
| Mã Tuyến | Tên Lộ Trình | Số Trạm (TimBus) | Pings 1D | Trạng Thái | Người Phụ Trách | Ghi Chú Kỹ Thuật |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **01** | Bến xe Gia Lâm - Bến xe Yên Nghĩa | 74 | 3.512 | Sẵn sàng | — | Trục Nguyễn Trãi - Hà Đông |
| **02** | Bác Cổ - Bến xe Yên Nghĩa | 74 | 12.352 | **ĐÃ XONG** | Trưởng nhóm | Golden Route (Mẫu 100%, Dwell: 28.4s) |
| **08A**| Long Biên - Đông Mỹ | 67 | 5.876 | Sẵn sàng | — | Trục Giải Phóng |
| **11** | Công viên Thống Nhất - HV Nông Nghiệp | 55 | 4.423 | Sẵn sàng | — | Trục Gia Lâm |
| **26** | Mai Động - SVĐ Quốc gia | 71 | 8.468 | Sẵn sàng | — | Trục Đại La - Chùa Bộc - Cầu Giấy |
| **27** | Bến xe Yên Nghĩa - Bến xe Nam Thăng Long | 85 | 10.235 | Sẵn sàng | — | Trục vành đai xuyên tâm |
| **31** | Bách Khoa - Chèm (ĐH Mỏ) | 68 | 4.120 | Sẵn sàng | — | Trục Tây Hồ |
| **32** | Bến xe Giáp Bát - Nhổn | 70 | 9.003 | Sẵn sàng | — | Trục Cầu Giấy - Hồ Tùng Mậu |

### 2. GÓI 2: HÀNH LANG VINBUS & BRT (12 Tuyến - Phương tiện hiện đại & làn ưu tiên)
| Mã Tuyến | Tên Lộ Trình | Số Trạm (TimBus) | Pings 1D | Trạng Thái | Người Phụ Trách | Ghi Chú Kỹ Thuật |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **BRT01**| Bến xe Yên Nghĩa - Kim Mã | 45 | 11.204 | Sẵn sàng | — | Làn ưu tiên độc lập, so sánh với tuyến 02 |
| **E01** | Bến xe Mỹ Đình - KĐT Ocean Park | 82 | 8.140 | Sẵn sàng | — | Xe buýt điện VinBus |
| **E02** | Hào Nam - KĐT Ocean Park | 78 | 7.920 | Sẵn sàng | — | Xe buýt điện VinBus |
| **E03** | Cầu Diễn - KĐT Ocean Park | 80 | 7.650 | Sẵn sàng | — | Xe buýt điện VinBus |
| **E04** | KĐT Smart City - Vincom Long Biên | 86 | 6.890 | Sẵn sàng | — | Xe buýt điện VinBus |
| **E05** | Long Biên - Cầu Giấy - KĐT Smart City | 75 | 5.430 | Sẵn sàng | — | Xe buýt điện VinBus |
| **E06** | Bến xe Giáp Bát - KĐT Smart City | 70 | 6.120 | Sẵn sàng | — | Xe buýt điện VinBus |
| **E07** | Long Biên - Bờ Hồ - KĐT Smart City | 68 | 5.980 | Sẵn sàng | — | Xe buýt điện VinBus |
| **E08** | Khu Liên cơ quan Sở ngành - Times City | 74 | 6.210 | Sẵn sàng | — | Xe buýt điện VinBus |
| **E09** | KĐT Smart City - Công viên nước Hồ Tây | 72 | 5.840 | Sẵn sàng | — | Xe buýt điện VinBus |
| **68**  | Hà Đông - Sân bay Nội Bài | 50 | 4.980 | Sẵn sàng | — | Tuyến chất lượng cao |
| **107** | Kim Mã - Làng văn hóa các dân tộc | 110 | 8.418 | Sẵn sàng | — | Cự ly dài Đại lộ Thăng Long |

### 3. GÓI 3: TUYẾN VÀNH ĐAI & KẾT NỐI (14 Tuyến)
| Mã Tuyến | Tên Lộ Trình | Số Trạm | Pings 1D | Trạng Thái | Phụ Trách | Ghi Chú |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **16, 20A, 28, 29, 30, 34, 38, 39, 45, 55A, 60A, 84, 103A, 105** | *Xem chi tiết trong file CSV* | 55 - 94 | 3k - 9k | Sẵn sàng | — | Tuyến chạy qua các trục vành đai 2, 2.5, 3 |

### 4. GÓI 4: TUYẾN NGOẠI THÀNH & LIÊN TỈNH (14 Tuyến)
| Mã Tuyến | Tên Lộ Trình | Số Trạm | Pings 1D | Trạng Thái | Phụ Trách | Ghi Chú |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **05, 07, 101A, 109, 122, 123, 13, 146, 17, 19, 21A, 22A, 35A, 37, 40, 42...** | *Xem chi tiết trong file CSV* | 46 - 141 | 2k - 13k | Sẵn sàng | — | Cự ly dài, vận tốc cao ngoại thành |

---

## II. HƯỚNG DẪN 2 BƯỚC ĐỒNG BỘ CÔNG CỤ QUẢN TRỊ

### Bước 1: Mở và Khai Thác Bằng Obsidian (Dành cho Nghiên Cứu & Docs)
1. Tải và mở **Obsidian**.
2. Chọn **"Open folder as vault"** $\to$ Trỏ tới thư mục `z:\Desktop\Bus_tracking`.
3. Bạn có ngay:
   - Toàn bộ 51 tài liệu kỹ thuật (`docs/00_` đến `docs/50_`) hiển thị gọn gàng.
   - Dùng tính năng **Canvas**: Kéo thả `48_...md`, `49_...md` và các ảnh bản đồ để có sơ đồ trực quan.

### Bước 2: Nhập Bảng Vào GitHub Projects (Dành cho Phân Công Nhóm)
1. Truy cập: `https://github.com/toibinguz/Bus_tracking/projects`.
2. Tạo **New Project** $\to$ Chọn chế độ xem **Table**.
3. Import hoặc paste các cột từ file [`data/metadata/route_handover_matrix_48.csv`](../data/metadata/route_handover_matrix_48.csv).
4. Phân công từng bạn vào cột **Assignee**. Mỗi bạn chạy lệnh trích xuất ma trận theo hướng dẫn trong [Doc 49](49_HISTORICAL_TRAVEL_TIME_MATRIX_SPECIFICATION_AND_STRATEGY.md).
