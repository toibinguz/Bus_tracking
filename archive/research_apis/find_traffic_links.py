import urllib.request
import urllib.parse
import re

url = 'https://maps.vietmap.vn/docs/map-api/overview/'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')
    matches = re.findall(r'href=[\'"]([^\'"]*)[\'"]', html)
    for m in matches:
        if 'traffic' in m.lower():
            full = urllib.parse.urljoin(url, m)
            print('Href:', m, '--> Full URL:', full)
except Exception as e:
    print('Error:', e)

