# KHO LƯU TRỮ TÀI LIỆU LỊCH SỬ DỰ ÁN HANOI BUS (HISTORICAL RESEARCH ARCHIVE)

> **Mục đích**: Lưu trữ toàn bộ 66 tài liệu nghiên cứu, khảo sát ban đầu và các báo cáo thử nghiệm từ giai đoạn đầu (tháng 10/2026 đến đầu tháng 11/2026, từ Doc 00 đến Doc 65).  
> **Nguyên tắc quản trị**: **KHÔNG HARD DELETE**. Toàn bộ tri thức và quá trình tiến hóa của hệ thống được bảo tồn 100% tại đây nhằm tránh quán tính nhận thức và các giả định lỗi thời.

---

## I. CẢNH BÁO QUAN TRỌNG CHO AI VÀ THÀNH VIÊN DỰ ÁN

> [!WARNING]
> **TÀI LIỆU TẠI ĐÂY CHỈ CÓ GIÁ TRỊ LỊCH SỬ VÀ THAM KHẢO HỌC THUẬT.**  
> Nhiều bài toán, trở ngại kỹ thuật hoặc lỗi dữ liệu được ghi nhận trong các tài liệu này (như bài toán ghép nối OSM, lệch pha trạm BusMap, lỗi nhảy cóc trạm, 60 cặp trạm vi phạm đơn điệu, kẹp trần vận tốc 80 km/h) **ĐÃ ĐƯỢC GIẢI QUYẾT TRIỆT ĐỂ** trong mã nguồn Production (`module_1`, `module_2`, `module_3`) và CSDL chuẩn tắc `data/hanoi_bus_system.db`.  
> **TUYỆT ĐỐI KHÔNG SỬ DỤNG CÁC TÀI LIỆU TRONG THƯ MỤC NÀY ĐỂ KẾT LUẬN CÁC NÚT THẮT HIỆN TẠI CỦA DỰ ÁN.**  
> **Nguồn chân lý thực nghiệm duy nhất hiện tại**: Chạy `scripts/verify_system_reality.py` để lấy trạng thái thực tế tức thời của cơ sở dữ liệu và lakehouse.

---

## II. BẢNG PHÂN LOẠI 66 TÀI LIỆU LỊCH SỬ ĐÃ LƯU TRỮ (DOC 00 – 65)

| Khoảng Tài Liệu | Tên Chủ Đề Giai Đoạn | Nội Dung Lịch Sử | Trạng Thái Hiện Tại Trong Codebase |
| :---: | :--- | :--- | :--- |
| **Doc 00 – 14** | Khảo sát ban đầu & API Crawler (OSM, BusMap, TomTom) | Khảo sát API BusMap, Here Maps, cấu trúc trạm dừng, thử nghiệm socket crawler. | Đã hoàn thành. Tầng crawler 24/7 đã đóng băng trên GitHub Actions. |
| **Doc 15 – 18** | Hạ tầng thu thập đám mây & thiết bị biên | Hướng dẫn triển khai Termux, HuggingFace Spaces, GitHub Actions. | Đang vận hành ổn định 24/7 trên Actions & HF. |
| **Doc 19 – 30** | Thiết kế phân rã module & Thử nghiệm OSM | Kiến trúc modular SRP, schema bảng sơ khởi, kiểm toán dữ liệu OSM. | Đã nâng cấp lên hệ thống 3 module chính tắc và Master TimBus. |
| **Doc 31 – 44** | 5 Trở ngại cốt lõi thời kỳ OSM & Phát hiện TimBus | Ghi nhận lệch pha trạm, trôi dạt GPS, độ trễ mạng, khám phá dữ liệu TimBus / TRAMOC. | Đã giải quyết: Chuẩn hóa Master TimBus (3,646 trạm WGS84, 17,631 điểm tim đường). |
| **Doc 45 – 53** | Chuyển dịch sang Kiến trúc Chính tắc 3 tầng | Di dời BusMap Native, kiểm toán động học 48 tuyến, lưu trữ legacy module. | Đã hoàn thành 100%. `module_1`, `module_2`, `module_3` đã chuẩn hóa. |
| **Doc 54 – 60** | Khảo sát Ma trận phân vị lịch sử & Dị thường ban đầu | Phát hiện 143/60 cặp trạm vi phạm đơn điệu của BusMap cũ, khảo sát dwell time. | Đã chuẩn hóa: `canonical_station_master` hiện tại có 0 cặp trạm vi phạm đơn điệu. |
| **Doc 61 – 65** | Kế hoạch WBS v2.0, TomTom v2.0, Lakehouse & Lộ trình cũ | Báo cáo thử nghiệm TomTom (Doc 62), Medallion Lakehouse (Doc 63), PySpark Spec (Doc 64), và phân tích điểm nghẽn (Doc 65). | Lưu trữ lịch sử. Toàn bộ trọng tâm chuyển sang triển khai sản phẩm thực tế (Demo First & Hadoop HDFS). |

---

## III. NGUYÊN TẮC QUẢN TRỊ MỚI: EMPIRICAL CODE-FIRST

Kể từ thời điểm này:
1. Mọi tài liệu cũ đã được cách ly trong thư mục này.
2. Thư mục `docs/` được làm sạch hoàn toàn để chuẩn bị cho tài liệu phát triển giai đoạn mới (Phase 3).
3. Hệ thống chỉ tin vào dữ liệu thực nghiệm kiểm chứng qua mã nguồn và trạng thái vận hành thực tế.
