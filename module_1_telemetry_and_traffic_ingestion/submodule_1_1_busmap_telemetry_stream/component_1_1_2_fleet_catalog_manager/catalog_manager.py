"""
Module 1.1.2: Fleet Catalog & Cluster Configuration Management
Quản lý danh bạ xe buýt 19 tuyến hành lang HUST và truy vấn tìm kiếm xe trên mạng lưới.
"""

import json
import socket
import ssl
from config import CONFIG_FILE

from ..component_1_1_1_transport_and_device_pool import get_busmap_device_id

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def load_cluster_config(config_path=CONFIG_FILE):
    """Đọc file cấu hình cụm 19 tuyến hành lang."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cluster_config(config, config_path=CONFIG_FILE):
    """Ghi cập nhật file cấu hình cụm 19 tuyến hành lang."""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def search_vehicles_by_query(query, limit=50):
    """Tìm kiếm xe buýt trên API BusMap theo mã tuyến hoặc biển số."""
    dev_id = get_busmap_device_id()
    raw_req = (
        f"GET /v2/public/busmap/search_vehicle_v2?regionCode=hn&limit={limit}&vehicleId={query}&page=0 HTTP/1.1\r\n"
        "Host: api.busmap.city\r\n"
        "language: vi\r\n"
        "client-version: android|20600\r\n"
        f"device-id: {dev_id}\r\n"
        "package-name: com.t7.busmaphn\r\n"
        "Connection: close\r\n\r\n"
    )
    try:
        with socket.create_connection(("api.busmap.city", 443), timeout=5.0) as s:
            with ssl_context.wrap_socket(s, server_hostname="api.busmap.city") as ss:
                ss.sendall(raw_req.encode("utf-8"))
                resp = b""
                while True:
                    d = ss.recv(4096)
                    if not d: break
                    resp += d
                header, _, body = resp.partition(b"\r\n\r\n")
                if not body: return []
                data = json.loads(body.decode("utf-8", errors="ignore"))
                if isinstance(data, list):
                    return data
    except Exception:
        return []
    return []

