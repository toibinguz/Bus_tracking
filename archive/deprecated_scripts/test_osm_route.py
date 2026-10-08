import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def test_osm_bus():
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = """
    [out:json][timeout:10];
    relation["route"="bus"]["ref"="01"](20.95,105.75,21.10,105.90);
    out tags;
    """
    
    req = urllib.request.Request(overpass_url, data=query.encode("utf-8"), headers={"User-Agent": "BusTrackExp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elements = data.get("elements", [])
            print(f"[*] Tìm thấy {len(elements)} relations cho Tuyến 01 trong OpenStreetMap Hà Nội:")
            for e in elements:
                tags = e.get("tags", {})
                print(f"  - Relation ID: {e.get('id')} | Từ: {tags.get('from')} -> Đến: {tags.get('to')} | Hãng: {tags.get('operator')}")
    except Exception as e:
        print(f"Lỗi truy vấn Overpass OSM: {e}")

if __name__ == "__main__":
    test_osm_bus()
