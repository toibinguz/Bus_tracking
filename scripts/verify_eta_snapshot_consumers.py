"""U4 parity against an offline repeat using existing domain algorithms and a real global model."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history import eta_snapshot as pipeline


def compare(first,second):
    with sqlite3.connect(Path(first).resolve().joinpath('baseline.db').as_uri()+'?mode=ro',uri=True) as a, sqlite3.connect(Path(second).resolve().joinpath('baseline.db').as_uri()+'?mode=ro',uri=True) as b:
        for table in ('agg_segment_travel_times','fact_route_tomtom_incidents'):
            left=pd.read_sql_query('SELECT * FROM '+table,a)
            right=pd.read_sql_query('SELECT * FROM '+table,b)
            columns=list(left.columns)
            pd.testing.assert_frame_equal(left.sort_values(columns).reset_index(drop=True),right.sort_values(columns).reset_index(drop=True),check_exact=True)
    files=sorted(path.relative_to(first) for path in Path(first).rglob('*.parquet'))
    assert files==sorted(path.relative_to(second) for path in Path(second).rglob('*.parquet'))
    split_rows={'train':0,'test':0}
    sample=[]
    for relative in files:
        left,right=pd.read_parquet(Path(first)/relative),pd.read_parquet(Path(second)/relative)
        columns=list(left.columns)
        pd.testing.assert_frame_equal(left.sort_values(columns).reset_index(drop=True),right.sort_values(columns).reset_index(drop=True),check_exact=True)
        if 'eta_feature_store' in relative.parts:
            info=pipeline.verify_artifact(first)
            split='train' if 'split=train' in relative.parts else 'test'
            split_rows[split]+=len(left)
            if split=='train':
                assert (left['dt']<=info['split']['train_end']).all()
            else:
                assert (left['dt']>=info['split']['test_start']).all()
            if len(left):
                sample.append(left.head(4))
    return split_rows,pd.concat(sample,ignore_index=True) if sample else pd.DataFrame()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--offline-output',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True)
    args=parser.parse_args()
    with patch('subprocess.run',side_effect=AssertionError('offline consumer used external process')), patch.object(pipeline,'transport',side_effect=AssertionError('offline used HDFS')):
        pipeline.build(args.cache,args.offline_output,workers=2)
    counts,sample=compare(args.output,args.offline_output)
    if sample.empty or not counts['train'] or not counts['test']:
        raise AssertionError('not enough real train/test feature rows for acceptance')
    import xgboost as xgb
    from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import predict_eta_with_residual_model
    model=xgb.XGBRegressor()
    model.load_model(args.model)
    columns=model.get_booster().feature_names
    predictions=predict_eta_with_residual_model(model,sample,columns)
    assert len(predictions)==len(sample) and np.isfinite(predictions).all()
    info=pipeline.verify_artifact(args.output)
    result=dict(artifact_id=info['artifact_id'],snapshot_id=info['snapshot_id'],exact_domain_table_and_parquet_parity=True,
                feature_rows=counts,offline_external_calls=0,global_model_loaded=True,model_sha256=pipeline.digest(args.model.read_bytes()),
                prediction_smoke_rows=len(predictions),prediction_finite=True,
                limitation='loader/prediction compatibility only; no retraining or accuracy claim; route index mapping not promoted to serving')
    print('ETA_CONSUMER_VERIFIED='+json.dumps(result),flush=True)


if __name__=='__main__':
    main()
