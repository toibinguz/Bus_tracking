import urllib.request, gzip, re, sys
sys.stdout.reconfigure(encoding='utf-8')

req = urllib.request.Request('http://timbus.vn/js/transerco2.js', headers={'User-Agent': 'Mozilla/5.0'})
content = urllib.request.urlopen(req).read()
if content[:2] == b'\x1f\x8b': content = gzip.decompress(content)
js = content.replace(b'\x00', b'').decode('utf-8', errors='ignore')

for act in ['partremained', 'searchfull']:
    print(f"=== USAGE OF {act} ===")
    for m in re.finditer(act, js):
        start = max(0, m.start() - 200)
        end = min(len(js), m.end() + 300)
        print(js[start:end])
        print("-" * 50)

