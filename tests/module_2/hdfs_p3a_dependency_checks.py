"""External HDFS manifest visibility and actual NameNode outage checks.

Creates only uniquely named test manifests/checkpoints and removes those in
finally. Does not import application code. Run while no other HDFS job runs.
"""
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

COMPOSE = ["docker", "compose", "-f", "docker-compose.hdfs.yml"]
ROOT = "hdfs://namenode:8020/bus-eta/v1"
PUBLISHED = ROOT + "/_published/bronze_to_silver"
URL = "http://127.0.0.1:8090/api/history/route-speed?route_code=08A&date_from=2026-10-08&date_to=2026-10-08"


def docker(*args, data=None):
    result = subprocess.run(COMPOSE + list(args), input=data, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def hdfs(*args, data=None):
    return docker("exec", "-T", "namenode", "hdfs", "dfs", *args, data=data)


def get():
    started = time.monotonic()
    try:
        response = urlopen(URL, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read()), round(time.monotonic() - started, 3)


def main():
    namespace = "blackbox-" + uuid4().hex
    checkpoint_path = ROOT + "/_checkpoints/bronze_to_silver/" + namespace + ".json"
    published_path = PUBLISHED + "/" + namespace + ".json"
    evidence = {"namespace": namespace}
    stopped = False
    try:
        original_path = next(line.split()[-1] for line in hdfs("-ls", PUBLISHED).splitlines() if line.endswith(".json"))
        manifest = json.loads(hdfs("-cat", original_path))
        checkpoint = json.loads(hdfs("-cat", manifest["checkpoint_path"]))
        baseline = get()
        assert baseline[0] == 200, baseline
        evidence["baseline"] = baseline
        # A different successful checkpoint without a publication must stay invisible.
        checkpoint["job_key"] = namespace
        hdfs("-put", "-", checkpoint_path, data=json.dumps(checkpoint))
        unpublished = get()
        assert unpublished[0] == 200 and unpublished[1]["rows"] == baseline[1]["rows"], unpublished
        evidence["unpublished_checkpoint_invisible"] = unpublished
        hdfs("-put", "-", published_path, data=json.dumps({"job_key": namespace, "checkpoint_path": checkpoint_path}))
        duplicate = get()
        assert duplicate[0] == 503 and duplicate[1]["error"] == "hdfs_unavailable", duplicate
        evidence["duplicate_published_window_rejected"] = duplicate
        hdfs("-rm", published_path)
        hdfs("-rm", checkpoint_path)
        assert get()[0] == 200
        docker("stop", "namenode")
        stopped = True
        outage = get()
        assert outage[0] == 503 and outage[1]["error"] == "hdfs_unavailable", outage
        assert outage[2] <= 25, outage
        evidence["actual_namenode_outage"] = outage
    finally:
        if stopped:
            docker("start", "namenode")
        # Never glob-delete: clean up exact test-owned paths only.
        for path in (published_path, checkpoint_path):
            try:
                hdfs("-rm", "-f", path)
            except RuntimeError:
                pass
    deadline = time.monotonic() + 90
    while True:
        restored = get()
        if restored[0] == 200:
            break
        if time.monotonic() >= deadline:
            raise AssertionError(restored)
        time.sleep(2)
    evidence["restored"] = restored
    output = Path("runtime/hdfs_p3a_blackbox")
    output.mkdir(parents=True, exist_ok=True)
    (output / "dependency_results.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == "__main__":
    main()
