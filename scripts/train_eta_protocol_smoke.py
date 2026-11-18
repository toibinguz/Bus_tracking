"""Train/reload a bounded global-model fixture with clean temporal provenance.

Writes only a fresh experimental output. This never promotes or overwrites a
production model, and its scores are pipeline checks, not acceptance evidence.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluate_eta_candidate import fingerprint,metrics
from module_3_bus_eta_prediction.temporal_contract import require_validation_provenance
from module_3_bus_eta_prediction.step_3_3_machine_learning_models import eta_model_trainer as trainer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('choose fresh experimental output')
    if ROOT not in args.output.resolve().parents:parser.error('output must be inside workspace')
    provenance=require_validation_provenance(args.features)
    protected={p:fingerprint(p) for p in (ROOT/'data/models').glob('*.json')}
    args.output.mkdir(parents=True)
    started=time.monotonic()
    fit,val=trainer.load_stratified_train_and_val_splits(str(args.features/'split=train'),5000,2000)
    if fit.empty or val.empty:raise ValueError('need both fitting and validation rows')
    assert fit.dt.max()<'2026-10-24'<=val.dt.min()
    model,_=trainer.train_xgb_residual_model(fit,val,trainer.ALL_54_FEATURES,'SPEC41_PIPELINE_SMOKE',n_estimators=64,max_depth=4)
    calibration=trainer.fit_per_route_empirical_bayes_calibrator(val,trainer.predict_eta_with_residual_model(model,val,trainer.ALL_54_FEATURES))
    model_path=args.output/'model.json';model.save_model(model_path)
    meta=dict(all_features=trainer.ALL_54_FEATURES,calibrator={'_'.join(map(str,key)):list(value) for key,value in calibration.items()},
              training_provenance=provenance,acceptance_status='not_accepted_pipeline_smoke',
              parameters=dict(n_estimators=64,max_depth=4,max_fit_rows_per_route=5000,max_val_rows_per_route=2000))
    (args.output/'metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    loaded=xgb.XGBRegressor(n_jobs=2);loaded.load_model(model_path)
    test=pd.concat([pd.read_parquet(p) for p in sorted((args.features/'split=test').glob('route_code=*/*.parquet'))],ignore_index=True)
    before=trainer.predict_eta_with_residual_model(model,test,trainer.ALL_54_FEATURES)
    after=trainer.predict_eta_with_residual_model(loaded,test,trainer.ALL_54_FEATURES)
    assert np.array_equal(before,after) and np.isfinite(after).all()
    predictions=trainer.apply_per_route_calibrator(test,after,calibration)
    assert all(fingerprint(path)==expected for path,expected in protected.items())
    result=dict(status='pipeline_training_smoke_passed_not_promoted',fit_rows=len(fit),validation_rows=len(val),test_rows=len(test),
                fit_dates=sorted(fit.dt.unique()),validation_dates=sorted(val.dt.unique()),test_dates=sorted(test.dt.unique()),
                model_sha256=fingerprint(model_path),metadata_sha256=fingerprint(args.output/'metadata.json'),
                reload_exact=True,original_models_unchanged=True,baseline=metrics(test.actual_eta_sec,test.baseline_eta_p50_sec),
                model=metrics(test.actual_eta_sec,predictions),elapsed_sec=round(time.monotonic()-started,3))
    (args.output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('TRAINING_SMOKE='+json.dumps(result),flush=True)


if __name__=='__main__':main()
