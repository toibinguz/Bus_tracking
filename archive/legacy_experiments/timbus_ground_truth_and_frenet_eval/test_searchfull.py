import urllib.request, urllib.parse, json, sys
sys.stdout.reconfigure(encoding='utf-8')

url = "http://timbus.vn/Engine/Business/Search/action.ashx"

for k in ['', 'tuyen', 'buýt', 'xe']:
    data = urllib.parse.urlencode({'act': 'searchfull', 'typ': '1', 'key': k}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={
        'User-Agent': 'Mozilla/5.0',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'http://timbus.vn/'
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            dt = res.get('dt', {})
            total = dt.get('Total', 0) if isinstance(dt, dict) else 0
            data_len = len(dt.get('Data', [])) if isinstance(dt, dict) else 0
            print(f"Search typ=1 with key='{k}': Total={total}, Data count={data_len}")
    except Exception as e:
        print(f"Error key='{k}':", e)

