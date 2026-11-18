"""Bounded, read-only evaluation of frozen candidates on current test partitions.

This evaluates current labels; it does not assert original training provenance,
independent label correctness, or that an historically reused test is untouched.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import xgboost as xgb

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import predict_eta_with_residual_model, apply_per_route_calibrator


def fingerprint(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def metrics(actual, predicted):
    actual=np.asarray(actual,dtype=float); error=np.asarray(predicted,dtype=float)-actual
    absolute=np.abs(error)
    eligible=actual>=30
    return dict(n=len(actual),bias_sec=float(error.mean()),mae_sec=float(absolute.mean()),
                median_absolute_sec=float(np.median(absolute)),p90_absolute_sec=float(np.quantile(absolute,.9)),
                wape_pct=float(100*absolute.sum()/actual.sum()),
                mape_ge30_pct=float(100*np.mean(absolute[eligible]/actual[eligible])) if eligible.any() else None,
                mape_ge30_n=int(eligible.sum()),within_30sec_pct=float(100*np.mean(absolute<=30)),
                within_60sec_pct=float(100*np.mean(absolute<=60)),
                actual_below_prediction_pct=float(100*np.mean(error>=0)),
                signed_percent_quantiles_ge30={str(q):float(np.quantile(100*error[eligible]/actual[eligible],q)) for q in (.05,.25,.5,.75,.95)} if eligible.any() else {})


def validate_batch(frame, route, split, route_index):
    failures={}
    def check(name,mask):
        count=int(np.count_nonzero(mask))
        if count: failures[name]=count
    check('nonfinite_label',~np.isfinite(frame.actual_eta_sec))
    check('invalid_eta_label',(frame.actual_eta_sec<5)|(frame.actual_eta_sec>7200))
    check('route_index_mismatch',frame.route_id_idx!=route_index)
    check('invalid_direction',~frame.direction_id.isin([0,1]))
    check('invalid_day_type',~frame.day_type.isin([0,1,2]))
    check('invalid_hour',~frame.hour_slot.between(5,21))
    check('nonpositive_horizon',frame.n_stations_ahead<1)
    check('nonpositive_remaining_distance',frame.remaining_distance_m<=0)
    check('timestamp_day_mismatch',pd.to_datetime(frame.device_epoch,unit='s',utc=True).dt.tz_convert('Asia/Ho_Chi_Minh').dt.strftime('%Y-%m-%d')!=frame.dt)
    check('split_date_violation',frame.dt<('2026-11-01') if split=='test' else frame.dt>'2026-10-31')
    return failures


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=ROOT/'data/lakehouse/gold/eta_feature_store')
    parser.add_argument('--batch-size',type=int,default=32768)
    args=parser.parse_args()
    if args.output.exists(): parser.error('choose fresh output')
    args.output.mkdir(parents=True)
    started=time.monotonic()
    metadata_path=ROOT/'data/models/eta_xgb_metadata_and_calibrator_r3_big.json'
    metadata=json.loads(metadata_path.read_text())
    calibrator={tuple(map(int,k.split('_'))):tuple(v) for k,v in metadata['calibrator'].items()}
    models={}
    model_files={}
    for role,name in [('full','eta_xgb_global_full_54feat_r3_big.json'),('pruned','eta_xgb_global_pruned_r3_big.json')]:
        path=ROOT/'data/models'/name
        model=xgb.XGBRegressor(n_jobs=2);model.load_model(path);model.set_params(n_jobs=2)
        models[role]=model
        model_files[role]=dict(file=str(path.relative_to(ROOT)),sha256=fingerprint(path))
    route_dirs=sorted((args.root/'split=train').glob('route_code=*'))
    routes=[p.name.split('=',1)[1] for p in route_dirs]
    # Reconstructed current feature-store mapping, not proof of the original training mapping.
    mapping={}
    inputs=[]
    for split in ('train','test'):
        for directory in sorted((args.root/('split='+split)).glob('route_code=*')):
            path=directory/'part-00000.snappy.parquet'
            if not path.exists(): continue
            file=pq.ParquetFile(path)
            sample=file.read_row_group(0,columns=['route_id_idx']).slice(0,1).to_pylist() if file.metadata.num_rows else []
            route=directory.name.split('=',1)[1]
            index=int(sample[0]['route_id_idx']) if sample else None
            if route in mapping and index!=mapping[route]: raise ValueError('inconsistent route mapping')
            if index is not None: mapping[route]=index
            inputs.append(dict(split=split,route=route,path=str(path),sha256=fingerprint(path),rows=file.metadata.num_rows,route_index=index))
    if len(set(mapping.values()))!=len(mapping): raise ValueError('route index collision')
    manifest=dict(started_at=datetime.now(timezone.utc).isoformat(),models=model_files,
                  metadata_sha256=fingerprint(metadata_path),inputs=inputs,route_mapping=mapping,
                  interpretation='current frozen artifacts and labels; original training lineage not certified')
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    reports=[];all_actual=[];all_predictions={k:[] for k in ('baseline','full','full_calibrated','pruned')}
    violations={}
    for item in inputs:
        path=Path(item['path']); collected=[]
        writer=None
        try:
            for batch in pq.ParquetFile(path).iter_batches(batch_size=args.batch_size):
                frame=batch.to_pandas()
                for name,count in validate_batch(frame,item['route'],item['split'],item['route_index']).items():
                    violations[name]=violations.get(name,0)+count
                if item['split']!='test': continue
                predictions={role:predict_eta_with_residual_model(model,frame,model.get_booster().feature_names) for role,model in models.items()}
                predictions['full_calibrated']=apply_per_route_calibrator(frame,predictions['full'],calibrator)
                predictions['baseline']=frame.baseline_eta_p50_sec.to_numpy()
                for role,values in predictions.items():
                    if not np.isfinite(values).all(): raise ValueError('nonfinite '+role)
                out=frame[['dt','vehicle_id','device_epoch','direction_id','target_station_order','n_stations_ahead','actual_eta_sec']].copy()
                for role,values in predictions.items(): out[role]=values.astype('float32')
                out['route_code']=item['route']
                table=pa.Table.from_pandas(out,preserve_index=False)
                if writer is None: writer=pq.ParquetWriter(args.output/('predictions_'+item['route']+'.parquet'),table.schema)
                writer.write_table(table)
                collected.append(out)
                all_actual.append(out.actual_eta_sec.to_numpy(dtype='float32'))
                for role in all_predictions: all_predictions[role].append(out[role].to_numpy(dtype='float32'))
            if collected:
                frame=pd.concat(collected,ignore_index=True)
                report=dict(route=item['route'],rows=len(frame),days=sorted(frame.dt.unique()),vehicles=int(frame.vehicle_id.nunique()),
                            metrics={role:metrics(frame.actual_eta_sec,frame[role]) for role in all_predictions},
                            horizons={str(h):{role:metrics(g.actual_eta_sec,g[role]) for role in all_predictions}
                                      for h in (1,2,5,10,15) if len(g:=frame[frame.n_stations_ahead==h])})
                reports.append(report)
                print(json.dumps(dict(route=item['route'],n=len(frame),mae={k:round(v['mae_sec'],3) for k,v in report['metrics'].items()})),flush=True)
        finally:
            if writer: writer.close()
    actual=np.concatenate(all_actual)
    summary=dict(status='evaluated_not_accepted',rows=len(actual),validation_violations=violations,
                 overall={role:metrics(actual,np.concatenate(parts)) for role,parts in all_predictions.items()},
                 per_route=reports,elapsed_sec=round(time.monotonic()-started,3),
                 unresolved=['original training input identity','independent label audit','validation baseline leakage audit',
                             'historical test reuse','prospective live transfer and interval calibration'])
    (args.output/'report.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print('EVALUATION_FINISHED='+json.dumps({k:v for k,v in summary.items() if k!='per_route'}),flush=True)


if __name__=='__main__': main()
