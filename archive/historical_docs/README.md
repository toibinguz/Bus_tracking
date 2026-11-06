# KHO LƯU TRỮ TÀI LIỆU LỊCH SỬ DỰ ÁN HANOI BUS (HISTORICAL RESEARCH ARCHIVE)

> **Mục đích**: Lưu trữ toàn bộ 62 tài liệu nghiên cứu, khảo sát ban đầu và các báo cáo thử nghiệm từ tháng 10/2026 đến đầu tháng 11/2026.  
> **Nguyên tắc quản trị**: **KHÔNG HARD DELETE**. Toàn bộ tri thức và quá trình tiến hóa của hệ thống được bảo tồn 100% tại đây.

---

## I. CẢNH BÁO QUAN TRỌNG CHO AI VÀ THÀNH VIÊN DỰ ÁN

> [!WARNING]
> **TÀI LIỆU TẠI ĐÂY CHỈ CÓ GIÁ TRỊ LỊCH SỬ VÀ THAM KHẢO HỌC THUẬT.**  
> Nhiều bài toán, trở ngại kỹ thuật hoặc lỗi dữ liệu được ghi nhận trong các tài liệu này (như bài toán ghép nối OSM, lệch pha trạm BusMap, lỗi nhảy cóc trạm, 60 cặp trạm vi phạm đơn điệu, kẹp trần vận tốc 80 km/h) **ĐÃ ĐƯỢC GIẢI QUYẾT TRIỆT ĐỂ** trong mã nguồn Production (`module_1`, `module_2`, `module_3`) và CSDL chuẩn tắc `data/hanoi_bus_system.db`.  
> **TUYỆT ĐỐI KHÔNG SỬ DỤNG CÁC TÀI LIỆU TRONG THƯ MỤC NÀY ĐỂ KẾT LUẬN CÁC NÚT THẮT HIỆN TẠI CỦA DỰ ÁN.**

---

## II. BẢNG PHÂN LOẠI 62 TÀI LIỆU LỊCH SỬ ĐÃ LƯU TRỮ

| Khoảng Tài Liệu | Tên Chủ Đề Giai Đoạn | Nội Dung Lịch Sử | Trạng Thái Hiện Tại Trong Codebase |
| :---: | :--- | :--- | :--- |
| **Doc 00 – 14** | Khảo sát ban đầu & API Crawler (OSM, BusMap, TomTom) | Khảo sát API BusMap, Here Maps, cấu trúc trạm dừng, thử nghiệm socket crawler. | Đã hoàn thành. Tầng crawler 24/7 đã đóng băng trên GitHub Actions. |
| **Doc 15 – 18** | Hạ tầng thu thập đám mây & thiết bị biên | Hướng dẫn triển khai Termux, HuggingFace Spaces, GitHub Actions. | Đang vận hành ổn định 24/7 trên Actions & HF. |
| **Doc 19 – 30** | Thiết kế phân rã module & Thử nghiệm OSM | Kiến trúc modular SRP, schema bảng sơ khởi, kiểm toán dữ liệu OSM. | Đã nâng cấp lên hệ thống 3 module chính tắc và Master TimBus. |
| **Doc 31 – 44** | 5 Trở ngại cốt lõi thời kỳ OSM & Phát hiện TimBus | Ghi nhận lệch pha trạm, trôi dạt GPS, độ trễ mạng, khám phá dữ liệu TimBus / TRAMOC. | Đã giải quyết: Chuẩn hóa Master TimBus (3,646 trạm WGS84, 17,631 điểm tim đường). |
| **Doc 45 – 53** | Chuyển dịch sang Kiến trúc Chính tắc 3 tầng | Di dời BusMap Native, kiểm toán động học 48 tuyến, lưu trữ legacy module. | Đã hoàn thành 100%. `module_1`, `module_2`, `module_3` đã chuẩn hóa. |
| **Doc 54 – 60** | Khảo sát Ma trận phân vị lịch sử & Dị thường ban đầu | Phát hiện 143/60 cặp trạm vi phạm đơn điệu của BusMap cũ, khảo sát dwell time. | Đã chuẩn hóa: `canonical_station_master` hiện tại có 0 cặp trạm vi phạm đơn điệu. |
| **Doc 61** | Lộ trình WBS v2.0 ban đầu | Bản kế hoạch phân rã công việc ban đầu trước khi làm sạch CSDL. | Đã hoàn thành các gói WP 2.1 và WP 2.2. |

---

## III. NƠI TRA CỨU TÀI LIỆU CHÍNH THỨC HIỆN TẠI

Toàn bộ tài liệu chuẩn tắc, phản ánh 100% thực tế hệ thống hiện tại được đặt tại thư mục **`docs/`**:
1. [`docs/00_MASTER_INDEX.md`](../../docs/00_MASTER_INDEX.md): Bản đồ tổng thể toàn bộ dự án.
2. [`docs/01_CANONICAL_ARCHITECTURE_AND_DATABASE_SPEC.md`](../../docs/01_CANONICAL_ARCHITECTURE_AND_DATABASE_SPEC.md): Kiến trúc chính tắc & cấu trúc CSDL hiện tại.
3. [`docs/02_SYSTEM_REALITY_AND_VERIFIED_BASELINE.md`](../../docs/02_SYSTEM_REALITY_AND_VERIFIED_BASELINE.md): Báo cáo kiểm chứng thực địa tự động.
4. [`docs/03_WP21_TOMTOM_MULTI_SOURCE_FUSION_SPEC.md`](../../docs/03_WP21_TOMTOM_MULTI_SOURCE_FUSION_SPEC.md): Đặc tả tích hợp sự cố TomTom v2.0.
5. [`docs/04_WP22_MEDALLION_LAKEHOUSE_AND_WEEKLY_SLA_SPEC.md`](../../docs/04_WP22_MEDALLION_LAKEHOUSE_AND_WEEKLY_SLA_SPEC.md): Đặc tả Medallion Lakehouse Parquet.
6. [`docs/05_WP23_APACHE_SPARK_AND_HADOOP_HDFS_SPEC.md`](../../docs/05_WP23_APACHE_SPARK_AND_HADOOP_HDFS_SPEC.md): Đặc tả Spark & Cụm HDFS phân tán.
7. [`docs/06_ACTIONABLE_ROADMAP_DEMO_FIRST.md`](../../docs/06_ACTIONABLE_ROADMAP_DEMO_FIRST.md): Lộ trình hành động (Demo First $\to$ HDFS $\to$ Spark).
