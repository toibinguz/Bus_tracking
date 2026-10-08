"""
Traffic Congestion Assessment Engine (Multi-source Bus Probe & Incident Fusion)
"""

from .config import (
    HUST_BOTTLENECK_NODES,
    HOTSPOT_RADIUS_METERS,
    INCIDENT_PROXIMITY_METERS,
    BUS_STOPPED_SPEED_KMPH,
    CONGESTION_AVG_SPEED_KMPH,
    CONGESTION_CORE_CRITICAL_SPEED_KMPH,
    CONGESTION_STOP_RATIO,
    CONGESTION_CORE_STOP_RATIO,
    INCIDENT_CRITICAL_MAGNITUDE,
    INCIDENT_CRITICAL_DELAY_SEC
)
from .bus_client import haversine_distance

def evaluate_hotspot_congestion(bus_records, bottleneck_nodes=HUST_BOTTLENECK_NODES, radius_meters=HOTSPOT_RADIUS_METERS, recent_incidents=None):
    """
    Đo lường mật độ và vận tốc xe buýt xung quanh 19 điểm nghẽn trọng yếu kết hợp sự cố giao thông (Incidents).
    Dùng 220 xe buýt làm cảm biến thăm dò (probe sensors) + TomTom incidents để phát hiện ùn tắc cục bộ.
    """
    if not bus_records and not recent_incidents:
        return {"is_congested": False, "congested_nodes": [], "details": {}}

    active_buses = [b for b in bus_records if b.get("quality_status") == "ACTIVE_VALID"] if bus_records else []
    congested_nodes = []
    details = {}
    has_critical_core_congestion = False

    # 1. Khảo sát từng nút giao nghẽn
    for node in bottleneck_nodes:
        n_lat, n_lon = node["lat"], node["lon"]
        name = node["name"]
        is_core = node.get("is_core", False)

        # A. Cảm biến vận tốc xe buýt
        nearby_speeds = []
        for b in active_buses:
            d = haversine_distance(n_lat, n_lon, b["lat"], b["lon"])
            if d <= radius_meters:
                nearby_speeds.append(b.get("speed", 0.0))

        bus_count = len(nearby_speeds)
        node_congested = False
        avg_speed = 0.0
        crawl_ratio = 0.0

        if bus_count >= 3:
            avg_speed = sum(nearby_speeds) / bus_count
            crawl_count = sum(1 for s in nearby_speeds if s < BUS_STOPPED_SPEED_KMPH)
            crawl_ratio = crawl_count / bus_count

            # Tiêu chí xe buýt:
            # 1. Vận tốc trung bình < CONGESTION_AVG_SPEED_KMPH (khi có >= 3 xe), HOẶC
            # 2. Tỷ lệ xe dừng/bò (v < BUS_STOPPED_SPEED_KMPH) >= CONGESTION_STOP_RATIO (khi có >= 4 xe)
            node_congested = (avg_speed < CONGESTION_AVG_SPEED_KMPH) or (bus_count >= 4 and crawl_ratio >= CONGESTION_STOP_RATIO)

        # B. Hợp nhất sự cố ngoại sinh (Incident Fusion)
        incident_cause = None
        if recent_incidents:
            for inc in recent_incidents:
                coords = inc.get("coordinates", [])
                inc_lat = None
                inc_lon = None
                if coords:
                    if isinstance(coords[0], list):
                        inc_lon, inc_lat = coords[0][0], coords[0][1]
                    elif len(coords) == 2 and isinstance(coords[0], (int, float)):
                        inc_lon, inc_lat = coords[0], coords[1]
                
                if inc_lat is not None and inc_lon is not None:
                    d_inc = haversine_distance(n_lat, n_lon, inc_lat, inc_lon)
                    if d_inc <= INCIDENT_PROXIMITY_METERS:
                        mag = inc.get("magnitude_of_delay", 0)
                        delay = inc.get("delay_seconds", 0)
                        if mag >= INCIDENT_CRITICAL_MAGNITUDE or delay >= INCIDENT_CRITICAL_DELAY_SEC:
                            node_congested = True
                            incident_cause = inc.get("description", "Sự cố giao thông nghiêm trọng")
                            break

        details[name] = {
            "bus_count": bus_count,
            "avg_speed": round(avg_speed, 1),
            "crawl_ratio": round(crawl_ratio, 2),
            "incident_cause": incident_cause,
            "is_congested": node_congested
        }

        if node_congested:
            congested_nodes.append(name)
            if is_core and (avg_speed < CONGESTION_CORE_CRITICAL_SPEED_KMPH or crawl_ratio >= CONGESTION_CORE_STOP_RATIO or incident_cause):
                has_critical_core_congestion = True

    # Ùn tắc hành lang: Có từ 2 nút bị tắc trở lên hoặc có 1 nút lõi tắc nghiêm trọng
    is_corridor_congested = (len(congested_nodes) >= 2) or has_critical_core_congestion

    return {
        "is_congested": is_corridor_congested,
        "congested_nodes": congested_nodes,
        "details": details
    }
