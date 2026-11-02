import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

with open('experiments/fetch_transerco_js.py', 'r', encoding='utf-8') as f:
    pass

import urllib.request, gzip
req = urllib.request.Request('http://timbus.vn/js/transerco2.js', headers={'User-Agent': 'Mozilla/5.0'})
content = urllib.request.urlopen(req).read()
if content[:2] == b'\x1f\x8b': content = gzip.decompress(content)
js = content.replace(b'\x00', b'').decode('utf-8', errors='ignore')

# Search for Engine/Business/Route/action.ashx
for m in re.finditer(r'Engine/Business/Route/action\.ashx', js):
    start = max(0, m.start() - 200)
    end = min(len(js), m.end() + 500)
    print("=== SNIPPET ===")
    print(js[start:end])
    print()

for m in re.finditer(r'Engine/Business/Search/action\.ashx', js):
    start = max(0, m.start() - 200)
    end = min(len(js), m.end() + 500)
    print("=== SEARCH SNIPPET ===")
    print(js[start:end])
    print()

