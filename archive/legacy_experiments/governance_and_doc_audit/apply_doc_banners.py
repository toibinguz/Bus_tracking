import os
import sys

if sys.stdout.encoding != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

CLASSIFICATIONS = {
    # DEPRECATED OSM (Falsely claimed OSM was ground truth)
    "26_GROUND_TRUTH_ROUTE_AND_STATION_DETERMINATION_METHODOLOGY.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - OSM IS NOT GROUND TRUTH)",
        "reason": "Tài liệu này từng coi OpenStreetMap (OSM) là 'Ground Truth'. Phương pháp này ĐÃ BỊ BÃI BỎ HOÀN TOÀN do OSM thiếu trạm, sai thứ tự và không phải dữ liệu chính thức. Cơ sở dữ liệu gốc chính thức của nhà nước là TimBus (TRAMOC / Sở GTVT Hà Nội) tại Doc 39.",
        "successor": "39_MASTER_GROUND_TRUTH_TIMBUS_SPECIFICATION.md"
    },
    "30_OSM_TELEMETRY_FUSION_AND_AUDIT.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - OSM FUSION)",
        "reason": "Hợp nhất telemetry trên nền OSM cũ đã bị bãi bỏ. Hệ thống hiện tại chiếu tọa độ Frenet 1D trực tiếp lên tim đường TimBus.",
        "successor": "37_FRENET_PROJECTION_AND_EMPIRICAL_SPATIAL_EVALUATION.md"
    },
    "32_STATION_UNIFICATION_AND_DISCREPANCY_ANALYSIS.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - OSM DISCREPANCY)",
        "reason": "Phân tích sai lệch giữa BusMap và OSM cũ. Đã được kế thừa và giải quyết dứt điểm khi đưa TimBus vào làm Master Ground Truth.",
        "successor": "38_TIMBUS_VS_BUSMAP_IDENTIFIER_MAPPING.md"
    },

    # DEPRECATED TOMTOM FLOW
    "02_TOMTOM_TWO_TIER_TRAFFIC_OPTIMIZATION.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - TOMTOM FLOW RETIRED)",
        "reason": "Mô hình 2 tầng TomTom Flow + Incidents đã bị bãi bỏ. TomTom Flow (19 nút tĩnh) bị loại bỏ 100% trong config/system_config.py do lãng phí quota và không phản ánh dòng xe dùng chung. Hệ thống chỉ giữ lại TomTom Incidents (80 req/ngày).",
        "successor": "44_DELTA_T_AND_DELTA_M_DUAL_PATTERN_ANALYSIS.md"
    },
    "09_TOMTOM_FLOW_INTERPOLATION_THEORY.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - FLOW INTERPOLATION)",
        "reason": "Lý thuyết nội suy TomTom Flow không còn sử dụng do đã loại bỏ hoàn toàn TomTom Flow khỏi hệ thống.",
        "successor": "49_HISTORICAL_TRAVEL_TIME_MATRIX_SPECIFICATION_AND_STRATEGY.md"
    },
    "10_TOMTOM_EMPIRICAL_VALIDATION_REPORT.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - FLOW VALIDATION)",
        "reason": "Báo cáo thử nghiệm TomTom Flow trên 19 nút cũ. Đã bãi bỏ việc dùng Flow.",
        "successor": "44_DELTA_T_AND_DELTA_M_DUAL_PATTERN_ANALYSIS.md"
    },
    "12_HERE_API_FREE_PLAN_EXPLOITATION_STRATEGY.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - HERE API REJECTED)",
        "reason": "Ý tưởng dùng HERE API đã bị bác bỏ hoàn toàn, không đưa vào mã nguồn sản xuất.",
        "successor": "47_CANONICAL_MODULE_STANDARDIZATION_AND_LEGACY_ARCHIVING.md"
    },
    "13_CONGESTION_COVERAGE_CAPACITY_ANALYSIS.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - CONGESTION COVERAGE)",
        "reason": "Phân tích năng lực vùng phủ TomTom Flow cũ, không còn áp dụng.",
        "successor": "config/system_config.py"
    },
    "14_HUST_CLUSTER_ROUTES_SELECTION_AND_SPATIAL_FEASIBILITY.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - 19 ROUTES SCOPE)",
        "reason": "Phạm vi 19 tuyến cụm Bách Khoa ban đầu đã được mở rộng thành 48 tuyến toàn mạng lưới Hà Nội.",
        "successor": "50_PROJECT_MANAGEMENT_AND_ROUTE_HANDOVER_MATRIX.md"
    },

    # DEPRECATED 5-MODULE ARCHITECTURE
    "19_WORKSPACE_MODULAR_ARCHITECTURE_AND_SRP.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - 5 MODULE ARCHITECTURE)",
        "reason": "Kiến trúc 5 module cũ (module_1 đến module_5) đã bị bãi bỏ và lưu trữ vào archive/legacy_modules/. Hệ thống hiện tại chuẩn hóa duy nhất 3 Module chính tắc.",
        "successor": "47_CANONICAL_MODULE_STANDARDIZATION_AND_LEGACY_ARCHIVING.md"
    },
    "20_DATA_PROCESSING_AND_ETA_PIPELINE_ROADMAP.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - OLD PIPELINE ROADMAP)",
        "reason": "Lộ trình kỹ thuật thời kỳ 5 module cũ. Đã được thay thế bằng Lộ trình 5 Trụ cột hiện hành.",
        "successor": "48_COMPREHENSIVE_REMAINING_TASKS_AND_SYSTEM_ROADMAP.md"
    },
    "21_SEGMENTATION_AND_FEATURE_ENGINEERING_SPECIFICATION.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - OLD FEATURE SPEC)",
        "reason": "Đặc tả đặc trưng phân mảnh thời 5 module cũ. Hiện tại Feature Store và Ma trận thời gian được tổ chức tập trung trong module_3.",
        "successor": "49_HISTORICAL_TRAVEL_TIME_MATRIX_SPECIFICATION_AND_STRATEGY.md"
    },
    "24_ML_CORE_BACKBONE_ARCHITECTURE.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - PREMATURE DEEP LEARNING)",
        "reason": "Đề xuất nhảy cóc vào Deep Learning / Multi-modal ML sớm trước khi có dữ liệu cơ sở. Đã được điều chỉnh: Tạm hoãn ML, hoàn thành Ma trận thời gian di chuyển phân đoạn (Travel Time Matrix) trước.",
        "successor": "49_HISTORICAL_TRAVEL_TIME_MATRIX_SPECIFICATION_AND_STRATEGY.md"
    },
    "28_DATA_CLEANING_AND_FUSION_PIPELINE_SPECIFICATION.md": {
        "type": "WARNING",
        "title": "TÀI LIỆU LỊCH SỬ ĐÃ BÃI BỎ (DEPRECATED - OLD CLEANING PIPELINE)",
        "reason": "Pipeline làm sạch dữ liệu dựa trên OSM và TomTom Flow cũ. Đã được chuẩn hóa thành pipeline TimBus + Frenet 1D.",
        "successor": "47_CANONICAL_MODULE_STANDARDIZATION_AND_LEGACY_ARCHIVING.md"
    },

    # HISTORICAL SURVEYS
    "00_OVERVIEW_ROADMAP.md": {
        "type": "NOTE",
        "title": "TÀI LIỆU LỊCH SỬ KHẢO SÁT (HISTORICAL R&D LOG)",
        "reason": "Tài liệu tổng quan sơ khởi khi mới bắt đầu dự án. Giữ lại làm nhật ký hình thành ý tưởng, không dùng để tra cứu trạng thái hệ thống.",
        "successor": "48_COMPREHENSIVE_REMAINING_TASKS_AND_SYSTEM_ROADMAP.md"
    },
    "04_ETA_MODELING_AND_LAMBDA_ARCHITECTURE.md": {
        "type": "NOTE",
        "title": "TÀI LIỆU LỊCH SỬ KHẢO SÁT (HISTORICAL R&D LOG)",
        "reason": "Ý tưởng sơ khai về Lambda Architecture và Speed Profile. Đã phát triển thành kiến trúc Medallion Lakehouse (Bronze -> Silver -> Gold).",
        "successor": "49_HISTORICAL_TRAVEL_TIME_MATRIX_SPECIFICATION_AND_STRATEGY.md"
    },
    "07_STATIC_DATA_AND_GTFS_FEASIBILITY.md": {
        "type": "NOTE",
        "title": "TÀI LIỆU LỊCH SỬ KHẢO SÁT (HISTORICAL R&D LOG)",
        "reason": "Khảo sát tính khả thi của GTFS Hà Nội. Có giá trị tham khảo bối cảnh dữ liệu giao thông Việt Nam.",
        "successor": "34_TIMBUS_TRAMOC_GROUND_TRUTH_DISCOVERY.md"
    },
    "08_DATA_CRAWLING_PIPELINE_PROCEDURE.md": {
        "type": "NOTE",
        "title": "TÀI LIỆU LỊCH SỬ KHẢO SÁT (HISTORICAL R&D LOG)",
        "reason": "Quy trình cào telemetry ban đầu. Mã nguồn chính thức đã được đóng băng trong module_1.",
        "successor": "47_CANONICAL_MODULE_STANDARDIZATION_AND_LEGACY_ARCHIVING.md"
    },
    "11_CONGESTION_DATA_SOURCES_AND_PROJECT_SCOPING.md": {
        "type": "NOTE",
        "title": "TÀI LIỆU LỊCH SỬ KHẢO SÁT (HISTORICAL R&D LOG)",
        "reason": "Khảo sát so sánh các nguồn dữ liệu giao thông năm 2026. Có giá trị tham khảo học thuật.",
        "successor": "config/system_config.py"
    },
    "22_ML_EXPERT_CONSULTATION_DOSSIER.md": {
        "type": "NOTE",
        "title": "TÀI LIỆU LỊCH SỬ THAM VẤN (HISTORICAL R&D LOG)",
        "reason": "Hồ sơ câu hỏi tham vấn chuyên gia Machine Learning.",
        "successor": "23_ML_EXPERT_CONSULTATION_ANSWERS.md"
    },
    "27_INTEGRATED_STAGE_ARCHITECTURE_AND_FLEET_SCALE.md": {
        "type": "NOTE",
        "title": "TÀI LIỆU LỊCH SỬ THỬ NGHIỆM (HISTORICAL R&D LOG)",
        "reason": "Báo cáo thử nghiệm quy mô 500 xe buýt giai đoạn 1.",
        "successor": "47_CANONICAL_MODULE_STANDARDIZATION_AND_LEGACY_ARCHIVING.md"
    },
    "31_ETA_ROADMAP_AND_TECHNICAL_OBSTACLES.md": {
        "type": "NOTE",
        "title": "TÀI LIỆU LỊCH SỬ TRỞ NGẠI KỸ THUẬT (HISTORICAL R&D LOG)",
        "reason": "Nhật ký ghi nhận các trở ngại kỹ thuật thời kỳ OSM.",
        "successor": "48_COMPREHENSIVE_REMAINING_TASKS_AND_SYSTEM_ROADMAP.md"
    }
}

count_updated = 0

for filename, info in CLASSIFICATIONS.items():
    filepath = os.path.join("docs", filename)
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        continue
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    if "[!WARNING]" in content or "[!NOTE]" in content:
        print(f"Skipping already tagged: {filename}")
        continue

    # Format banner
    if info["type"] == "WARNING":
        banner = f"""> [!WARNING] {info['title']}
> - **Trạng thái**: KHÔNG ÁP DỤNG CHO HỆ THỐNG HIỆN HÀNH (Chỉ lưu trữ vết tích R&D).
> - **Lý do bãi bỏ**: {info['reason']}
> - **Tài liệu chuẩn mực kế thừa**: Xem [{info['successor']}]({info['successor']}).
> - **CẢNH BÁO CHO AI**: TUYỆT ĐỐI KHÔNG sử dụng các giả định, mã nguồn, cấu trúc dữ liệu hoặc thông số trong tài liệu này làm căn cứ triển khai hệ thống hiện tại.

---
"""
    else:
        banner = f"""> [!NOTE] {info['title']}
> - **Trạng thái**: GHI NHẬN TIẾN TRÌNH KHẢO SÁT BAN ĐẦU (Có giá trị tham khảo học thuật, không phải đặc tả kỹ thuật cuối cùng).
> - **Bối cảnh lịch sử**: {info['reason']}
> - **Tài liệu chuẩn mực kế thừa**: Xem [{info['successor']}]({info['successor']}).

---
"""
    # Insert banner after title line (first line starting with #)
    lines = content.splitlines(keepends=True)
    insert_idx = 0
    for idx, l in enumerate(lines):
        if l.strip().startswith("#"):
            insert_idx = idx + 1
            break
            
    new_content = "".join(lines[:insert_idx]) + "\n" + banner + "\n" + "".join(lines[insert_idx:])
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    print(f"Tagged {filename} with [{info['type']}]")
    count_updated += 1

print(f"\nTotal docs successfully tagged: {count_updated}")
