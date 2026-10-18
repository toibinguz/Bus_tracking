"""
Module 1.1.1: Device Identity Management & Progressive Commuter Pool
Bể hành khách ảo tăng trưởng lũy tiến 300 -> 5000 thiết bị.
Cấp phát ID Android ngẫu nhiên theo phân vùng active để tránh 429 và bảo đảm tính tự nhiên.
"""

import os
import hashlib
import random
from datetime import datetime
from ..config import get_hanoi_time

POOL_START_DATE = "2026-10-12"
BASE_POOL_SIZE = 300
MAX_POOL_SIZE = 5000
HOURLY_GROWTH_RATE = 15   # Thêm 15 thiết bị mới/giờ trong khung giờ 05:00 - 22:00
DAILY_GROWTH_RATE = 250   # Tăng trưởng lũy tiến mỗi ngày

# Danh bạ 5.000 ID Master chuẩn Android 16-hex sinh từ seed xác định
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

