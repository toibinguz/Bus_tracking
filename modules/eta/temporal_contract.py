"""Date boundaries shared by baseline fitting, label extraction and ML validation."""
from datetime import date, timedelta
import hashlib
from itertools import groupby
from pathlib import Path
import json

MODEL_VALIDATION_START_DATE = '2026-10-24'
MODEL_BASELINE_FIT_END_DATE = (date.fromisoformat(MODEL_VALIDATION_START_DATE)-timedelta(days=1)).isoformat()


def split_at_dates(pings, cutoffs):
    cutoffs=sorted(set(cutoffs))
    for cutoff in cutoffs: date.fromisoformat(cutoff)
    def window(ping):
        day=ping[0]
        date.fromisoformat(day)
        return sum(day>cutoff for cutoff in cutoffs)
    return [list(group) for _,group in groupby(pings,key=window)]


def require_validation_provenance(feature_root, validation_start=MODEL_VALIDATION_START_DATE):
    path=Path(feature_root)/'feature_store_manifest.json'
    if not path.is_file():
        raise ValueError('feature store lacks provenance; rebuild before training a new accepted model')
    value=json.loads(path.read_text(encoding='utf-8'))
    cutoff=value.get('baseline_fit_end_date')
    if cutoff is None or date.fromisoformat(cutoff)>=date.fromisoformat(validation_start):
        raise ValueError('baseline fitting overlaps validation; rebuild with an earlier baseline fit cutoff')
    files=value.get('files',{})
    root=Path(feature_root).resolve()
    if not files or set(files)!={p.relative_to(root).as_posix() for p in root.rglob('*.parquet')}:
        raise ValueError('feature input file manifest incomplete')
    for relative,expected in files.items():
        target=(root/relative).resolve()
        if root not in target.parents:
            raise ValueError('feature manifest path outside root')
        with target.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:
                raise ValueError('feature input hash mismatch')
    return value
