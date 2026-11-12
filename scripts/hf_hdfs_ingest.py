"""U2: stage pinned HF raw batches offline, then receive them into private HDFS."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.hf_bronze import DockerHdfs, receive_batch, stage_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    stage = sub.add_parser('stage', help='HF reads only; Docker not required')
    stage.add_argument('--stage-dir', type=Path, required=True)
    stage.add_argument('--dataset')
    stage.add_argument('--revision')
    selection = stage.add_mutually_exclusive_group(required=True)
    selection.add_argument('--path', action='append')
    selection.add_argument('--date', type=date.fromisoformat)
    stage.add_argument('--category', choices=['bus', 'incidents', 'all'], default='all')
    upload = sub.add_parser('upload', help='local staging to HDFS only; no HF access')
    upload.add_argument('--stage-dir', type=Path, required=True)
    upload.add_argument('--failpoint', choices=['after_raw', 'before_receipt'])
    args = parser.parse_args()
    if args.command == 'stage':
        from huggingface_hub import HfApi, hf_hub_download
        from config import HF_DATASET_ID, get_hf_token
        dataset = args.dataset or HF_DATASET_ID
        token = get_hf_token() or None
        api = HfApi(token=token)
        revision = api.dataset_info(dataset, revision=args.revision).sha
        if args.path:
            paths = sorted(set(args.path))
        else:
            categories = {'bus', 'incidents'} if args.category == 'all' else {args.category}
            prefix = 'raw_data/' + args.date.isoformat() + '/'
            paths = sorted(path for path in api.list_repo_files(dataset, repo_type='dataset', revision=revision)
                           if path.startswith(prefix) and len(path.split('/')) == 4 and path.split('/')[2] in categories and path.endswith('.jsonl'))
        if not paths:
            raise ValueError('no batches selected at pinned revision')
        for path in paths:
            local = hf_hub_download(dataset, filename=path, repo_type='dataset', revision=revision, token=token)
            metadata = stage_batch(args.stage_dir, dataset, revision, path, Path(local).read_bytes())
            print(json.dumps(dict(event='staged', **metadata)), flush=True)
    else:
        sources = sorted(args.stage_dir.glob('*/sources/*.json'))
        if not sources:
            raise ValueError('no completed staged source descriptors')
        store = DockerHdfs(ROOT / 'docker-compose.hdfs.yml')
        for source in sources:
            print(json.dumps(receive_batch(args.stage_dir, source, store, args.failpoint)), flush=True)


if __name__ == '__main__':
    main()
