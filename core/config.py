"""
Centralized Configuration & Constants for Bus Tracking & Traffic Ingestion
Single Source of Truth: All parameters, thresholds, intervals, and credentials.
"""

import os
import sys
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
API_KEY_FILE = "Test_tomtom/TOMTOM_API_KEY.txt"
HF_TOKEN_FILE = "access_token_hf.txt"
HF_DATASET_ID = os.environ.get("HF_DATASET_ID", "Toibinguz/hust-bus-data")

# -------------------------------------------------------------
# 2. TOMTOM FREEMIUM BUDGET & LIMITS
# -------------------------------------------------------------
# Bounded to Monthly Freemium: 20,000 Flow / month, 2,500 Incident / month
MAX_TOMTOM_FLOW_DAILY = 600
MAX_TOMTOM_FLOW_MONTHLY = 20000
MAX_TOMTOM_INCIDENT_DAILY = 75
MAX_TOMTOM_INCIDENT_MONTHLY = 2500

# -------------------------------------------------------------
# 3. GEOGRAPHIC BOUNDING BOXES & BOTTLENECK NODES
# -------------------------------------------------------------
HANOI_BBOX = {
    "min_lat": 20.80,
    "max_lat": 21.30,
    "min_lon": 105.65,
    "max_lon": 106.05
}

HUST_CORRIDOR_BBOX = "105.7500,20.9500,105.9000,21.0800"

HUST_BOTTLENECK_NODES = [
    {"name": "Kim_Lien_Ham_Chui", "lat": 21.0084, "lon": 105.8427, "is_core": True},
    {"name": "Dai_Co_Viet_Pho_Hue", "lat": 21.0092, "lon": 105.8503, "is_core": True},
    {"name": "Nga_Tu_Vong", "lat": 20.9987, "lon": 105.8415, "is_core": True},
    {"name": "Le_Thanh_Nghi_Bach_Mai", "lat": 21.0028, "lon": 105.8497, "is_core": True},
    {"name": "Nga_Tu_Cau_Giay", "lat": 21.0315, "lon": 105.8016, "is_core": False},
    {"name": "Nga_Tu_Mai_Dich", "lat": 21.0378, "lon": 105.7788, "is_core": False},
    {"name": "Cau_Dien_QL32", "lat": 21.0422, "lon": 105.7582, "is_core": False},
    {"name": "Nhon_DH_Cong_Nghiep", "lat": 21.0543, "lon": 105.7351, "is_core": False},
    {"name": "Pham_Ngoc_Thach_DH_Y", "lat": 21.0089, "lon": 105.8324, "is_core": False},
    {"name": "Chua_Boc_Tay_Son", "lat": 21.0097, "lon": 105.8239, "is_core": False},
    {"name": "Huynh_Thuc_Khang_NCT", "lat": 21.0211, "lon": 105.8118, "is_core": False},
    {"name": "Nga_Tu_So", "lat": 21.0012, "lon": 105.8197, "is_core": False},
    {"name": "Nguyen_Trai_Khuat_Duy_Tien", "lat": 20.9922, "lon": 105.8005, "is_core": False},
    {"name": "Nguyen_Trai_Cau_Trang", "lat": 20.9765, "lon": 105.7832, "is_core": False},
    {"name": "Trang_Tien_Bo_Ho", "lat": 21.0251, "lon": 105.8542, "is_core": False},
    {"name": "Yen_Phu_Cau_Chuong_Duong", "lat": 21.0415, "lon": 105.8552, "is_core": False},
    {"name": "Nghi_Tam_Au_Co", "lat": 21.0665, "lon": 105.8285, "is_core": False},
    {"name": "Giai_Phong_Kim_Dong_Giap_Bat", "lat": 20.9812, "lon": 105.8422, "is_core": False},
    {"name": "Ngoc_Hoi_Phan_Trong_Tue", "lat": 20.9498, "lon": 105.8451, "is_core": False}
]

# Tự động tính số đợt gọi tối đa dựa trên số lượng nút bottleneck (KHÔNG hardcode số 31)
TOTAL_BOTTLENECK_NODES = len(HUST_BOTTLENECK_NODES)
MAX_DAILY_TOMTOM_BATCHES = MAX_TOMTOM_FLOW_DAILY // TOTAL_BOTTLENECK_NODES          # 600 // 19 = 31 đợt/ngày
MAX_MONTHLY_TOMTOM_BATCHES = MAX_TOMTOM_FLOW_MONTHLY // TOTAL_BOTTLENECK_NODES      # 20000 // 19 = 1052 đợt/tháng

# -------------------------------------------------------------
# 4. PACING, TIMING & SCHEDULING INTERVALS
# -------------------------------------------------------------
BUS_MICRO_BATCH_SIZE = 8
BUS_MICRO_BATCH_DELAY_SEC = 0.35
BUS_POLL_INTERVAL_SEC = 60
SESSION_DURATION_SEC = 540               # 9 phút cho mỗi phiên GitHub Actions runner
TOMTOM_PEAK_INTERVAL_SEC = 18 * 60       # 1080s (18 phút khi cao điểm hoặc ùn tắc)
TOMTOM_OFFPEAK_INTERVAL_SEC = 54 * 60    # 3240s (54 phút khi thấp điểm bình thường)
TOMTOM_FLOW_THROTTLE_SEC = 0.08          # 80ms throttle giữa các nút
HF_SYNC_INTERVAL_SEC = 600               # 10 phút đồng bộ lên Hugging Face

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

def get_hanoi_time():
    """Lấy thời gian chuẩn Hà Nội (UTC + 7)."""
    return datetime.now(timezone.utc) + timedelta(hours=7)

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

# -------------------------------------------------------------
# 7. DEVICE IDENTIFIERS & CREDENTIALS
# -------------------------------------------------------------
_CURRENT_BUSMAP_DEVICE_ID = None

def get_busmap_device_id(force_rotate=False):
    """
    Lấy device-id giả lập Android (16 hex chars).
    Nếu bị 429 LOCKED hoặc force_rotate=True, tự động sinh mã mới để vượt qua giới hạn rate-limit per-device.
    """
    global _CURRENT_BUSMAP_DEVICE_ID
    env_id = os.environ.get("BUSMAP_DEVICE_ID")
    if env_id and not force_rotate:
        return env_id
    if _CURRENT_BUSMAP_DEVICE_ID is None or force_rotate:
        import uuid
        _CURRENT_BUSMAP_DEVICE_ID = uuid.uuid4().hex[:16]
    return _CURRENT_BUSMAP_DEVICE_ID

def get_tomtom_api_key():
    """Lấy TomTom API Key từ biến môi trường hoặc file cục bộ."""
    key = os.environ.get("TOMTOM_KEY", "") or os.environ.get("TOMTOM_API_KEY", "")
    if not key and os.path.exists(API_KEY_FILE):
        try:
            with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
        except Exception:
            pass
    return key

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
