"""
Module 1.1.1: Low-level Network Transport (Raw Socket SSL & Dynamic DNS Cache)
Quản lý kết nối TCP/SSL cấp thấp, Dynamic DNS cache trong RAM, và đóng dấu crawled_at thời gian thực.
"""

import socket
import ssl
import json
import time
from .device_pool import get_busmap_device_id
from core.config import get_hanoi_time

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

_BUSMAP_HOST = "api.busmap.city"
_BUSMAP_IP_CACHE = None
_BUSMAP_IP_RESOLVED_AT = 0
SOCKET_TIMEOUT_SEC = 2.2       # Ngưỡng timeout tối ưu (gấp đôi thời gian phản hồi bình thường)
SOCKET_RETRY_TIMEOUT_SEC = 1.5 # Ngưỡng timeout cho đợt retry nếu gặp 429

def get_busmap_ip():
    """Cache phân giải IP của api.busmap.city trong RAM để triệt tiêu 504 lần truy vấn DNS/vòng."""
    global _BUSMAP_IP_CACHE, _BUSMAP_IP_RESOLVED_AT
    now = time.time()
    if _BUSMAP_IP_CACHE is None or (now - _BUSMAP_IP_RESOLVED_AT) > 600:  # Làm mới mỗi 10 phút
        try:
            _BUSMAP_IP_CACHE = socket.gethostbyname(_BUSMAP_HOST)
            _BUSMAP_IP_RESOLVED_AT = now
        except Exception:
            _BUSMAP_IP_CACHE = _BUSMAP_HOST
    return _BUSMAP_IP_CACHE

def fetch_single_bus_raw(v_id):
    """
    Gửi HTTP request cấp thấp qua raw socket SSL đến BusMap API với DNS Cache và Timeout chặt chẽ.
    Đóng dấu mốc thời gian crawled_at chính xác ngay khi nhận được gói tin HTTP của xe này.
    """
    dev_id = get_busmap_device_id(v_id=v_id)
    raw_req = (
        f"GET /v2/public/busmap/vehicle_hn/get?id={v_id} HTTP/1.1\r\n"
        f"Host: {_BUSMAP_HOST}\r\n"
        "language: vi\r\n"
        "client-version: android|20600\r\n"
        f"device-id: {dev_id}\r\n"
        "package-name: com.t7.busmaphn\r\n"
        "Connection: close\r\n\r\n"
    )
    target_host = get_busmap_ip()
    try:
        with socket.create_connection((target_host, 443), timeout=SOCKET_TIMEOUT_SEC) as s:
            s.settimeout(SOCKET_TIMEOUT_SEC)
            with ssl_context.wrap_socket(s, server_hostname=_BUSMAP_HOST) as ss:
                ss.settimeout(SOCKET_TIMEOUT_SEC)
                ss.sendall(raw_req.encode("utf-8"))
                resp = b""
                while True:
                    d = ss.recv(4096)
                    if not d: break
                    resp += d
                header, _, body = resp.partition(b"\r\n\r\n")
                if not body: return None
                if b"429 Too Many Requests" in header or b"LOCKED" in body:
                    new_dev_id = get_busmap_device_id(v_id=v_id, bad_device_id=dev_id, force_rotate=True)
                    # Thử lại 1 lần với device ID mới vừa cấp và timeout gọn gàng
                    retry_req = (
                        f"GET /v2/public/busmap/vehicle_hn/get?id={v_id} HTTP/1.1\r\n"
                        f"Host: {_BUSMAP_HOST}\r\n"
                        "language: vi\r\n"
                        "client-version: android|20600\r\n"
                        f"device-id: {new_dev_id}\r\n"
                        "package-name: com.t7.busmaphn\r\n"
                        "Connection: close\r\n\r\n"
                    )
                    with socket.create_connection((target_host, 443), timeout=SOCKET_RETRY_TIMEOUT_SEC) as s2:
                        s2.settimeout(SOCKET_RETRY_TIMEOUT_SEC)
                        with ssl_context.wrap_socket(s2, server_hostname=_BUSMAP_HOST) as ss2:
                            ss2.settimeout(SOCKET_RETRY_TIMEOUT_SEC)
                            ss2.sendall(retry_req.encode("utf-8"))
                            resp2 = b""
                            while True:
                                d2 = ss2.recv(4096)
                                if not d2: break
                                resp2 += d2
                            _, _, body2 = resp2.partition(b"\r\n\r\n")
                            if body2:
                                data2 = json.loads(body2.decode("utf-8", errors="ignore"))
                                if data2 and isinstance(data2, list) and len(data2) > 0:
                                    item2 = data2[0]
                                    if isinstance(item2, dict):
                                        item2["_crawled_at"] = get_hanoi_time().isoformat()
                                    return item2
                    return None
                data = json.loads(body.decode("utf-8", errors="ignore"))
                if data and isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    if isinstance(item, dict):
                        item["_crawled_at"] = get_hanoi_time().isoformat()
                    return item
    except Exception:
        return None
    return None

