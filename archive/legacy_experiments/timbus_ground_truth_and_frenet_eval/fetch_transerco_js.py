import urllib.request
import gzip
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

req = urllib.request.Request(
    'http://timbus.vn/js/transerco2.js',
    headers={'User-Agent': 'Mozilla/5.0'}
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        content = resp.read()
        if content[:2] == b'\x1f\x8b':
            content = gzip.decompress(content)
        # Check if utf-16
        try:
            js = content.decode('utf-16')
        except:
            js = content.replace(b'\x00', b'').decode('utf-8', errors='ignore')
            
        print(f"Decoded JS size: {len(js)} chars")
        
        # Search for endpoints
        endpoints = re.findall(r'["\']([^"\']+\.(?:ashx|aspx|asmx|php|json)[^"\']*)["\']', js)
        print("\nEndpoints:")
        for ep in set(endpoints):
            print(" ", ep)

        # Search for 'act='
        acts = re.findall(r'act=([a-zA-Z0-9_]+)', js)
        print("\nActs:")
        for a in set(acts):
            print(" ", a)
            
        # Search for functions
        funcs = re.findall(r'function\s+([a-zA-Z0-9_]+)\s*\(', js)
        print("\nFunctions count:", len(funcs))
        for f in set(funcs):
            if any(k in f.lower() for k in ['stop', 'station', 'route', 'fleet', 'bus', 'geo', 'point']):
                print("  fn:", f)

except Exception as e:
    print("Error:", e)

