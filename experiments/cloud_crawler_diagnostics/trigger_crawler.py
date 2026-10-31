import urllib.request
import json
import subprocess

proc = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
out, _ = proc.communicate('protocol=https\nhost=github.com\n')
token = [l.split('=', 1)[1] for l in out.splitlines() if l.startswith('password=')][0]

url = "https://api.github.com/repos/toibinguz/Bus_tracking/actions/workflows/crawl_bus.yml/dispatches"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Python"
}
payload = json.dumps({"ref": "main"}).encode("utf-8")

req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

try:
    with urllib.request.urlopen(req) as resp:
        print(f"Trigger Response Status: {resp.status} (204 = Successfully Dispatched!)")
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code} - {e.read().decode()}")
except Exception as e:
    print(f"Error: {e}")

