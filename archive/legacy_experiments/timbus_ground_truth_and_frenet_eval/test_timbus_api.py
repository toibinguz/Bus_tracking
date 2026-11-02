import urllib.request
import urllib.parse
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = "http://timbus.vn/Engine/Business/Search/action.ashx"
data = urllib.parse.urlencode({'act': 'fleetdetail', 'fid': '2'}).encode('utf-8')

req = urllib.request.Request(
    url,
    data=data,
    headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'http://timbus.vn/'
    }
)

with urllib.request.urlopen(req, timeout=10) as resp:
    res = json.loads(resp.read().decode('utf-8'))

stations = res['dt']['Go']['Station']
print(f"Total stations in Go direction: {len(stations)}")
for i, s in enumerate(stations):
    oid = s.get('ObjectID')
    name = s.get('Name')
    geo = s.get('Geo', {})
    lat = geo.get('Lat')
    lng = geo.get('Lng')
    print(f"{i+1:02d} | [{oid}] {name:<45} | ({lat:.6f}, {lng:.6f})")

