"""
Module 2: OpenStreetMap Ground-Truth & Official Road Network Layer
Subcomponent: step_2_4_timbus_official_ground_truth_extractor
File: timbus_client.py

Client to interact with the official TRAMOC / TimBus portal (Transerco - Hanoi DoT)
to fetch official station catalogs, line geometries (polylines), and schedule data.
"""

import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMBUS_URL = "http://timbus.vn/Engine/Business/Search/action.ashx"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class TimBusClient:
    """HTTP Client for TimBus (Transerco / TRAMOC) internal API."""

    def __init__(
        self,
        endpoint_url: str = DEFAULT_TIMBUS_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: int = 15,
    ):
        self.endpoint_url = endpoint_url
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    def fetch_fleet_detail(self, fleet_id: str | int) -> Dict[str, Any]:
        """
        Fetch official fleet details including stations and polyline for a route.
        
        Args:
            fleet_id: The route ID on TimBus (e.g. 2 for Route 02, 32 for Route 32).
            
        Returns:
            Dictionary containing official route metadata, stations, and shape points.
            
        Raises:
            RuntimeError: If the server returns an error or status is False.
        """
        payload = urllib.parse.urlencode({
            "act": "fleetdetail",
            "fid": str(fleet_id)
        }).encode("utf-8")

        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "http://timbus.vn/",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        req = urllib.request.Request(self.endpoint_url, data=payload, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw_bytes = resp.read()
                raw_text = raw_bytes.decode("utf-8", errors="replace")
                data = json.loads(raw_text)

                if not data.get("st"):
                    err_msg = data.get("msg", "Unknown error from TimBus API")
                    raise RuntimeError(f"TimBus API returned status False: {err_msg}")

                dt = data.get("dt")
                if not dt:
                    raise RuntimeError("TimBus API returned empty 'dt' field")

                return {
                    "raw_text": raw_text,
                    "data": dt
                }
        except Exception as exc:
            logger.error("Failed to fetch TimBus fleet detail for fid=%s: %s", fleet_id, exc)
            raise

