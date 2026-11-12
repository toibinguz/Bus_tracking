"""Read-only U1 inspection: pin HF revision and inspect bounded raw batches."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def describe(content):
    rows = [json.loads(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
    keys = Counter(key for row in rows for key in row)
    timestamps = {}
    for name in ('device_update_time', 'crawled_at', 'timestamp', 'start_time', 'end_time'):
        counts = Counter()
        for row in rows:
            value = row.get(name)
            if value is None:
                counts['missing'] += 1
                continue
            try:
                parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                counts['offset_present' if parsed.tzinfo else 'offset_missing'] += 1
            except ValueError:
                counts['invalid'] += 1
        timestamps[name] = dict(counts)
    return dict(rows=len(rows), bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                keys=dict(keys), directions=dict(Counter(str(row.get('direction')) for row in rows)),
                quality_status=dict(Counter(str(row.get('quality_status')) for row in rows)),
                timestamps=timestamps, samples=rows[:2])


def reference_profile(content, database):
    rows = [json.loads(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        routes = dict(conn.execute('SELECT route_id,route_code FROM canonical_route_master'))
        station_rows = conn.execute('SELECT route_id,station_id,direction FROM canonical_station_master ORDER BY route_id,station_id,direction').fetchall()
    lookup = {}
    for route, station, direction in station_rows:
        lookup.setdefault((route, station), set()).add(direction)
    counts, cross = Counter(), Counter()
    for row in rows:
        counts['known_route' if row.get('route_id') in routes else 'unknown_route'] += 1
        directions = lookup.get((row.get('route_id'), row.get('current_station_id')), set())
        label = next(iter(directions)) if len(directions) == 1 else ('ambiguous' if directions else 'missing')
        cross[f"{row.get('direction')} -> {label}"] += 1
    return dict(database=str(Path(database).resolve()), route_counts=dict(counts),
                raw_direction_vs_station=dict(sorted(cross.items())),
                reference_rows_sha256=hashlib.sha256(json.dumps(dict(routes=sorted(routes.items()), stations=station_rows), sort_keys=True).encode()).hexdigest())


def main():
    from huggingface_hub import HfApi, hf_hub_download
    from config import HF_DATASET_ID, get_hf_token

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', help='pin an existing commit for repeat inspection')
    parser.add_argument('--reference-db', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must be a new directory')
    token = get_hf_token() or None
    dataset = os.environ.get('HF_DATASET_ID') or HF_DATASET_ID
    api = HfApi(token=token)
    revision = api.dataset_info(dataset, revision=args.revision).sha
    files = api.list_repo_files(dataset, repo_type='dataset', revision=revision)
    report = dict(dataset=dataset, revision=revision, files_total=len(files), categories={})
    args.output.mkdir(parents=True)
    for category in ('bus', 'incidents'):
        matches = sorted(path for path in files if path.startswith('raw_data/') and f'/{category}/' in path and path.endswith('.jsonl'))
        if not matches:
            report['categories'][category] = dict(available_files=0, status='absent')
            continue
        path = matches[-1]
        local = hf_hub_download(dataset, filename=path, repo_type='dataset', revision=revision, token=token)
        content = Path(local).read_bytes()
        (args.output / f'{category}.jsonl').write_bytes(content)
        report['categories'][category] = dict(path=path, available_files=len(matches), **describe(content))
        if category == 'bus' and args.reference_db:
            report['reference_profile'] = reference_profile(content, args.reference_db)
    (args.output / 'inspection.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
