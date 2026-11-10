"""Run one public SPEC-26 JSON fixture and compare its frozen output."""
from pathlib import Path
import json
import subprocess
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: verify_frenet_fixture.py INPUT.json EXPECTED.json")
output = Path(__file__).resolve().parent / ".frenet-fixture-output.json"
subprocess.run([sys.executable, str(Path(__file__).with_name("project_frenet_fixture.py")), sys.argv[1], str(output)], check=True)
if json.loads(output.read_text(encoding="utf-8")) != json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")):
    raise AssertionError("fixture output differs")
output.unlink()
print("fixture pass")
