import urllib.request
import json

url = "https://api.github.com/repos/toibinguz/Bus_tracking/actions/runs/39278459205"  # wait, let's get 3106 id
# First get run 3106 id
req = urllib.request.Request("https://api.github.com/repos/toibinguz/Bus_tracking/actions/runs?per_page=5", headers={"User-Agent": "Python"})
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())
    r3106 = data["workflow_runs"][0]
    run_id = r3106["id"]
    print(f"Run #{r3106['run_number']}, ID: {run_id}, status: {r3106['status']}, conclusion: {r3106['conclusion']}")

jobs_url = f"https://api.github.com/repos/toibinguz/Bus_tracking/actions/runs/{run_id}/jobs"
req_jobs = urllib.request.Request(jobs_url, headers={"User-Agent": "Python"})
with urllib.request.urlopen(req_jobs) as resp:
    jobs_data = json.loads(resp.read().decode())
    for j in jobs_data.get("jobs", []):
        print(f"Job: {j['name']}, status: {j['status']}, conclusion: {j['conclusion']}")
        for s in j.get("steps", []):
            print(f"  Step: {s['name']}, status: {s['status']}, conclusion: {s['conclusion']}, started: {s.get('started_at')}, completed: {s.get('completed_at')}")

