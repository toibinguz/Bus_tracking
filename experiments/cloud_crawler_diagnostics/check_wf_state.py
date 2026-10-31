import urllib.request
import json
import subprocess

proc = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
out, _ = proc.communicate('protocol=https\nhost=github.com\n')
token = [l.split('=', 1)[1] for l in out.splitlines() if l.startswith('password=')][0]

req = urllib.request.Request(
    'https://api.github.com/repos/toibinguz/Bus_tracking/actions/workflows/378026361',
    headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'Python'}
)

with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())
    print("Workflow Name:", data.get("name"))
    print("Workflow State:", data.get("state"))

