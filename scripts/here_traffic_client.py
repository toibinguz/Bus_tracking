"""
HERE Traffic & Routing API Client for Bus Tracking & ETA Prediction
Author: Antigravity Big Data Architecture Team
Description:
    Demonstrates how to exploit HERE Traffic Flow API v7 and Routing API v8
    under HERE's Free Plan (Freemium: 30,000 - 250,000 req/month).
"""

import urllib.request
import urllib.parse
import json
import os
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class HereTrafficClient:
    FLOW_ENDPOINT = "https://data.traffic.hereapi.com/v7/flow"
    ROUTING_ENDPOINT = "https://router.hereapi.com/v8/routes"

    def __init__(self, api_key: str = None):
        # Look for environment variable or local config file
        self.api_key = api_key or os.environ.get("HERE_API_KEY")
        if not self.api_key:
            # Check if a local file exists
            key_file = os.path.join(os.path.dirname(__file__), "..", "Test_here", "HERE_API_KEY.txt")
            if os.path.exists(key_file):
                with open(key_file, "r", encoding="utf-8") as f:
                    self.api_key = f.read().strip()

    def classify_jam_factor(self, jam_factor: float) -> dict:
        """
        Map HERE's continuous jamFactor (0.0 to 10.0) into discrete traffic classes:
        - 0.0 <= jamFactor < 4.0: GREEN (Thông thoáng)
        - 4.0 <= jamFactor < 7.0: YELLOW (Ùn ứ / Chậm)
        - 7.0 <= jamFactor < 9.0: RED (Tắc nghẽn nặng)
        - 9.0 <= jamFactor <= 10.0: DARK_RED (Tê liệt / Đóng đường)
        """
        if jam_factor < 4.0:
            return {"level": "FREE_FLOW", "color": "GREEN", "desc": "Thông thoáng"}
        elif jam_factor < 7.0:
            return {"level": "MODERATE", "color": "YELLOW", "desc": "Ùn ứ / Chậm"}
        elif jam_factor < 9.0:
            return {"level": "HEAVY", "color": "RED", "desc": "Tắc nghẽn"}
        else:
            return {"level": "SEVERE", "color": "DARK_RED", "desc": "Tê liệt / Đóng đường"}

    def get_flow_by_bbox(self, west: float, south: float, east: float, north: float, min_jam_factor: float = None):
        """
        Query traffic flow for an entire urban area using a single Bounding Box request.
        Example Hanoi Center: bbox:105.78,20.97,105.86,21.05
        """
        if not self.api_key:
            print("[WARN] HERE_API_KEY not configured. Returning mock/url info.")
            return None

        params = {
            "in": f"bbox:{west:.5f},{south:.5f},{east:.5f},{north:.5f}",
            "locationReferencing": "shape",
            "apiKey": self.api_key
        }
        if min_jam_factor is not None:
            params["minJamFactor"] = str(min_jam_factor)

        url = f"{self.FLOW_ENDPOINT}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "HanoiBusTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        parsed_segments = []
        for item in data.get("results", []):
            loc = item.get("location", {})
            flow = item.get("currentFlow", {})
            speed_ms = flow.get("speed", 0.0)
            freeflow_ms = flow.get("freeFlow", 0.0)
            jam = flow.get("jamFactor", 0.0)

            parsed_segments.append({
                "street": loc.get("description", "Unknown"),
                "length_m": loc.get("length", 0.0),
                "speed_kmh": round(speed_ms * 3.6, 1),
                "freeflow_kmh": round(freeflow_ms * 3.6, 1),
                "jam_factor": jam,
                "classification": self.classify_jam_factor(jam),
                "confidence": flow.get("confidence", 1.0)
            })
        return parsed_segments

    def get_bus_route_eta(self, origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float):
        """
        Use HERE Routing API v8 with transportMode=bus to calculate realistic bus ETA
        and granular per-span speeds.
        """
        if not self.api_key:
            print("[WARN] HERE_API_KEY not configured.")
            return None

        params = {
            "transportMode": "bus",
            "origin": f"{origin_lat:.5f},{origin_lon:.5f}",
            "destination": f"{dest_lat:.5f},{dest_lon:.5f}",
            "return": "summary,polyline",
            "spans": "dynamicSpeedInfo,names",
            "apiKey": self.api_key
        }
        url = f"{self.ROUTING_ENDPOINT}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "HanoiBusTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        routes = data.get("routes", [])
        if not routes:
            return None
        
        route = routes[0]
        section = route.get("sections", [{}])[0]
        summary = section.get("summary", {})
        
        spans_data = []
        for span in section.get("spans", []):
            speed_info = span.get("dynamicSpeedInfo", {})
            spans_data.append({
                "names": span.get("names", []),
                "length_m": span.get("length", 0),
                "traffic_speed_kmh": round(speed_info.get("trafficSpeed", 0) * 3.6, 1),
                "base_speed_kmh": round(speed_info.get("baseSpeed", 0) * 3.6, 1),
                "traffic_time_s": speed_info.get("trafficTime", 0),
                "base_time_s": speed_info.get("baseTime", 0)
            })

        return {
            "total_distance_m": summary.get("length", 0),
            "total_duration_s": summary.get("duration", 0),
            "base_duration_s": summary.get("baseDuration", 0),
            "delay_s": max(0, summary.get("duration", 0) - summary.get("baseDuration", 0)),
            "spans_count": len(spans_data),
            "spans_sample": spans_data[:5]
        }

if __name__ == "__main__":
    print("=== HERE Traffic Client Architecture Test ===")
    client = HereTrafficClient()
    print("API Key loaded:", "YES" if client.api_key else "NO (Ready to accept key)")
    print("\nDemonstration of Jam Factor Classification:")
    for jam in [1.2, 5.5, 7.8, 9.6]:
        print(f"Jam Factor {jam:4.1f} -> {client.classify_jam_factor(jam)}")
