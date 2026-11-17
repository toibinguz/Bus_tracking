"""Launch the real demo from a local release, inspect HTTP, and stop without stdin.

Windows-only launcher verification; uses an isolated port and stops only its own
process group. It never stops Docker or an existing user's demo process.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.eta_snapshot import inspect_active


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pointer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows launcher verification requires Windows')
    if args.output.exists():
        parser.error('choose a fresh output directory')
    args.output.mkdir(parents=True)
    before = inspect_active(args.pointer)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    command = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               str(ROOT/'run_demo.ps1'), '-Port', str(port), '-NoBrowser',
               '-ReleasePointer', str(args.pointer.resolve())]
    responses = {}
    forced = False
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    with (args.output/'launcher.log').open('wb') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            deadline = time.monotonic()+60
            while time.monotonic() < deadline:
                try:
                    with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as reply:
                        health = json.load(reply)
                    if health['serving']['artifact_id'] != before['artifact_id']:
                        raise AssertionError('server selected another release')
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError('launcher exited before readiness')
                    time.sleep(.25)
            else:
                raise AssertionError('release demo did not become ready')
            responses['health'] = health
            for endpoint in ('routes', 'route-shape?route=02&direction=0', 'route-stations?route=02&direction=0'):
                with urlopen(f'http://127.0.0.1:{port}/api/{endpoint}', timeout=10) as reply:
                    responses[endpoint] = json.load(reply)
        finally:
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    forced = True
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'], capture_output=True, check=False)
                    process.wait(timeout=10)
    after = inspect_active(args.pointer)
    text = (args.output/'launcher.log').read_text(encoding='utf-8', errors='replace')
    result = dict(started_at=started_at,command=command,
                  elapsed_sec=round(time.monotonic()-started,3),stdin_closed=True,
                  forced_cleanup=forced,graceful_shutdown='Application shutdown complete' in text,
                  artifact_unchanged=before==after,responses=responses,
                  limitation='catalog/geometry HTTP and lifecycle only; no live ETA accuracy claim; Docker left untouched')
    (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert not forced and result['graceful_shutdown'], 'normal shutdown was not verified; see launcher.log'
    assert result['artifact_unchanged']
    print(json.dumps({key:value for key,value in result.items() if key not in ('responses','command')},ensure_ascii=False))


if __name__ == '__main__':
    main()
