"""Run one public SPEC-26 JSON fixture and compare its frozen output."""
from pathlib import Path
import json
import subprocess
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: verify_frenet_fixture.py INPUT.json EXPECTED.json")
output = Path(__file__).resolve().parent / ".frenet-fixture-output.json"
mapping_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "frenet" / "p0_raw_direction_mapping.json"
mapping = json.loads(mapping_path.read_text(encoding="utf-8"))["raw_busmap_direction_to_hint"]
if mapping != {"0": "go", "1": "re", "-1": "unknown"}:
    raise AssertionError("P0 raw direction mapping fixture changed")
subprocess.run([sys.executable, str(Path(__file__).with_name("project_frenet_fixture.py")), sys.argv[1], str(output)], check=True)
if json.loads(output.read_text(encoding="utf-8")) != json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")):
    raise AssertionError("fixture output differs")
if Path(sys.argv[1]).name == "f6_real_slice_input.json":
    manifest = json.loads((Path(sys.argv[1]).with_name("f6_real_slice_manifest.json")).read_text(encoding="utf-8"))
    actual = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["accepted"]
    if [row["legacy_ping_id"] for row in actual] != manifest["legacy_ping_ids"]:
        raise AssertionError("F6 fixture does not match its frozen manifest")
output.unlink()
print("fixture pass")
