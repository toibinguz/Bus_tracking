"""
Centralized Configuration & Constants for Bus Tracking & Traffic Ingestion
"""

import os
import sys
from datetime import datetime, timezone, timedelta, time as dtime

CONFIG_FILE = "data/metadata/hust_cluster_config.json"
BUS_OUTPUT_DIR = "data/raw/bus"
TRAFFIC_OUTPUT_DIR = "data/raw/traffic"
INCIDENT_OUTPUT_DIR = "data/raw/incidents"
TOMTOM_QUOTA_FILE = "data/metadata/tomtom_quota_tracker.json"
API_KEY_FILE = "Test_tomtom/TOMTOM_API_KEY.txt"
HF_TOKEN_FILE = "access_token_hf.txt"
HF_DATASET_ID = os.environ.get("HF_DATASET_ID", "Toibinguz/hust-bus-data")

# TomTom Freemium Limits (20k Flow / month, 2.5k Incident / month)
MAX_TOMTOM_FLOW_DAILY = 600
MAX_TOMTOM_FLOW_MONTHLY = 20000
MAX_TOMTOM_INCIDENT_DAILY = 75
MAX_TOMTOM_INCIDENT_MONTHLY = 2500

# Geographic bounding box for Hanoi Urban Core
HANOI_BBOX = {
    "min_lat": 20.80,
    "max_lat": 21.30,
    "min_lon": 105.65,
    "max_lon": 106.05
}

# Bounding box for HUST Corridor (TomTom Incidents query)
HUST_CORRIDOR_BBOX = "105.7500,20.9500,105.9000,21.0800"

# Top 19 critical bottlenecks for HUST cluster routes
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
    return 5.0 <= hour_val <= 22.0

def is_peak_hours(hn_time=None):
    """
    Xác định giờ cao điểm phân biệt Ngày trong tuần (Thứ 2 - Thứ 6) vs Cuối tuần (Thứ 7 - CN).
    - Ngày thường: Cao điểm sáng 06:30 - 09:00, chiều 16:30 - 19:30 (đi làm, đi học).
    - Cuối tuần: Cao điểm giãn 07:30 - 09:30 và 17:00 - 19:00 (lưu lượng giảm, tránh lãng phí budget).
    """
    if hn_time is None:
        hn_time = get_hanoi_time()
    hour_val = hn_time.hour + hn_time.minute / 60.0
    is_weekend = hn_time.weekday() >= 5  # 5: Thứ 7, 6: Chủ nhật

    if not is_weekend:
        return (6.5 <= hour_val <= 9.0) or (16.5 <= hour_val <= 19.5)
    else:
        return (7.5 <= hour_val <= 9.5) or (17.0 <= hour_val <= 19.0)

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

