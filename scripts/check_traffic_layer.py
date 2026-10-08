import urllib.request
import re

url = 'https://maps.vietmap.vn/docs/map-api/traffic-layer/'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')
    # strip tags
    text = re.sub(r'<(h[1-6]|p|div|tr|li)[^>]*>', r'\n\g<0>', html)
    text = re.sub(r'</(h[1-6]|p|div|tr|li)>', r'\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n\s*\n', '\n', text)
    with open('data/vietmap_traffic_layer.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    print('Fetched traffic-layer! Size:', len(text))
except Exception as e:
    print('Error:', e)

