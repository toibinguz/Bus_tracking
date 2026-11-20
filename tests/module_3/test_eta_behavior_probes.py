import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from probe_eta_behavior import transition, recommendation_check


def packet(vehicle,epoch,eta,distance):
    return dict(query_epoch=epoch,result=dict(vehicle_id=vehicle,eta_seconds=eta),
                features=dict(remaining_distance_m=distance))


def test_remaining_eta_decreases_but_arrival_can_move_later():
    result=transition(packet(1,0,100,500),packet(1,60,80,500))
    assert result['eta_change_sec']==-20
    assert result['arrival_revision_sec']==40
    assert result['distance_advance_m']==0


def test_next_bus_must_not_be_reported_as_same_bus_eta_jump():
    with pytest.raises(ValueError,match='different vehicles'):
        transition(packet(1,0,5,20),packet(2,5,600,2000))


def test_recommendation_inside_bracket_is_not_proven_late():
    result=recommendation_check(100,10,108,112)
    assert result['later_than_earliest_gps_crossing']
    assert not result['later_than_latest_gps_crossing']
    assert result['lateness_beyond_right_sec']==0


def test_recommendation_after_entire_bracket_is_flagged():
    result=recommendation_check(100,15,108,112)
    assert result['later_than_latest_gps_crossing']
    assert result['lateness_beyond_right_sec']==3
