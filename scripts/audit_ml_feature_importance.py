"""Measure the deployed candidate's feature use on frozen recorded inputs.

This is residual TreeSHAP, not a causal effect or an accuracy measurement.
Inputs precede the HMM installation; the report explicitly preserves that scope.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(session, output):
    model_path = session / 'artifacts/model.json'
    metadata_path = session / 'artifacts/metadata.json'
    trace_path = session / 'backend/trace.jsonl'
    manifest = json.loads((session / 'session.json').read_text(encoding='utf-8'))
    assert sha(model_path) == manifest['health']['serving']['model']['model_sha256']
    assert sha(metadata_path) == manifest['health']['serving']['model']['metadata_sha256']
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    archived = {row['feature']: row for row in metadata['feature_importance']}
    rows = []
    for line in trace_path.open(encoding='utf-8'):
        row = json.loads(line)
        if row['kind'] == 'eta_result' and row['result']['prediction_source'] == 'ml_calibrated':
            rows.append(row['features'])
    model = xgb.XGBRegressor(n_jobs=2)
    model.load_model(model_path)
    model.set_params(n_jobs=2)
    booster = model.get_booster()
    rounds = model.best_iteration + 1
    used = booster[:rounds]
    used.set_param({'nthread': 2})
    frame = pd.DataFrame(rows).reindex(columns=booster.feature_names)
    numeric = frame.copy()
    for key in ('route_id_idx', 'direction_id', 'day_type', 'hour_slot'):
        frame[key] = frame[key].astype('int32').astype('category')
    # Preserve training category codes when this live cohort contains only a
    # subset of routes/hours. A plain DMatrix silently uses local category codes.
    matrix = xgb.DMatrix(frame, enable_categorical=True, feature_types=booster.get_categories())
    contributions = booster.predict(matrix, pred_contribs=True, iteration_range=(0, rounds))
    error = float(np.max(np.abs(contributions.sum(axis=1) - model.predict(frame))))
    assert error < .02, error
    gain = used.get_score(importance_type='total_gain')
    average_gain = used.get_score(importance_type='gain')
    cover = used.get_score(importance_type='cover')
    total_cover = used.get_score(importance_type='total_cover')
    weight = used.get_score(importance_type='weight')
    gain_sum = sum(gain.values())
    stored_gain = booster.get_score(importance_type='total_gain')
    stored_weight = booster.get_score(importance_type='weight')
    ledger_error = max(abs(stored_gain.get(key, 0) - archived[key]['total_gain'])
                       / max(1, abs(archived[key]['total_gain'])) for key in booster.feature_names)
    assert ledger_error < 1e-5, ledger_error
    assert all(int(stored_weight.get(key, 0)) == archived[key]['split_count'] for key in booster.feature_names)
    features = {}
    for index, key in enumerate(booster.feature_names):
        series = numeric[key]
        features[key] = dict(
            total_gain_share_percent=100 * gain.get(key, 0) / gain_sum,
            total_gain=float(gain.get(key, 0)), average_gain=float(average_gain.get(key, 0)),
            average_cover=float(cover.get(key, 0)), total_cover=float(total_cover.get(key, 0)),
            archived_training=archived[key],
            splits=int(weight.get(key, 0)),
            mean_abs_residual_shap_sec=float(np.abs(contributions[:, index]).mean()),
            mean_residual_shap_sec=float(contributions[:, index].mean()),
            observed_unique=int(series.nunique()), minimum=float(series.min()),
            median=float(series.median()), maximum=float(series.max()),
            missing=int(series.isna().sum()))
    report = dict(scope='Recorded 2026-11-17 pre-HMM feature vectors; not current HMM replay, not held-out accuracy or causal effects',
                  rows=len(rows), xgboost=xgb.__version__, stored_rounds=booster.num_boosted_rounds(),
                  used_rounds=rounds, max_shap_additivity_error_sec=error,
                  archived_ledger_max_relative_gain_error=ledger_error,
                  model_sha256=sha(model_path), metadata_sha256=sha(metadata_path),
                  trace_sha256=sha(trace_path), script_sha256=sha(Path(__file__)),
                  features=features)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'features'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.session, args.output)
