import json
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from modules.eta.features.causal_eta import CATEGORICAL, FEATURES
from modules.eta.training.causal_eta_training import ResidualETA
from modules.eta.serving.model_runtime import ModelRuntime
from modules.eta.serving import request_trace


def test_model_runtime_matches_causal_batch_and_rejects_unknown_route():
    domains = {
        'route_id_idx': [0, 1],
        'direction_id': [0, 1],
        'day_type': [0, 1, 2],
        'hour_slot': list(range(5, 22)),
    }
    rows = []
    for i in range(16):
        row = {f: float(i) for f in FEATURES}
        row.update({
            'route_id_idx': i % 2,
            'direction_id': (i // 2) % 2,
            'day_type': i % 3,
            'hour_slot': 5 + (i % 4),
            'baseline_eta_p50_sec': 100.0 + i,
            'n_stations_ahead': [1, 2, 6, 16][i % 4],
        })
        rows.append(row)
    frame = pd.DataFrame(rows, columns=FEATURES, dtype=float)
    for col in CATEGORICAL:
        frame[col] = pd.Categorical(frame[col], categories=domains[col])
    model = xgb.XGBRegressor(n_estimators=4, max_depth=2, n_jobs=1, enable_categorical=True, tree_method='hist')
    model.fit(frame, np.arange(16, dtype='float32') * 2 - 8)
    residual = ResidualETA(model, domains, best_iteration=2)
    expected = residual.predict(rows, allow_unknown_routes=False)
    runtime = ModelRuntime(residual_eta=residual)
    actual = [runtime.predict_p50(row) for row in rows]
    assert actual == pytest.approx(expected, abs=1e-4)

    unknown = dict(rows[0], route_id_idx=999)
    assert runtime.predict_p50(unknown) is None


def test_trace_io_failure_does_not_change_prediction(tmp_path, monkeypatch):
    blocker = tmp_path / 'file-not-directory'
    blocker.write_text('occupied')
    monkeypatch.setenv('ETA_TRACE_DIR', str(blocker))

    class Constant:
        def predict(self, frame):
            return np.array([10.0])

    domains = {'route_id_idx': [0], 'direction_id': [0, 1], 'day_type': [0, 1, 2], 'hour_slot': list(range(5, 22))}
    runtime = ModelRuntime(residual_eta=ResidualETA(Constant(), domains))
    row = {f: 0.0 for f in FEATURES}
    row.update(dict(route_id_idx=0, direction_id=0, day_type=0, hour_slot=8, n_stations_ahead=1, baseline_eta_p50_sec=100.0))
    assert runtime.predict_p50(row) == pytest.approx(110.0)


def test_request_ids_correlate_http_and_trace_and_reset_between_requests(tmp_path,monkeypatch):
    from modules.eta.web_demo import app as web
    monkeypatch.setenv('ETA_TRACE_DIR',str(tmp_path))
    class Service:
        source_info=dict(mode='test')
        def get_routes(self):
            request_trace.record('test_event')
            return []
    monkeypatch.setattr(web,'service',Service())
    with TestClient(web.app) as client:
        first=client.get('/api/routes');second=client.get('/api/routes')
    rows=[json.loads(x) for x in (tmp_path/'trace.jsonl').read_text().splitlines()]
    assert [r['request_id'] for r in rows]==[first.headers['X-Request-ID'],second.headers['X-Request-ID']]
    assert rows[0]['request_id']!=rows[1]['request_id']
    assert request_trace.request_id.get() is None
