"""Actual U2 outage/recovery probe; restores NameNode in finally."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import DockerHdfs, stage_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-dir', type=Path, required=True)
    parser.add_argument('--recovery-stage', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if args.recovery_stage.exists() or args.evidence.exists():
        parser.error('recovery/evidence paths must be new')
    sources = sorted(args.stage_dir.glob('*/sources/*.json'))
    if not sources:
        raise ValueError('no source batches')
    expected = {}
    for source in sources:
        metadata = json.loads(source.read_text())
        content = (source.parent.parent / 'batch.jsonl').read_bytes()
        stage_batch(args.recovery_stage, metadata['dataset'], metadata['revision'], metadata['path'], content)
        expected[metadata['batch_id']] = metadata
    compose = ['docker','compose','-f',str(ROOT / 'docker-compose.hdfs.yml')]
    command = [sys.executable, str(ROOT / 'scripts/hf_hdfs_ingest.py'), 'upload', '--stage-dir', str(args.recovery_stage)]
    args.evidence.mkdir(parents=True)
    def run_probe(label, extra=(), timeout=300):
        start = time.monotonic()
        result = subprocess.run(command + list(extra), capture_output=True, timeout=timeout)
        (args.evidence / (label + '.txt')).write_bytes(result.stdout + result.stderr)
        return dict(exit_code=result.returncode, seconds=time.monotonic()-start)
    results = {}
    try:
        subprocess.run(compose + ['stop','namenode'], check=True, capture_output=True, timeout=30)
        results['actual_outage'] = run_probe('actual_outage', timeout=70)
        assert results['actual_outage']['exit_code'] != 0
        assert not list(args.recovery_stage.glob('*/receipts/*.json'))
        for batch_id, metadata in expected.items():
            assert hashlib.sha256((args.recovery_stage / batch_id / 'batch.jsonl').read_bytes()).hexdigest() == metadata['content_sha256']
    finally:
        subprocess.run(compose + ['start','namenode'], check=True, capture_output=True, timeout=30)
    store = DockerHdfs(ROOT / 'docker-compose.hdfs.yml')
    for attempt in range(15):
        try:
            store.call('-ls', '/bus-eta/v1')
            break
        except (RuntimeError, subprocess.TimeoutExpired):
            if attempt == 14:
                raise
            time.sleep(1)
    results['before_receipt'] = run_probe('before_receipt', ['--failpoint','before_receipt'])
    assert results['before_receipt']['exit_code'] != 0
    assert not list(args.recovery_stage.glob('*/receipts/*.json'))
    results['recovered'] = run_probe('recovered')
    assert results['recovered']['exit_code'] == 0
    results['repeated'] = run_probe('repeated')
    assert results['repeated']['exit_code'] == 0
    for label in ('recovered','repeated'):
        receipt_rows = [json.loads(line) for line in (args.evidence / (label + '.txt')).read_text().splitlines() if line.startswith('{')]
        assert len(receipt_rows) == len(sources)
        if label == 'repeated':
            assert all(row['already_received'] for row in receipt_rows)
    results['batch_ids'] = sorted(expected)
    results['staging_preserved_during_outage'] = True
    results['all_remote_bytes_verified_by_receiver'] = True
    results['receipts'] = len(list(args.recovery_stage.glob('*/receipts/*.json')))
    (args.evidence / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results), flush=True)


if __name__ == '__main__':
    main()
