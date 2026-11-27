"""Fit the global ETA model from completed route Parquet checkpoints."""

import argparse
import gc
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from config.hardware_guard import (
    check_gpu_thermal_and_vram,
    check_memory_pressure,
    recommended_xgb_threads,
    set_process_below_normal_priority,
)
from modules.eta.features.causal_eta import CATEGORICAL, FEATURES
from modules.eta.training.causal_eta_training import (
    BASE,
    MONOTONE_INCIDENT_FEATURES,
    MONOTONE_SPEED_FEATURES,
    ResidualETA,
    build_xgb_regressor,
    digest,
)


def load_split(files, split):
    columns = [*FEATURES, 'route', 'journey', 'target', 'eta_seconds']
    parts = []
    for path in files:
        frame = pd.read_parquet(path, columns=columns, filters=[('split', '==', split)])
        if not frame.empty:
            frame['journey'] = frame.journey.astype('int32')
            frame['target'] = frame.target.astype('int16')
            parts.append(frame)
    if not parts:
        return pd.DataFrame()
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


def _scan_train_stats(files, splits=('train', 'validation')):
    """Quét nhanh 3 cột để lấy route_id_idx domains, tổng số dòng và mean_weight chính xác mà không load toàn bộ RAM."""
    route_ids = set()
    total_rows = 0
    total_weight_sum = 0.0
    split_filter = [('split', 'in', list(splits))]
    for path in files:
        meta = pd.read_parquet(path, columns=['route_id_idx', 'journey', 'target'], filters=split_filter)
        if meta.empty:
            continue
        route_ids.update(int(x) for x in meta.route_id_idx.unique())
        total_rows += len(meta)
        # Mỗi (journey, target) đóng góp tổng trọng số đúng bằng 1.0 (= n_groups)
        total_weight_sum += float(meta.groupby(['journey', 'target'], sort=False).ngroups)
    domains = {
        'route_id_idx': sorted(route_ids),
        'direction_id': [0, 1],
        'day_type': [0, 1, 2],
        'hour_slot': list(range(5, 22)),
    }
    mean_weight = (total_weight_sum / total_rows) if total_rows else 1.0
    return domains, total_rows, mean_weight


class _ParquetTrainIter(xgb.DataIter):
    """Stream từng file tuyến vào xgb.QuantileDMatrix để tránh phình RAM/Commit."""

    def __init__(self, files, domains, mean_weight, splits=('train', 'validation')):
        self._files = list(files)
        self._domains = domains
        self._mean_weight = float(mean_weight)
        self._splits = list(splits)
        self._idx = 0
        super().__init__()

    def reset(self):
        self._idx = 0

    def next(self, input_data):
        while self._idx < len(self._files):
            path = self._files[self._idx]
            self._idx += 1
            cols = [*FEATURES, 'journey', 'target', 'eta_seconds']
            frame = pd.read_parquet(path, columns=cols, filters=[('split', 'in', self._splits)])
            if frame.empty:
                continue
            encode(frame, self._domains)
            size = frame.groupby(['journey', 'target'], sort=False)['eta_seconds'].transform('size')
            w = ((1.0 / size) / self._mean_weight).to_numpy(dtype='float32')
            y = (frame['eta_seconds'] - frame[BASE]).to_numpy(dtype='float32')
            x = frame[list(FEATURES)]
            input_data(data=x, label=y, weight=w)
            del frame, x, y, w, size
            return 1
        return 0


def run(
    root,
    rounds,
    max_depth=4,
    features_dir=None,
    use_validation=True,
    reference_model=None,
    device='cuda',
    early_stopping_rounds: int | None = None,
    early_stop_on_test: bool = False,
):
    set_process_below_normal_priority()
    nthread = recommended_xgb_threads()
    if (root/'model.json').exists():
        raise FileExistsError(root/'model.json')
    feat_root = Path(features_dir) if features_dir else (root/'features')
    files = sorted(feat_root.glob('*.parquet'))
    if len(files) != 48 or any(not path.with_suffix('.json').exists() for path in files):
        raise ValueError('all 48 route checkpoints must be complete')
    check_memory_pressure(label='before_fit')
    if device == 'cuda':
        gpu_status = check_gpu_thermal_and_vram(min_free_vram_mb=2200)
        if gpu_status.get('overheated'):
            raise RuntimeError(f"GPU overheated ({gpu_status['reason']}); aborting CUDA training to protect hardware.")
        if not gpu_status.get('use_cuda'):
            device = 'cpu'
    if use_validation:
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
        best_score = history['validation_0']['mae'][best]
        del train, validation
    else:
        domains, n_train, mean_weight = _scan_train_stats(files, splits=('train', 'validation'))
        counts = {'train': n_train, 'validation': 0}
        use_es = bool(early_stop_on_test and early_stopping_rounds and int(early_stopping_rounds) > 0)
        print(
            f'global training rows {counts} (no-valid, streaming QuantileDMatrix, device={device}, '
            f'early_stop_on_test={use_es}, es_rounds={early_stopping_rounds})',
            flush=True,
        )
        it = _ParquetTrainIter(files, domains, mean_weight, splits=('train', 'validation'))
        dtrain = xgb.QuantileDMatrix(it, max_bin=256, enable_categorical=True)
        gc.collect()
        constraints = tuple(
            -1 if f in MONOTONE_SPEED_FEATURES else (1 if f in MONOTONE_INCIDENT_FEATURES else 0)
            for f in FEATURES
        )
        params = {
            'objective': 'reg:absoluteerror',
            'eval_metric': 'mae',
            'max_depth': int(max_depth),
            'learning_rate': 0.05,
            'tree_method': 'hist',
            'device': device,
            'max_bin': 256,
            'monotone_constraints': constraints,
            'seed': 42,
            'nthread': nthread,
        }
        history = {}
        if use_es:
            _, n_valid, valid_mean_w = _scan_train_stats(files, splits=('test',))
            counts['validation'] = n_valid
            it_valid = _ParquetTrainIter(files, domains, valid_mean_w, splits=('test',))
            dvalid = xgb.QuantileDMatrix(it_valid, ref=dtrain, max_bin=256, enable_categorical=True)
            gc.collect()
            bst = xgb.train(
                params,
                dtrain,
                num_boost_round=int(rounds),
                evals=[(dvalid, 'valid_test')],
                early_stopping_rounds=int(early_stopping_rounds),
                evals_result=history,
                verbose_eval=100,
            )
            del dvalid, it_valid
            gc.collect()
            best = int(getattr(bst, 'best_iteration', int(bst.num_boosted_rounds()) - 1))
            val_curve = history.get('valid_test', {}).get('mae', [])
            best_score = float(val_curve[best]) if 0 <= best < len(val_curve) else float(getattr(bst, 'best_score', 0.0))
        else:
            bst = xgb.train(params, dtrain, num_boost_round=int(rounds), verbose_eval=False)
            best = int(bst.num_boosted_rounds()) - 1
            best_score = None
        bst.set_param({'device': 'cpu', 'nthread': nthread})
        del dtrain, it
        gc.collect()
        model = xgb.XGBRegressor(n_estimators=int(rounds), max_depth=int(max_depth), tree_method='hist', enable_categorical=True, n_jobs=nthread)
        model._Booster = bst
    if best_score is not None:
        model.get_booster().set_attr(best_iteration=str(best), best_score=str(best_score))
    else:
        model.get_booster().set_attr(best_iteration=str(best))
    gc.collect()
    output = root/'test_predictions'
    output.mkdir(exist_ok=False)
    predictions = []
    missing_test = []
    float32_eval_cols = (
        'as_of', 'eta_seconds', BASE, 'prediction',
        'history_seconds', 'bracket_before', 'bracket_after', 'inc_ahead_total_delay_sec',
    )
    for idx_file, path in enumerate(files, start=1):
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
                          'prediction', 'n_stations_ahead', 'history_seconds', 'bracket_before', 'bracket_after',
                          'inc_ahead_total_delay_sec']].copy()
        retained.to_parquet(output/path.name, index=False)
        compact = retained.drop(columns=['vehicle']).copy()
        compact['route'] = compact['route'].astype('category')
        compact['journey'] = compact['journey'].astype('int32')
        compact['target'] = compact['target'].astype('int16')
        compact['n_stations_ahead'] = compact['n_stations_ahead'].astype('int16')
        for fcol in float32_eval_cols:
            if fcol in compact.columns:
                compact[fcol] = compact[fcol].astype('float32')
        predictions.append(compact)
        print(f'evaluated {path.stem} {len(frame):,}', flush=True)
        del frame, retained
        if idx_file % 6 == 0:
            gc.collect()
            check_memory_pressure(label=f'eval={path.stem}')
    test = pd.concat(predictions, ignore_index=True)
    del predictions
    gc.collect()
    counts['test'] = len(test)
    evaluation = dict(overall=score(test), rows_by_split=counts, routes_without_test=missing_test,
                      per_route={str(route): score(group) for route, group in test.groupby('route')},
                      by_horizon={}, by_incident={})
    for name, lo, hi in [('1', 1, 1), ('2-5', 2, 5), ('6-15', 6, 15), ('16+', 16, float('inf'))]:
        group = test[test.n_stations_ahead.between(lo, hi)]
        if len(group):
            evaluation['by_horizon'][name] = score(group)
    for name, mask in [('no_incident', test.inc_ahead_total_delay_sec.fillna(0) <= 0),
                       ('has_incident', test.inc_ahead_total_delay_sec.fillna(0) > 0)]:
        group = test[mask]
        if len(group):
            evaluation['by_incident'][name] = score(group)

    if reference_model is not None:
        del test
        gc.collect()
        ref_runner = ResidualETA.load(reference_model)
        ref_runner.model.set_params(n_jobs=nthread)
        ref_preds = []
        for idx_file, path in enumerate(files, start=1):
            frame = pd.read_parquet(path, filters=[('split', '==', 'test')])
            if frame.empty:
                continue
            ref_frame = frame[['route', 'journey', 'target', 'eta_seconds', BASE, 'inc_ahead_total_delay_sec']].copy()
            encode(frame, ref_runner.domains)
            unknown_mask = frame['route_id_idx'].isna().to_numpy()
            base_vals = frame[BASE].to_numpy()
            if unknown_mask.all():
                ref_frame['prediction'] = np.maximum(5.0, base_vals)
            else:
                res_vals = ref_runner._predict_raw(frame[list(ref_runner.features)])
                ref_frame['prediction'] = np.maximum(5.0, np.where(unknown_mask, base_vals, res_vals + base_vals))
            ref_frame['route'] = ref_frame['route'].astype('category')
            ref_frame['journey'] = ref_frame['journey'].astype('int32')
            ref_frame['target'] = ref_frame['target'].astype('int16')
            for fcol in ('eta_seconds', BASE, 'inc_ahead_total_delay_sec', 'prediction'):
                ref_frame[fcol] = ref_frame[fcol].astype('float32')
            ref_preds.append(ref_frame)
            del frame
            if idx_file % 6 == 0:
                gc.collect()
                check_memory_pressure(label=f'ref_eval={path.stem}')
        ref_test = pd.concat(ref_preds, ignore_index=True)
        del ref_preds
        gc.collect()
        ref_eval = {
            'reference_model': str(reference_model),
            'overall': score(ref_test),
            'by_incident': {},
        }
        for name, mask in [('no_incident', ref_test.inc_ahead_total_delay_sec.fillna(0) <= 0),
                           ('has_incident', ref_test.inc_ahead_total_delay_sec.fillna(0) > 0)]:
            group = ref_test[mask]
            if len(group):
                ref_eval['by_incident'][name] = score(group)
        (root / 'reference_eval.json').write_text(json.dumps(ref_eval, indent=2), encoding='utf-8')
        print('[REFERENCE EVAL]', json.dumps(ref_eval['overall'], indent=2), flush=True)
    model.save_model(root/'model.json')
    metadata = dict(schema='causal-eta.v1', features=FEATURES, category_domains=domains,
                    hashes={'model': digest(root/'model.json')}, best_iteration=best, trained_rounds=rounds,
                    early_stopped_on_test=bool(not use_validation and early_stop_on_test and early_stopping_rounds),
                    early_stopping_rounds=early_stopping_rounds,
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
            for col in FEATURES}), iteration_range=(0, best + 1)) + sample[BASE].to_numpy())
        np.testing.assert_allclose(restored.predict(rows), original, rtol=1e-5, atol=.001)
    print(json.dumps(evaluation['overall'], indent=2), flush=True)
    print(f'completed {rounds} rounds, selected {best+1}, test routes {len(evaluation["per_route"])}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--rounds', type=int, default=300)
    parser.add_argument('--max-depth', type=int, default=4)
    parser.add_argument('--features-dir', type=Path, default=None)
    parser.add_argument('--no-valid', action='store_true')
    parser.add_argument('--reference-model', type=Path, default=None)
    parser.add_argument('--device', default='cuda', choices=['cuda', 'cpu'])
    parser.add_argument('--early-stop-on-test', action='store_true')
    parser.add_argument('--early-stopping-rounds', type=int, default=None)
    args = parser.parse_args()
    run(
        args.root,
        args.rounds,
        max_depth=args.max_depth,
        features_dir=args.features_dir,
        use_validation=not args.no_valid,
        reference_model=args.reference_model,
        device=args.device,
        early_stopping_rounds=args.early_stopping_rounds,
        early_stop_on_test=args.early_stop_on_test,
    )
