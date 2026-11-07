"""
Centralized Configuration & Constants for Bus Tracking & Traffic Ingestion
Single Source of Truth: All parameters, thresholds, intervals, and credentials.
"""

import os
import sys
import hashlib
import random
from datetime import datetime, timezone, timedelta, time as dtime

# -------------------------------------------------------------
# 1. FILE SYSTEM PATHS & CLOUD IDS
# -------------------------------------------------------------
CONFIG_FILE = "data/metadata/hust_cluster_config.json"
BUS_OUTPUT_DIR = "data/raw/bus"
TRAFFIC_OUTPUT_DIR = "data/raw/traffic"
INCIDENT_OUTPUT_DIR = "data/raw/incidents"
TOMTOM_QUOTA_FILE = "data/metadata/tomtom_quota_tracker.json"
DAILY_HEALTH_FILE = "data/metadata/daily_catalog_health.json"
API_KEY_FILE = "config/TOMTOM_API_KEY.txt"
LEGACY_API_KEY_FILES = [
    "Test_tomtom/TOMTOM_API_KEY.txt",
    "archive/legacy_tests/Test_tomtom/TOMTOM_API_KEY.txt"
]
HF_TOKEN_FILE = "access_token_hf.txt"
HF_DATASET_ID = os.environ.get("HF_DATASET_ID", "Toibinguz/hust-bus-data")

DEFAULT_DB_PATH = "data/hanoi_bus_system.db"
DEFAULT_LAKEHOUSE_ROOT = "data/lakehouse"
LEGACY_AUDIT_DB_PATH = "archive/legacy_dumps/telemetry_audit_2026_10_17_18.db"

def get_database_path() -> str:
    """Lay duong dan CSDL van hanh chuan."""
    if os.path.exists(DEFAULT_DB_PATH):
        return DEFAULT_DB_PATH
    return LEGACY_AUDIT_DB_PATH

# -------------------------------------------------------------
# 2. TOMTOM FREEMIUM BUDGET & LIMITS
# -------------------------------------------------------------
# Đã loại bỏ hoàn toàn TomTom Flow để giải phóng hệ thống và tối đa hóa tính tổng quát hóa.
ENABLE_TOMTOM_FLOW = False
MAX_TOMTOM_FLOW_DAILY = 0
MAX_TOMTOM_FLOW_MONTHLY = 0

# Tối đa hóa TomTom Incident API: Sát mốc 80 requests/ngày (Hạn ngạch tháng: 2,500 req/tháng)
MAX_TOMTOM_INCIDENT_DAILY = 80
MAX_TOMTOM_INCIDENT_MONTHLY = 2500
TOMTOM_INCIDENT_INTERVAL_SEC = 750        # ~12.5 phút/lần (17h x 60 / 12.5 ≈ 80 requests/ngày)

# -------------------------------------------------------------
# 3. GEOGRAPHIC BOUNDING BOXES & BOTTLENECK NODES
# -------------------------------------------------------------
# Bao phủ toàn bộ địa giới Đại đô thị Hà Nội mở rộng (từ Ba Vì/Sơn Tây/Hòa Lạc đến Vân Đình/Mê Linh)
HANOI_BBOX = {
    "min_lat": 20.50,
    "max_lat": 21.40,
    "min_lon": 105.20,
    "max_lon": 106.15
}

# Quét sự cố trên toàn bộ vùng lõi đô thị mở rộng Hà Nội
HUST_CORRIDOR_BBOX = "105.7000,20.9400,105.9200,21.0900"

# Danh sách nút tĩnh đã được loại bỏ việc query Flow trực tiếp, bảo lưu cấu trúc phục vụ đánh giá nếu cần
HUST_BOTTLENECK_NODES = []
TOTAL_BOTTLENECK_NODES = 0
MAX_DAILY_TOMTOM_BATCHES = 0
MAX_MONTHLY_TOMTOM_BATCHES = 0

# -------------------------------------------------------------
# 3.1. KEYLESS & HEADERLESS MAP TILE SERVERS (TESTING & VISUALIZATION)
# -------------------------------------------------------------
OSM_TILE_SERVERS = {
    "osm_fr": {
        "name": "OpenStreetMap France (Headerless & Keyless - Highest Fidelity)",
        "url_template": "https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
        "subdomains": "abc",
        "attribution": "OpenStreetMap France, OpenStreetMap contributors",
        "max_zoom": 20,
        "requires_key": False,
        "requires_custom_headers": False
    },
    "osm_standard": {
        "name": "OpenStreetMap Standard",
        "url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "OpenStreetMap contributors",
        "max_zoom": 19,
        "requires_key": False,
        "requires_custom_headers": False
    },
    "carto_positron": {
        "name": "CartoDB Positron (Light - Clean & High Contrast)",
        "url_template": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "subdomains": "abcd",
        "attribution": "OpenStreetMap contributors, CARTO",
        "max_zoom": 20,
        "requires_key": False,
        "requires_custom_headers": False
    },
    "carto_voyager": {
        "name": "CartoDB Voyager (Street Details)",
        "url_template": "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        "subdomains": "abcd",
        "attribution": "OpenStreetMap contributors, CARTO",
        "max_zoom": 20,
        "requires_key": False,
        "requires_custom_headers": False
    },
    "carto_dark": {
        "name": "CartoDB Dark Matter (Night Mode)",
        "url_template": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "subdomains": "abcd",
        "attribution": "OpenStreetMap contributors, CARTO",
        "max_zoom": 20,
        "requires_key": False,
        "requires_custom_headers": False
    },
    "esri_sat": {
        "name": "Esri World Imagery (Satellite - Keyless and Headerless)",
        "url_template": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Esri, Maxar, Earthstar Geographics, CNES/Airbus DS",
        "max_zoom": 19,
        "requires_key": False,
        "requires_custom_headers": False
    }
}
DEFAULT_TILE_SERVER = "osm_fr"

def get_tile_layer_config(server_key: str = DEFAULT_TILE_SERVER) -> dict:
    """Tra ve cau hinh tile layer mien phi, khong can API key va khong bat buoc custom headers."""
    return OSM_TILE_SERVERS.get(server_key, OSM_TILE_SERVERS["osm_fr"])

# -------------------------------------------------------------
# 4. PACING, TIMING & SCHEDULING INTERVALS (QUY MÔ ~500 XE BUÝT)
# -------------------------------------------------------------
BUS_MICRO_BATCH_SIZE = 18                  # 18 xe / batch (28 batches cho 504 xe)
BUS_MICRO_BATCH_DELAY_SEC = 0.40           # 0.40s giữa các micro-batches (dàn đều ~30s cào 504 xe)
BUS_POLL_INTERVAL_SEC = 75                 # Chu kỳ quét chuẩn 75 giây toàn mạng lưới (30s cào + 45s nghỉ)
SESSION_DURATION_SEC = 540                 # 9 phút cho mỗi phiên GitHub Actions runner
HF_SYNC_INTERVAL_SEC = 600                 # 10 phút đồng bộ lên Hugging Face
TOMTOM_FLOW_THROTTLE_SEC = 0.08            # Giữ tương thích ngược
TOMTOM_PEAK_INTERVAL_SEC = 300             # 5 phút (tương thích ngược)
TOMTOM_OFFPEAK_INTERVAL_SEC = 600          # 10 phút (tương thích ngược)

# -------------------------------------------------------------
# 5. DATA QUALITY, FRENET PROJECTION & KINEMATIC THRESHOLDS
# -------------------------------------------------------------
CANONICAL_START_DATE = "2026-10-08"          # Ngày bắt đầu chiến dịch dữ liệu chuẩn
MIN_CLUSTER_ROUTE_DAYS = 5                   # Tối thiểu 5 ngày hoạt động để xác định 48 tuyến cụm HUST
RAW_DATA_DIR = "data/raw"                    # Thư mục chuẩn duy nhất chứa dữ liệu thô JSONL

METERS_PER_DEG_LON_EQUATOR = 111320.0        # Hệ số quy đổi kinh độ sang mét tại xích đạo (WGS84)
METERS_PER_DEG_LAT = 110540.0                # Hệ số quy đổi vĩ độ sang mét (WGS84)

MAX_CORRIDOR_CROSS_TRACK_M = 35.0            # Ngưỡng lệch tim đường d_perp tối đa (m) cho toàn tầng Silver
MAX_GPS_BACKWARD_JITTER_M = 20.0             # Dung sai nhiễu GPS giật lùi tại chỗ khi xe dừng đỗ (m)
FRENET_MIN_FORWARD_WINDOW_M = 1500.0         # Cửa sổ tìm kiếm tiến tối thiểu trên tim đường (m)
GPS_DRIFT_MAX_SPEED_KMPH = 80.0              # Vận tốc tối đa vật lý xe buýt đô thị Hà Nội (km/h)
FRENET_MAX_SPEED_MPS = GPS_DRIFT_MAX_SPEED_KMPH / 3.6  # Vận tốc tối đa mở cửa sổ tiến (~22.22 m/s)
TERMINAL_RESET_ZONE_M = 800.0                # Vùng đầu/cuối bến cho phép quay đầu bắt đầu chuyến mới (m)

MAX_CONTINUOUS_GAP_SEC = 300.0               # Khoảng cách tối đa (5 phút) coi là ping liên tục trực tiếp
MAX_BRIDGEABLE_DETOUR_GAP_SEC = 1800.0       # Khoảng trống tối đa (30 phút) cho phép nối chuyến qua detour
MIN_DETOUR_BRIDGE_DISPLACEMENT_M = 100.0     # Quãng đường tiến tối thiểu để nối chuyến qua lỗ thủng detour
MIN_DETOUR_BRIDGE_SPEED_KMPH = 2.0           # Vận tốc trung bình tối thiểu qua đoạn detour (km/h)
MAX_DETOUR_BRIDGE_SPEED_KMPH = 60.0          # Vận tốc trung bình tối đa qua đoạn detour (km/h)
MAX_BACKWARD_RESET_M = 200.0                 # Bước lùi xác nhận xe đã quay đầu chuyến mới (m)
MIN_PINGS_PER_TRIP = 5                       # Số bản tin tối thiểu của 1 chuyến hợp lệ
MIN_TRIP_DISTANCE_M = 500.0                  # Quãng đường tối thiểu của 1 chuyến hợp lệ (m)
TERMINAL_STATIONARY_TOL_M = 15.0             # Ngưỡng dịch chuyển cắt bỏ đuôi xe đỗ nghỉ tại bến (m)

TOMTOM_MAX_BATCH_GAP_SEC = 1200              # Khoảng cách tối đa nối 2 batch sự cố TomTom liên tiếp (20 phút)
TOMTOM_DEFAULT_TTL_SEC = 900                 # Thời gian hiệu lực mặc định của 1 snapshot sự cố (15 phút)
TOMTOM_MIN_COS_THETA = 0.50                  # Góc lệch tối đa (<= 60 độ) giữa vector sự cố và hướng tuyến
TOMTOM_GRID_SCALE = 500.0                    # Độ chia lưới không gian O(1) chiếu sự cố (~220m)
TOMTOM_BBOX_PAD_DEG = 0.00045                # Đệm khung bao không gian chiếu sự cố (~46m)
BUS_STOPPED_SPEED_KMPH = 5.0             # Vận tốc xe bò/dừng đón trả khách
CONGESTION_AVG_SPEED_KMPH = 13.0         # Ngưỡng vận tốc trung bình kích hoạt ùn tắc nút
CONGESTION_CORE_CRITICAL_SPEED_KMPH = 10.0 # Ngưỡng ùn tắc nghiêm trọng tại nút lõi Bách Khoa
CONGESTION_STOP_RATIO = 0.35             # 35% xe bò/dừng kích hoạt ùn tắc nút
CONGESTION_CORE_STOP_RATIO = 0.50        # 50% xe dừng kích hoạt ùn tắc nút lõi
HOTSPOT_RADIUS_METERS = 450.0            # Bán kính quanh 19 điểm nghẽn để gom xe probe
INCIDENT_PROXIMITY_METERS = 500.0        # Bán kính quanh điểm nghẽn để hợp nhất sự cố
INCIDENT_CRITICAL_DELAY_SEC = 300        # Sự cố gây trễ từ 5 phút trở lên
INCIDENT_CRITICAL_MAGNITUDE = 3          # Mức độ nghiêm trọng của sự cố từ cấp 3
STALE_DELTA_T_MIN_SEC = 3.0              # Khoảng cách tối thiểu để tính đạo hàm vận tốc
STALE_DELTA_T_MAX_SEC = 300.0            # Khoảng cách tối đa (5 phút) coi là ping liên tục
CATALOG_STALE_HOURS = 24.0                # TD-21: Xe có lastUpdateTime cũ hơn ngưỡng này bị coi là chết/đóng băng (STALE)
CATALOG_MIN_ACTIVE_PER_ROUTE = 6          # TD-21: Số xe ACTIVE tối thiểu mỗi tuyến trước khi quét bổ sung
CATALOG_SCAN_PREFIXES = (
    [f"29B{n}" for n in range(10, 40)]
    + [f"29F0{n}" for n in range(0, 10)]
)                                         # TD-21: Tiền tố biển số quét tìm xe thay thế khi BusMap đổi dải ID
WATCHDOG_MIN_RESPONSE_RATE = 0.60        # Cảnh báo nếu tỷ lệ phản hồi xe < 60%
EMA_ALPHA = 0.65                         # Hệ số làm mịn vận tốc: v_smooth = 0.65*v_calc + 0.35*v_prev

# -------------------------------------------------------------
# 6. OPERATING SCHEDULES, TIMEZONE & MODULE 3 BASELINE CONFIG
# -------------------------------------------------------------
OPERATING_START_HOUR = 5.0
OPERATING_END_HOUR = 22.0

TRAIN_SPLIT_END_DATE = "2026-10-31"          # Ngày kết thúc tập Train (21 ngày: 2026-10-08 -> 2026-10-31)
TEST_SPLIT_START_DATE = "2026-11-01"         # Ngày bắt đầu tập Test độc lập (7 ngày: 2026-11-01 -> 2026-11-07)

BRACKET_MAX_DT_SEC = 150.0                   # Khoảng kẹp thời gian tối đa nội suy thời điểm qua trạm (s)
BRACKET_MAX_DS_M = 1000.0                    # Khoảng kẹp không gian cơ sở nội suy thời điểm qua trạm (m)
BRACKET_SEG_LEN_FACTOR = 1.35                # Hệ số nới khoảng kẹp thích ứng cho các đoạn trạm dài (>1000m)
SEGMENT_MIN_SPEED_KMPH = 1.5                 # Vận tốc liên trạm tối thiểu vật lý (tránh xe chết máy/nghỉ giữa đường)
SEGMENT_MAX_SPEED_KMPH = 65.0                # Vận tốc liên trạm tối đa vật lý (km/h)

BASELINE_MIN_HOUR_SLOT = 5                   # Khung giờ vận hành bắt đầu (05:00)
BASELINE_MAX_HOUR_SLOT = 21                  # Khung giờ vận hành cuối (21:00+, gộp đuôi sau 21h vào slot 21 -> 17 khung giờ)
DAY_TYPE_WEEKDAY = 0                         # Thứ 2 .. Thứ 6 (15 ngày Train)
DAY_TYPE_SATURDAY = 1                        # Thứ 7 (4 ngày Train - hành vi giao thông riêng biệt)
DAY_TYPE_SUNDAY = 2                          # Chủ Nhật (3 ngày Train - thông thoáng)

BASELINE_TIER0_MIN_SAMPLES = 10              # Tier 0 (Weekday - 15 ngày Train): Đủ mẫu trực tiếp >= 10
BASELINE_TIER0_MIN_SAMPLES_WEEKEND = 5       # Tier 0 (Thứ 7 / Chủ Nhật sau khi gom trượt 3h cùng loại ngày): >= 5 mẫu
BASELINE_SAT_SUN_KERNEL_MIN_DIRECT = 8       # Ngưỡng mẫu trực tiếp tối thiểu trước khi kích hoạt cửa sổ trượt 3h [h-1,h,h+1] cùng loại ngày cho Thứ 7/CN
BASELINE_TIER1_MIN_SAMPLES = 3               # Tier 1: Mẫu thưa trực tiếp (3 <= N < Tier 0)
DEFAULT_URBAN_BUS_SPEED_KMPH = 18.0          # Vận tốc trung bình mặc định toàn mạng khi không có mẫu lịch sử
EXCLUDE_TERMINAL_BOUNDARY_STATIONS = True    # TD-19: Tách biệt 2 trạm đầu cuối (0 và N); chỉ tính ETA động học cho hành lang nội tuyến [1 .. N-1]

TZ_HANOI = timezone(timedelta(hours=7))

def get_hanoi_time():
    """Lấy thời gian chuẩn Hà Nội (UTC + 7) với tzinfo='+07:00' chính xác."""
    return datetime.now(TZ_HANOI)

def is_operating_hours(hn_time=None, run_24x7=False):
    """Kiểm tra khung giờ xe buýt vận hành (05:00 - 22:00)."""
    if run_24x7:
        return True
    if hn_time is None:
        hn_time = get_hanoi_time()
    hour_val = hn_time.hour + hn_time.minute / 60.0
    return OPERATING_START_HOUR <= hour_val <= OPERATING_END_HOUR

def is_peak_hours(hn_time=None):
    """
    Xác định giờ cao điểm phân biệt Ngày trong tuần (Thứ 2 - Thứ 6) vs Cuối tuần (Thứ 7 - CN).
    - Ngày thường: Cao điểm sáng 06:30 - 09:00, chiều 16:30 - 19:30 (đi làm, đi học).
    - Cuối tuần: Cao điểm giãn 07:30 - 09:30 và 17:00 - 19:00 (lưu lượng giảm, tránh lãng phí budget).
    """
    if hn_time is None:
        hn_time = get_hanoi_time()
    hour_val = hn_time.hour + hn_time.minute / 60.0
    is_weekend = hn_time.weekday() >= 5

    if not is_weekend:
        return (6.5 <= hour_val <= 9.0) or (16.5 <= hour_val <= 19.5)
    else:
        return (7.5 <= hour_val <= 9.5) or (17.0 <= hour_val <= 19.0)

# ==============================================================================
# PROGRESSIVE COMMUTER POOL (Bể Hành Khách Ảo Tăng Trưởng Lũy Tiến 300 -> 5000)
# ==============================================================================
POOL_START_DATE = "2026-10-12"
BASE_POOL_SIZE = 300
MAX_POOL_SIZE = 5000
HOURLY_GROWTH_RATE = 15   # Thêm 15 thiết bị mới/giờ trong khung giờ 05:00 - 22:00
DAILY_GROWTH_RATE = 250   # Tăng trưởng lũy tiến mỗi ngày

MASTER_DEVICE_POOL = [
    hashlib.sha256(f"hust_commuter_device_{i:04d}".encode("utf-8")).hexdigest()[:16]
    for i in range(MAX_POOL_SIZE)
]

def get_current_progressive_pool_size():
    """Tính toán kích thước bể hiện tại dựa trên mốc thời gian trôi qua."""
    hn_time = get_hanoi_time()
    try:
        start_dt = datetime.strptime(POOL_START_DATE, "%Y-%m-%d")
        curr_dt = datetime(hn_time.year, hn_time.month, hn_time.day)
        days_elapsed = max(0, (curr_dt - start_dt).days)
    except Exception:
        days_elapsed = 0

    operating_hours = max(0, min(17, hn_time.hour - 5))
    size = BASE_POOL_SIZE + (days_elapsed * DAILY_GROWTH_RATE) + (operating_hours * HOURLY_GROWTH_RATE)
    return min(MAX_POOL_SIZE, max(BASE_POOL_SIZE, size))

def get_busmap_device_id(v_id=None, bad_device_id=None, force_rotate=False):
    """
    Cấp phát Device-ID từ phân vùng active của Bể Tăng Trưởng Lũy Tiến:
    - Nếu có biến môi trường BUSMAP_DEVICE_ID và không force_rotate: dùng biến môi trường.
    - Ngược lại: bốc ngẫu nhiên 1 ID từ active_pool (kích thước hiện tại từ 300 -> 5.000).
    - Tần suất mỗi ID cực thấp (< 1 req/phút), 100% không bao giờ bị 429.
    """
    env_id = os.environ.get("BUSMAP_DEVICE_ID")
    if env_id and not force_rotate:
        return env_id
    active_size = get_current_progressive_pool_size()
    idx = random.randint(0, active_size - 1)
    chosen_id = MASTER_DEVICE_POOL[idx]
    if force_rotate and bad_device_id and chosen_id == bad_device_id and active_size > 1:
        idx = (idx + 1) % active_size
        chosen_id = MASTER_DEVICE_POOL[idx]
    return chosen_id

def get_tomtom_api_key():
    """Lấy TomTom API Key từ biến môi trường hoặc file cục bộ."""
    key = os.environ.get("TOMTOM_KEY", "") or os.environ.get("TOMTOM_API_KEY", "")
    if key:
        return key

    candidate_files = [API_KEY_FILE] + LEGACY_API_KEY_FILES
    for path in candidate_files:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val:
                        return val
            except Exception:
                pass
    return ""

def get_hf_token():
    """Lấy Hugging Face Token từ biến môi trường hoặc file cục bộ."""
    token = os.environ.get("HF_TOKEN", "")
    if not token and os.path.exists(HF_TOKEN_FILE):
        try:
            with open(HF_TOKEN_FILE, "r", encoding="utf-8") as f:
                token = f.read().strip()
        except Exception:
            pass
    return token
