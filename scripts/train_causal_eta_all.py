"""Build route-sized Silver replays and train one global ETA model."""

import argparse
import gc
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.train_causal_eta import replay_silver, select_partitions
from module_3_bus_eta_prediction.causal_eta import CATEGORICAL, FEATURES, CausalFeatures
from module_3_bus_eta_prediction.causal_eta_training import (
    BASE, ResidualETA, TrainingReplay, baseline_cutoff_epoch, digest, epoch,
)
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.data_access import DataAccess


def build_routes(args):
    import sqlite3
    with sqlite3.connect(args.baseline.resolve().as_uri() + '?mode=ro', uri=True) as db:
        cutoff, = db.execute('SELECT fit_end_date FROM eta_baseline_manifest').fetchone()
    if date.fromisoformat(cutoff) >= date.fromisoformat(args.from_day):
        raise ValueError('baseline overlaps feature replay')
    partitions = select_partitions(args.silver, date.fromisoformat(args.from_day), date.fromisoformat(args.to_day), [])
    routes = sorted({p.parent.parent.name.removeprefix('route_code=') for paths in partitions.values() for p in paths})
    destination = args.output / 'features'
    destination.mkdir(parents=True, exist_ok=True)
    identity = dict(baseline=digest(args.baseline), catalog=digest(args.catalog),
                    validation=args.validation_start, test=args.test_start,
                    from_day=args.from_day, to_day=args.to_day, cadence=args.forecast_every,
                    inputs={str(p): digest(p) for paths in partitions.values() for p in paths},
                    code={str(p): digest(p) for p in (
                        Path(__file__), ROOT/'scripts/train_causal_eta.py',
                        ROOT/'module_3_bus_eta_prediction/causal_eta.py',
                        ROOT/'module_3_bus_eta_prediction/causal_eta_training.py',
                        ROOT/'module_1_data_ingestion_and_preprocessing/step_1_4_frenet_spatial_projection/route_matcher.py')})
    manifest = args.output / 'feature_inputs.json'
    if manifest.exists():
        if json.loads(manifest.read_text()) != identity:
            raise ValueError('feature inputs changed during resume')
    else:
        manifest.write_text(json.dumps(identity, indent=2), encoding='utf-8')
    for index, code in enumerate(routes, 1):
        target = destination / f'{code}.parquet'
        if target.exists():
            print(f'[{index}/{len(routes)}] resume {code}', flush=True)
            continue
        selected = {day: [p for p in paths if p.parent.parent.name == f'route_code={code}']
                    for day, paths in partitions.items()}
        selected = {day: paths for day, paths in selected.items() if paths}
        replay = TrainingReplay(CausalFeatures(DataAccess(db_path=str(args.catalog), baseline_db_path=str(args.baseline))))
        replay_silver(replay, selected, baseline_cutoff_epoch(cutoff), args.forecast_every)
        rows = []
        for row in replay.labeled(epoch(args.validation_start), epoch(args.test_start)):
            label = row['label']
            speed = row['speeds']['ego5']
            rows.append(dict(row['features'], route=code, vehicle=row['vehicle'], journey=row['journey'],
                             target=row['target'], split=row['split'], as_of=row['as_of'],
                             eta_seconds=row['eta_seconds'], bracket_before=label['before_epoch'],
                             bracket_after=label['after_epoch'], crossing_epoch=label['epoch'],
                             history_seconds=speed['seconds'] if speed else 0))
        counts = dict(replay.counts)
        del replay
        frame = pd.DataFrame(rows)
        del rows
        if not frame.empty:
            frame[list(FEATURES)] = frame[list(FEATURES)].astype('float32')
        temporary = target.with_suffix('.tmp')
        frame.to_parquet(temporary, index=False)
        temporary.rename(target)
        (destination / f'{code}.json').write_text(json.dumps(counts, indent=2), encoding='utf-8')
        print(f'[{index}/{len(routes)}] route {code} rows {len(frame):,} {counts}', flush=True)
        del frame
        gc.collect()
    return identity


def train(args, identity):
    model_path = args.output / 'model.json'
    if model_path.exists():
        raise FileExistsError(model_path)
    files = sorted((args.output / 'features').glob('*.parquet'))
    columns = [*FEATURES, 'route', 'journey', 'target', 'split', 'eta_seconds', 'history_seconds']
    parts = []
    for path in files:
        if pd.read_parquet(path).empty:
            continue
        parts.append(pd.read_parquet(path, columns=columns))
    frame = pd.concat(parts, ignore_index=True)
    del parts
    domains = {'route_id_idx': sorted(frame.loc[frame.split == 'train', 'route_id_idx'].unique().tolist()),
               'direction_id': [0, 1], 'day_type': [0, 1, 2], 'hour_slot': list(range(5, 22))}
    supported = frame.route_id_idx.isin(domains['route_id_idx'])
    unsupported = frame.loc[~supported].groupby(['route', 'split']).size()
    frame = frame[supported].copy()
    for column in CATEGORICAL:
        frame[column] = pd.Categorical(frame[column], categories=domains[column])
    counts = frame.groupby('split').size().to_dict()
    if set(counts) != {'train', 'validation', 'test'}:
        raise ValueError(f'incomplete temporal splits {counts}')
    weights = 1 / frame.groupby(['split', 'route', 'journey', 'target']).eta_seconds.transform('size')
    weights /= weights.groupby(frame.split).transform('mean')
    fit = frame.split == 'train'
    validation = frame.split == 'validation'
    print(f'training 300 rounds on {counts}', flush=True)
    model = xgb.XGBRegressor(objective='reg:absoluteerror', eval_metric='mae', n_estimators=args.rounds,
                             max_depth=4, learning_rate=.05, tree_method='hist', enable_categorical=True,
                             random_state=42, n_jobs=2)
    model.fit(frame.loc[fit, FEATURES], (frame.eta_seconds-frame[BASE])[fit], sample_weight=weights[fit],
              eval_set=[(frame.loc[fit, FEATURES], (frame.eta_seconds-frame[BASE])[fit]),
                        (frame.loc[validation, FEATURES], (frame.eta_seconds-frame[BASE])[validation])],
              sample_weight_eval_set=[weights[fit], weights[validation]], verbose=25)
    history = model.evals_result()
    best = int(np.argmin(history['validation_1']['mae']))
    model.get_booster().set_attr(best_iteration=str(best), best_score=str(history['validation_1']['mae'][best]))
    test = frame[frame.split == 'test'].copy()
    test['prediction'] = np.maximum(5, model.predict(test.loc[:, FEATURES]) + test[BASE].to_numpy())

    def score(group):
        result = {}
        for name, prediction in [('baseline', group[BASE]), ('model', group.prediction)]:
            error = prediction - group.eta_seconds
            absolute = error.abs()
            balanced = absolute.groupby([group.route, group.journey, group.target]).mean()
            result[name] = dict(rows=len(group), mae=float(absolute.mean()), median_ae=float(absolute.median()),
                                p90_ae=float(absolute.quantile(.9)), bias=float(error.mean()),
                                crossings=len(balanced), crossing_balanced_mae=float(balanced.mean()))
        return result

    evaluation = dict(overall=score(test), rows_by_split=counts,
                      unsupported_routes={str(key): int(value) for key, value in unsupported.items()},
                      per_route={route: score(group) for route, group in test.groupby('route')}, by_horizon={})
    for name, lo, hi in [('1',1,1), ('2-5',2,5), ('6-15',6,15), ('16+',16,float('inf'))]:
        group = test[test.n_stations_ahead.between(lo, hi)]
        if len(group):
            evaluation['by_horizon'][name] = score(group)
    model.save_model(model_path)
    metadata = dict(schema='causal-eta.v1', features=FEATURES, category_domains=domains,
                    hashes={'model': digest(model_path)}, best_iteration=best, trained_rounds=args.rounds,
                    training_history=history, provenance=identity, evaluation=evaluation,
                    feature_files={str(path): digest(path) for path in files})
    (args.output/'manifest.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    reloaded = ResidualETA.load(args.output)
    np.testing.assert_allclose(np.maximum(5, reloaded.model.predict(test.loc[:, FEATURES])+test[BASE].to_numpy()),
                               test.prediction.to_numpy())
    test.drop(columns=list(FEATURES)).to_parquet(args.output/'test_predictions.parquet', index=False)
    print(json.dumps(evaluation['overall'], indent=2), flush=True)
    print(f'completed rounds {args.rounds}, selected {best+1}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--silver', required=True, type=Path)
    parser.add_argument('--catalog', required=True, type=Path)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--from-day', default='2026-10-18')
    parser.add_argument('--to-day', default='2026-11-07')
    parser.add_argument('--validation-start', default='2026-10-24T00:00:00+07:00')
    parser.add_argument('--test-start', default='2026-11-02T00:00:00+07:00')
    parser.add_argument('--forecast-every', type=float, default=120)
    parser.add_argument('--rounds', type=int, default=300)
    arguments = parser.parse_args()
    train(arguments, build_routes(arguments))
