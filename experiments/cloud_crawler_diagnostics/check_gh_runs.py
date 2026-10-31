import urllib.request
import json

url = "https://api.github.com/repos/toibinguz/Bus_tracking/actions/runs?per_page=20"
req = urllib.request.Request(url, headers={"User-Agent": "Python"})

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        runs = data.get("workflow_runs", [])
        print(f"Total runs returned: {len(runs)}")
        for r in runs:
            print(f"Run #{r['run_number']}: status={r['status']}, conclusion={r['conclusion']}, created={r['created_at']}, event={r['event']}, head_commit={r['head_commit']['message'][:40] if r.get('head_commit') else ''}")
except Exception as e:
    print(f"Error fetching runs: {e}")

