import json
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.model_runtime import ModelRuntime
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation import request_trace
from module_3_bus_eta_prediction.step_3_3_machine_learning_models.eta_model_trainer import predict_eta_with_residual_model, apply_per_route_calibrator


def test_model_runtime_matches_batch_and_calibration_with_category_subsets():
    frame=pd.DataFrame(dict(route_id_idx=np.array([0,1]*8,dtype='int32'),
                            direction_id=np.array([0,0,1,1]*4,dtype='int32'),
                            day_type=np.array([0,1,2,0]*4,dtype='int32'),
                            hour_slot=np.array([5,8,15,21]*4,dtype='int32'),
                            baseline_eta_p50_sec=np.arange(16,dtype='float32')+100,
                            n_stations_ahead=np.array([1,2,6,16]*4,dtype='int32')))
    features=list(frame)
    X=frame.copy()
    for col in ('route_id_idx','direction_id','day_type','hour_slot'): X[col]=X[col].astype('category')
    model=xgb.XGBRegressor(n_estimators=4,max_depth=2,n_jobs=1,enable_categorical=True,tree_method='hist')
    model.fit(X,np.arange(16,dtype='float32')*2-8)
    calibration={(1,1,3):(1.1,-5)}
    expected=apply_per_route_calibrator(frame,predict_eta_with_residual_model(model,frame,features),calibration)
    runtime=ModelRuntime(model=model,booster_feature_names=features,calibrator={'1_1_3':(1.1,-5)})
    actual=[runtime.predict_p50(row) for row in frame.to_dict('records')]
    assert actual==pytest.approx(expected,abs=1e-4)


def test_trace_io_failure_does_not_change_prediction(tmp_path,monkeypatch):
    blocker=tmp_path/'file-not-directory';blocker.write_text('occupied')
    monkeypatch.setenv('ETA_TRACE_DIR',str(blocker))
    class Constant:
        def predict(self,frame):return [10.]
    runtime=ModelRuntime(model=Constant(),booster_feature_names=['baseline_eta_p50_sec'])
    row=dict(route_id_idx=0,direction_id=0,n_stations_ahead=1,baseline_eta_p50_sec=100.)
    assert runtime.predict_p50(row)==110.


def test_request_ids_correlate_http_and_trace_and_reset_between_requests(tmp_path,monkeypatch):
    from module_3_bus_eta_prediction.step_3_5_web_demo import app as web
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
