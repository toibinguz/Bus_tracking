import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.eta_history_baseline import verify_cache, run_cached_baseline


def test_incomplete_snapshot_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_cache(tmp_path)


def test_corruption_rejected_without_docker(tmp_path):
    data = tmp_path / 'part.parquet'
    data.write_bytes(b'original')
    (tmp_path / 'cache_manifest.json').write_text(json.dumps({'files': {name: hashlib.sha256(b'original').hexdigest() for name in ('silver/part-00000.parquet', 'stations.json', 'origin.json')}}))
    (tmp_path / 'silver').mkdir()
    (tmp_path / 'silver' / 'part-00000.parquet').write_bytes(b'corrupted')
    data.write_bytes(b'corrupted')
    with patch('subprocess.run', side_effect=AssertionError('offline must not call Docker')):
        with pytest.raises(ValueError, match='hash mismatch'):
            run_cached_baseline(tmp_path, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_manifest_cannot_escape_cache(tmp_path):
    (tmp_path / 'cache_manifest.json').write_text(json.dumps({'files': {'../other': 'bad'}}))
    with pytest.raises(ValueError, match='incomplete snapshot'):
        verify_cache(tmp_path)


def test_local_mode_retains_existing_builder_without_docker():
    from scripts.eta_history_baseline import main
    from module_3_bus_eta_prediction.step_3_1_historical_baseline_model import baseline_matrix_builder as builder
    with patch('sys.argv', ['eta_history_baseline.py']), patch.object(builder, 'build_and_evaluate_baseline_matrix') as baseline, patch('subprocess.run', side_effect=AssertionError('local mode must not call Docker')):
        main()
        baseline.assert_called_once_with()
