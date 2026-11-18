"""Replay model/calibration components from captured features, with hash checks."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluate_eta_candidate import fingerprint
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import predict_eta_with_residual_model, apply_per_route_calibrator


def replay(session, output):
    session,output=Path(session),Path(output)
    if output.exists():raise ValueError('choose fresh replay output')
    manifest=json.loads((session/'session.json').read_text(encoding='utf-8'))
    identity=manifest['health']['serving']['model']
    model_path=ROOT/'data/models/eta_xgb_global_full_54feat_r3_big.json'
    metadata_path=ROOT/'data/models/eta_xgb_metadata_and_calibrator_r3_big.json'
    bundle=session/'artifact_bundle.json'
    if bundle.is_file():
        archived=json.loads(bundle.read_text())['files']
        model_path=session/archived['model']['path'];metadata_path=session/archived['metadata']['path']
    if fingerprint(model_path)!=identity['model_sha256'] or fingerprint(metadata_path)!=identity['metadata_sha256']:
        raise ValueError('captured model identity does not match available files')
    model=xgb.XGBRegressor(n_jobs=2);model.load_model(model_path);model.set_params(n_jobs=2)
    meta=json.loads(metadata_path.read_text())
    calibration={tuple(map(int,k.split('_'))):tuple(v) for k,v in meta['calibrator'].items()}
    maximum=0.;count=0;fallback=0;pending=[]
    def flush():
        nonlocal maximum,count
        if not pending:return
        frame=pd.DataFrame([r['features'] for r in pending])
        # JSON loses pandas integer widths; restore the runtime's categorical ABI.
        for column in ('route_id_idx','direction_id','day_type','hour_slot'):
            if column in frame:frame[column]=frame[column].astype('int32')
        predicted=apply_per_route_calibrator(frame,predict_eta_with_residual_model(model,frame,model.get_booster().feature_names),calibration)
        expected=np.array([r['result']['eta_seconds'] for r in pending])
        maximum=max(maximum,float(np.max(np.abs(predicted-expected))))
        count+=len(pending);pending.clear()
    for line in (session/'backend/trace.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['kind']!='eta_result':continue
        if row['result']['prediction_source']!='ml_calibrated':fallback+=1;continue
        pending.append(row)
        if len(pending)>=4096:flush()
    flush()
    result=dict(model_predictions=count,baseline_fallbacks=fallback,max_abs_error_seconds=maximum,
                tolerance_seconds=.101,passed=count>0 and maximum<=.101,
                scope='model plus calibrator from recorded features; HTTP rounds to 0.1 seconds; not full upstream/state replay')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not result['passed']:raise AssertionError(result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--session',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(replay(args.session,args.output)))
