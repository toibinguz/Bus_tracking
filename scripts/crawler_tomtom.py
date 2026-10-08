import os
import sys
import json
import time
import urllib.request
import ssl
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

API_KEY_FILE = "Test_tomtom/TOMTOM_API_KEY.txt"
OUTPUT_DIR = "data/raw/traffic"
BBOX_HANOI = "105.703949,20.933177,106.011921,21.252462" # BBox chuan Ha Noi tu map_raw.txt
MAX_DAILY_REQUESTS = 2200 # Gioi han an toan duoi tran 2500

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get_api_key():
    if os.path.exists(API_KEY_FILE):
        with open(API_KEY_FILE, "r") as f:
            return f.read().strip()
    return os.environ.get("TOMTOM_API_KEY", "")

def get_sleep_interval():
    now = datetime.now()
    hour = now.hour + now.minute / 60.0
    # Gio cao diem sang (6h30 - 9h00) va chieu (16h30 - 19h30): Quet 3 phut/lan
    if (6.5 <= hour <= 9.0) or (16.5 <= hour <= 19.5):
        return 180 # 3 phut
    # Gio dem (22h00 - 5h30): Nghi 15 phut/lan de tiet kiem quota
    elif hour >= 22.0 or hour < 5.5:
        return 900 # 15 phut
    # Gio binh thuong ban ngay: 5 phut/lan
    else:
        return 300 # 5 phut

def fetch_macro_incidents(api_key):
    url = (
        f"https://api.tomtom.com/traffic/services/5/incidentDetails"
        f"?key={api_key}&bbox={BBOX_HANOI}&language=vi-VN"
        f"&fields={{incidents{{type,geometry{{type,coordinates}},properties{{iconCategory,magnitudeOfDelay,delay,length}}}}}}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "BusTrackingBot/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    api_key = get_api_key()
    if not api_key:
        print("Loi: Chua tim thay TomTom API Key!")
        return

    print("[*] Bat dau Crawler Giao thong TomTom (2 Tang)...")
    print(f"[*] BBox Ha Noi: {BBOX_HANOI}")
    
    daily_counter = 0
    current_day = datetime.now().day

    while True:
        now = datetime.now()
        if now.day != current_day:
            daily_counter = 0
            current_day = now.day

        if daily_counter >= MAX_DAILY_REQUESTS:
            print("[CANH BAO] Da cham nguong quota an toan trong ngay! Tam nghi den ngay mai...")
            time.sleep(3600)
            continue

        try:
            start_t = time.time()
            data = fetch_macro_incidents(api_key)
            daily_counter += 1
            incidents = data.get("incidents", [])
            
            # Ghi vao file log
            date_str = now.strftime("%Y-%m-%d")
            out_file = os.path.join(OUTPUT_DIR, f"incidents_{date_str}.jsonl")
            
            payload = {
                "timestamp": now.isoformat(),
                "total_incidents": len(incidents),
                "incidents": incidents
            }
            with open(out_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

            elapsed = time.time() - start_t
            sleep_sec = get_sleep_interval()
            print(f"[{now.strftime('%H:%M:%S')}] TomTom Tang 1: Thu thap {len(incidents)} su co trong {elapsed:.1f}s | Quota hom nay: {daily_counter}/{MAX_DAILY_REQUESTS} | Nghi {sleep_sec}s")
            time.sleep(sleep_sec)

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Loi TomTom API: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()

