"""Fit the global ETA model from completed route Parquet checkpoints."""

import argparse
import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import xgboost as xgb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_3_bus_eta_prediction.step_3_2_feature_store_extractor.causal_eta import CATEGORICAL, FEATURES
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.causal_eta_training import BASE, ResidualETA, build_xgb_regressor, digest


def load_split(files, split):
    columns = [*FEATURES, 'route', 'journey', 'target', 'eta_seconds']
    parts = []
    for path in files:
        frame = pd.read_parquet(path, columns=columns, filters=[('split', '==', split)])
        if not frame.empty:
            frame['journey'] = frame.journey.astype('int32')
            frame['target'] = frame.target.astype('int16')
            parts.append(frame)
    result = pd.concat(parts, ignore_index=True)
    result['route'] = result.route.astype('category')
    return result


def weights(frame):
    size = frame.groupby(['route', 'journey', 'target'], observed=True).eta_seconds.transform('size')
    weight = (1 / size).to_numpy(dtype='float32')
    return weight / weight.mean()


def encode(frame, domains):
    for column in CATEGORICAL:
        frame[column] = pd.Categorical(frame[column].astype('int32'), categories=domains[column])


def score(frame):
    result = {}
    for name, column in [('baseline', BASE), ('model', 'prediction')]:
        errors = frame[column] - frame.eta_seconds
        absolute = errors.abs()
        balanced = absolute.groupby([frame.route, frame.journey, frame.target], observed=True).mean()
        result[name] = dict(rows=len(frame), mae=float(absolute.mean()), median_ae=float(absolute.median()),
                            p90_ae=float(absolute.quantile(.9)), bias=float(errors.mean()),
                            crossings=len(balanced), crossing_balanced_mae=float(balanced.mean()))
    return result


def run(root, rounds, max_depth=4, features_dir=None):
    if (root/'model.json').exists():
        raise FileExistsError(root/'model.json')
    feat_root = Path(features_dir) if features_dir else (root/'features')
    files = sorted(feat_root.glob('*.parquet'))
    if len(files) != 48 or any(not path.with_suffix('.json').exists() for path in files):
        raise ValueError('all 48 route checkpoints must be complete')
    train = load_split(files, 'train')
    domains = {'route_id_idx': sorted(int(x) for x in train.route_id_idx.unique()), 'direction_id': [0, 1],
               'day_type': [0, 1, 2], 'hour_slot': list(range(5, 22))}
    encode(train, domains)
    validation = load_split(files, 'validation')
    if not validation.route_id_idx.isin(domains['route_id_idx']).all():
        raise ValueError('validation contains routes absent from training')
    encode(validation, domains)
    counts = {'train': len(train), 'validation': len(validation)}
    print(f'global training rows {counts}', flush=True)
    model = build_xgb_regressor(rounds, max_depth=max_depth)
    model.fit(train.loc[:, FEATURES], train.eta_seconds - train[BASE], sample_weight=weights(train),
              eval_set=[(validation.loc[:, FEATURES], validation.eta_seconds - validation[BASE])],
              sample_weight_eval_set=[weights(validation)], verbose=25)
    history = model.evals_result()
    best = int(getattr(model, 'best_iteration', int(np.argmin(history['validation_0']['mae']))))
    model.get_booster().set_attr(best_iteration=str(best), best_score=str(history['validation_0']['mae'][best]))
    del train, validation
    gc.collect()
    output = root/'test_predictions'
    output.mkdir(exist_ok=False)
    predictions = []
    missing_test = []
    for path in files:
        frame = pd.read_parquet(path, filters=[('split', '==', 'test')])
        if frame.empty:
            missing_test.append(path.stem)
            continue
        if not frame.route_id_idx.isin(domains['route_id_idx']).all():
            raise ValueError('test contains routes absent from training')
        encode(frame, domains)
        frame['prediction'] = np.maximum(
            5, model.predict(frame.loc[:, FEATURES], iteration_range=(0, best + 1)) + frame[BASE].to_numpy()
        )
        retained = frame[['route', 'vehicle', 'journey', 'target', 'as_of', 'eta_seconds', BASE,
                          'prediction', 'n_stations_ahead', 'history_seconds', 'bracket_before', 'bracket_after']]
        retained.to_parquet(output/path.name, index=False)
        predictions.append(retained.drop(columns=['vehicle']))
        print(f'evaluated {path.stem} {len(frame):,}', flush=True)
    test = pd.concat(predictions, ignore_index=True)
    counts['test'] = len(test)
    evaluation = dict(overall=score(test), rows_by_split=counts, routes_without_test=missing_test,
                      per_route={str(route): score(group) for route, group in test.groupby('route')}, by_horizon={})
    for name, lo, hi in [('1',1,1), ('2-5',2,5), ('6-15',6,15), ('16+',16,float('inf'))]:
        group = test[test.n_stations_ahead.between(lo, hi)]
        if len(group):
            evaluation['by_horizon'][name] = score(group)
    model.save_model(root/'model.json')
    metadata = dict(schema='causal-eta.v1', features=FEATURES, category_domains=domains,
                    hashes={'model': digest(root/'model.json')}, best_iteration=best, trained_rounds=rounds,
                    training_history=history, provenance=json.loads((root/'feature_inputs.json').read_text()),
                    training_code_sha256=digest(Path(__file__)), evaluation=evaluation,
                    feature_files={str(path): digest(path) for path in files})
    (root/'manifest.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    restored = ResidualETA.load(root)
    for path in files:
        sample = pd.read_parquet(path, filters=[('split', '==', 'test')]).head(10)
        if sample.empty:
            continue
        rows = sample[list(FEATURES)].replace({np.nan: None}).to_dict('records')
        original = np.maximum(5, model.predict(pd.DataFrame({
            col: pd.Categorical(sample[col].astype('int32'), categories=domains[col]) if col in domains else sample[col]
            for col in FEATURES}), iteration_range=(0, best + 1))+sample[BASE].to_numpy())
        np.testing.assert_allclose(restored.predict(rows), original, rtol=1e-5, atol=.001)
    print(json.dumps(evaluation['overall'], indent=2), flush=True)
    print(f'completed {rounds} rounds, selected {best+1}, test routes {len(evaluation["per_route"])}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--rounds', type=int, default=300)
    parser.add_argument('--max-depth', type=int, default=4)
    parser.add_argument('--features-dir', type=Path, default=None)
    args = parser.parse_args()
    run(args.root, args.rounds, max_depth=args.max_depth, features_dir=args.features_dir)
