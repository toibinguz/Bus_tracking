from pathlib import Path
import sys

import pytest

from modules.eta.evaluation.analyze_eta_live import crossing_events, metrics


def test_arrival_is_interpolated_inside_known_gps_bracket():
    events,intervals=crossing_events([(0,0),(5,50),(10,150)],{2:100})
    assert events==[dict(trip=0,station_order=2,valid=True,left=5,right=10,
                         estimated_arrival_epoch=7.5,uncertainty_sec=5)]
    assert intervals==[(0,0,10)]


def test_duplicates_jitter_and_new_trip_do_not_inflate_arrivals():
    events,_=crossing_events([(0,0),(10,200),(10,200),(15,195),(20,205),(30,0),(40,200)],{2:100})
    assert len(events)==2
    assert [x['trip'] for x in events]==[0,1]
    assert [x['estimated_arrival_epoch'] for x in events]==[5,35]


def test_long_gap_is_censored_instead_of_assigned_a_precise_arrival():
    events,_=crossing_events([(0,0),(60,200)],{2:100})
    assert len(events)==1 and not events[0]['valid']
    assert 'estimated_arrival_epoch' not in events[0]


def test_error_metrics_have_correct_sign_units_and_denominator():
    result=metrics([100,200],[120,160])
    assert result['bias_sec']==-10
    assert result['mae_sec']==30
    assert result['wape_pct']==20
    assert result['within_30sec_pct']==50
    assert result['p90_absolute_sec']==38
    assert metrics([5,200],[100,160])['mape_ge30_n']==1


def test_unknown_route_index_cannot_be_predicted_as_first_route():
    from modules.eta.serving.model_runtime import ModelRuntime
    class Forbidden:
        domains={'route_id_idx':[0,1]}
        def predict(self,*args,**kwargs): pytest.fail('unknown route reached model')
    runtime=ModelRuntime(residual_eta=Forbidden())
    assert runtime.predict_p50({'route_id_idx':-1}) is None
    assert runtime.predict_p50({'route_id_idx':999}) is None
