"""
TomTom Traffic API Client, Circuit Breaker & Quota Tracking
"""

import os
import json
import time
import ssl
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from .config import (
    TOMTOM_QUOTA_FILE,
    MAX_TOMTOM_FLOW_DAILY,
    MAX_TOMTOM_FLOW_MONTHLY,
    MAX_TOMTOM_INCIDENT_DAILY,
    MAX_TOMTOM_INCIDENT_MONTHLY,
    TOMTOM_FLOW_THROTTLE_SEC,
    HUST_CORRIDOR_BBOX,
    HUST_BOTTLENECK_NODES,
    get_hanoi_time
)

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

TOMTOM_CIRCUIT_OPEN = False

def fetch_tomtom_flow(lat, lon, api_key):
    """Truy vấn TomTom Flow Segment Data cho một tọa độ điểm nghẽn."""
    global TOMTOM_CIRCUIT_OPEN
    if TOMTOM_CIRCUIT_OPEN or not api_key:
        return None
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key={api_key}&point={lat},{lon}&unit=KMPH"
    req = urllib.request.Request(url, headers={"User-Agent": "HUSTBusCrawler/2.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("flowSegmentData")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            TOMTOM_CIRCUIT_OPEN = True
            print(f"[CIRCUIT BREAKER] ⚠️ TomTom trả về HTTP {e.code} (Hết quota/bị giới hạn). Đóng cổng kết nối!", flush=True)
        return None
    except Exception:
        return None

def fetch_tomtom_incidents(api_key, bbox=HUST_CORRIDOR_BBOX):
    """Truy vấn TomTom Incident Details cho toàn bộ Bounding Box hành lang Bách Khoa."""
    global TOMTOM_CIRCUIT_OPEN
    if TOMTOM_CIRCUIT_OPEN or not api_key:
        return []
    raw_url = f"https://api.tomtom.com/traffic/services/5/incidentDetails?key={api_key}&bbox={bbox}&language=en-GB&fields={{incidents{{type,geometry{{type,coordinates}},properties{{id,iconCategory,magnitudeOfDelay,delay,length,events{{description}}}}}}}}"
    url = urllib.parse.quote(raw_url, safe=':/?=&')
    req = urllib.request.Request(url, headers={"User-Agent": "HUSTBusCrawler/2.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("incidents", [])
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            TOMTOM_CIRCUIT_OPEN = True
            print(f"[CIRCUIT BREAKER] ⚠️ TomTom trả về HTTP {e.code} (Hết quota/bị giới hạn). Đóng cổng kết nối!", flush=True)
        return []
    except Exception:
        return []

def execute_tomtom_flow_poll(cur_hn_time, api_key, nodes=None):
    """Thực hiện một lượt quét Flow Segments cho danh sách nodes (mặc định 19 nodes)."""
    flow_records = []
    if not api_key or TOMTOM_CIRCUIT_OPEN:
        return flow_records
    if nodes is None:
        nodes = HUST_BOTTLENECK_NODES

    for node in nodes:
        res = fetch_tomtom_flow(node["lat"], node["lon"], api_key)
        if res:
            raw_coords = res.get("coordinates", {}).get("coordinate", [])
            seg_coords = [[round(c["longitude"], 6), round(c["latitude"], 6)] for c in raw_coords if "longitude" in c and "latitude" in c]
            flow_records.append({
                "timestamp": cur_hn_time.isoformat(),
                "node_name": node["name"],
                "lat": node["lat"],
                "lon": node["lon"],
                "current_speed": res.get("currentSpeed"),
                "free_flow_speed": res.get("freeFlowSpeed"),
                "travel_time": res.get("currentTravelTime"),
                "confidence": res.get("confidence"),
                "road_closure": res.get("roadClosure", False),
                "coordinates": seg_coords
            })
        time.sleep(TOMTOM_FLOW_THROTTLE_SEC)
    return flow_records

def execute_tomtom_incident_poll(cur_hn_time, api_key, bbox=HUST_CORRIDOR_BBOX):
    """Thực hiện một lượt quét Incident Details cho Bounding Box Hà Nội."""
    inc_records = []
    if not api_key or TOMTOM_CIRCUIT_OPEN:
        return inc_records

    raw_incidents = fetch_tomtom_incidents(api_key, bbox=bbox)
    for inc in raw_incidents:
        props = inc.get("properties", {})
        geom = inc.get("geometry", {})
        events = props.get("events", [])
        desc = events[0].get("description", "") if events else ""
        inc_records.append({
            "timestamp": cur_hn_time.isoformat(),
            "incident_id": props.get("id", ""),
            "icon_category": props.get("iconCategory", 0),
            "magnitude_of_delay": props.get("magnitudeOfDelay", 0),
            "delay_seconds": props.get("delay", 0),
            "length_meters": round(props.get("length", 0), 2),
            "description": desc,
            "geometry_type": geom.get("type", "LineString"),
            "coordinates": geom.get("coordinates", [])
        })
    return inc_records

def execute_tomtom_poll(cur_hn_time, api_key):
    """Wrapper tương thích ngược: quét cả 19 Flow Segments và Incident BBox."""
    flow = execute_tomtom_flow_poll(cur_hn_time, api_key)
    inc = execute_tomtom_incident_poll(cur_hn_time, api_key)
    return flow, inc

def load_tomtom_quota_state():
    """Tải trạng thái sử dụng hạn mức TomTom theo Ngày và Tháng theo giờ chuẩn Hà Nội."""
    hn_time = get_hanoi_time()
    today_str = hn_time.strftime("%Y-%m-%d")
    current_month_str = hn_time.strftime("%Y-%m")
    flow_today = 0
    flow_month = 0
    incident_today = 0
    incident_month = 0
    if os.path.exists(TOMTOM_QUOTA_FILE):
        try:
            with open(TOMTOM_QUOTA_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                saved_month = state.get("month", "")
                saved_date = state.get("date", "")
                if saved_month == current_month_str:
                    flow_month = state.get("flow_used_month", 0)
                    incident_month = state.get("incident_used_month", 0)
                if saved_date == today_str:
                    flow_today = state.get("flow_used_today", state.get("used_today", 0))
                    incident_today = state.get("incident_used_today", 0)
        except Exception:
            pass
    return {
        "flow_today": flow_today,
        "flow_month": flow_month,
        "incident_today": incident_today,
        "incident_month": incident_month
    }

def save_tomtom_quota_state(quota_state):
    """Lưu cập nhật trạng thái hạn mức TomTom theo Ngày và Tháng theo giờ chuẩn Hà Nội."""
    hn_time = get_hanoi_time()
    today_str = hn_time.strftime("%Y-%m-%d")
    current_month_str = hn_time.strftime("%Y-%m")
    os.makedirs(os.path.dirname(TOMTOM_QUOTA_FILE), exist_ok=True)
    state = {
        "date": today_str,
        "month": current_month_str,
        "flow_daily_budget": MAX_TOMTOM_FLOW_DAILY,
        "flow_monthly_limit": MAX_TOMTOM_FLOW_MONTHLY,
        "flow_used_today": quota_state["flow_today"],
        "flow_used_month": quota_state["flow_month"],
        "flow_remaining_today": max(0, MAX_TOMTOM_FLOW_DAILY - quota_state["flow_today"]),
        "flow_remaining_month": max(0, MAX_TOMTOM_FLOW_MONTHLY - quota_state["flow_month"]),
        "incident_daily_budget": MAX_TOMTOM_INCIDENT_DAILY,
        "incident_monthly_limit": MAX_TOMTOM_INCIDENT_MONTHLY,
        "incident_used_today": quota_state["incident_today"],
        "incident_used_month": quota_state["incident_month"],
        "incident_remaining_today": max(0, MAX_TOMTOM_INCIDENT_DAILY - quota_state["incident_today"]),
        "incident_remaining_month": max(0, MAX_TOMTOM_INCIDENT_MONTHLY - quota_state["incident_month"]),
        "last_updated": hn_time.strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        with open(TOMTOM_QUOTA_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def render_tomtom_cli_bar(quota_state, next_poll_seconds, is_congested=False, circuit_open=False):
    """Vẽ thanh tiến độ CLI trực quan."""
    f_pct = min(1.0, quota_state["flow_today"] / float(MAX_TOMTOM_FLOW_DAILY))
    bar_width = 8
    filled = int(f_pct * bar_width)
    bar_str = "█" * filled + "░" * (bar_width - filled)
    countdown_str = f"{int(next_poll_seconds // 60):02d}:{int(next_poll_seconds % 60):02d}s" if next_poll_seconds > 0 else "Sẵn sàng"
    status_tag = "🔴 CIRCUIT OPEN" if circuit_open else ("🔥 ÙN TẮC" if is_congested else "🟢 BÌNH THƯỜNG")
    return (
        f"🚦 TomTom [{status_tag}]: Flow [{bar_str}] {quota_state['flow_today']}/{MAX_TOMTOM_FLOW_DAILY} "
        f"(Tháng: {quota_state['flow_month']}/{MAX_TOMTOM_FLOW_MONTHLY // 1000}k) | Incidents {quota_state['incident_today']}/{MAX_TOMTOM_INCIDENT_DAILY} | "
        f"Đợt tới: {countdown_str}"
    )

