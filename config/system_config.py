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
LEGACY_AUDIT_DB_PATH = "data/telemetry_audit_2026_10_17_18.db"

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
HANOI_BBOX = {
    "min_lat": 20.80,
    "max_lat": 21.30,
    "min_lon": 105.65,
    "max_lon": 106.05
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
    }
}
DEFAULT_TILE_SERVER = "carto_positron"

def get_tile_layer_config(server_key: str = DEFAULT_TILE_SERVER) -> dict:
    """Tra ve cau hinh tile layer mien phi, khong can API key va khong bat buoc custom headers."""
    return OSM_TILE_SERVERS.get(server_key, OSM_TILE_SERVERS["carto_positron"])

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
# 5. DATA QUALITY & TRAFFIC THRESHOLDS
# -------------------------------------------------------------
GPS_DRIFT_MAX_SPEED_KMPH = 80.0          # Vận tốc tối đa vật lý xe buýt nội đô Hà Nội
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
WATCHDOG_MIN_RESPONSE_RATE = 0.60        # Cảnh báo nếu tỷ lệ phản hồi xe < 60%
EMA_ALPHA = 0.65                         # Hệ số làm mịn vận tốc: v_smooth = 0.65*v_calc + 0.35*v_prev

# -------------------------------------------------------------
# 6. OPERATING SCHEDULES & TIMEZONE
# -------------------------------------------------------------
OPERATING_START_HOUR = 5.0
OPERATING_END_HOUR = 22.0

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
