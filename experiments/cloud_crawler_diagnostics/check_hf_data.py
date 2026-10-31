import urllib.request
import json
import sys
import os

sys.path.insert(0, os.path.abspath("."))
from config.system_config import get_hf_token

token = get_hf_token()
headers = {"User-Agent": "Python", "Authorization": f"Bearer {token}"}
hf_url = "https://huggingface.co/api/datasets/Toibinguz/hust-bus-data/tree/main/raw_data"
req = urllib.request.Request(hf_url, headers=headers)

try:
    with urllib.request.urlopen(req) as resp:
        files = json.loads(resp.read().decode())
        for f in sorted(files, key=lambda x: x['path']):
            print(f['path'])
except Exception as e:
    print(f"Error checking HF: {e}")
