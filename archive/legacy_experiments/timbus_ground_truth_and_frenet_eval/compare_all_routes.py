import urllib.request, urllib.parse, json, sys
sys.stdout.reconfigure(encoding='utf-8')

# 1. Fetch 165 routes from TimBus
url = "http://timbus.vn/Engine/Business/Search/action.ashx"
data = urllib.parse.urlencode({'act': 'searchfull', 'typ': '1', 'key': ''}).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={
    'User-Agent': 'Mozilla/5.0',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'http://timbus.vn/'
})
with urllib.request.urlopen(req, timeout=10) as resp:
    tb_routes = json.loads(resp.read().decode('utf-8'))['dt']['Data']

print(f"Total TimBus routes fetched: {len(tb_routes)}")

# 2. Load BusMap routes
with open("data/metadata/routes.json", "r", encoding="utf-8") as f:
    bm_routes = json.load(f)

print(f"Total BusMap routes loaded: {len(bm_routes)}")

# 3. Compare route numbers (Code / FleedCode in TimBus vs routeNo in BusMap)
tb_by_code = {r.get('FleedCode', '').strip(): r for r in tb_routes}
bm_by_code = {r.get('routeNo', '').strip(): r for r in bm_routes}

matched_codes = set(tb_by_code.keys()).intersection(set(bm_by_code.keys()))
print(f"\nMatching route numbers (e.g. '01', '02', '32'...): {len(matched_codes)}")

print("\n--- SAMPLE COMPARISON OF ROUTE IDENTIFIERS ---")
print(f"{'Route No':<10} | {'TimBus ObjectID':<16} | {'BusMap routeId':<16} | {'BusMap id':<12} | {'ID Match?'}")
print("-" * 75)
sample_codes = ['01', '02', '03A', '07', '08A', '09A', '22A', '27', '32', '34', '107', 'BRT01', 'E01']
for sc in sample_codes:
    tb_r = tb_by_code.get(sc, {})
    bm_r = bm_by_code.get(sc, {})
    tb_oid = tb_r.get('ObjectID', 'N/A')
    bm_rid = bm_r.get('routeId', 'N/A')
    bm_id = bm_r.get('id', 'N/A')
    is_match = "TRUNG KHOP" if str(tb_oid) == str(bm_rid) else "KHAC NHAU"
    print(f"{sc:<10} | {str(tb_oid):<16} | {str(bm_rid):<16} | {str(bm_id):<12} | {is_match}")

