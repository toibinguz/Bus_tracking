"""Known-geometry checks complement raw replay; these fixtures are not live evidence."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from route_projection_candidates import RouteHMM
from module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation.frenet import ShapeProjectionModel


def hairpin():
    return ShapeProjectionModel.build([(0,0,0,0),(1,0,.01,1113.2),(2,.0002,.01,1135.4),(3,.0002,0,2248.6)])


def test_sequence_can_correct_an_initial_nearest_branch_choice():
    shape=hairpin();h=RouteHMM(shape)
    first=h.update(100,.00012,.004,0)
    assert first.segment==2  # closest geometry alone initially favors the wrong leg
    second=h.update(105,.00012,.0042,1)
    assert second.segment==0
    assert h.best_path[0].segment==0
    assert first.segment==2  # the earlier as-of result does not gain future knowledge


def test_duplicate_and_late_inputs_do_not_create_new_evidence():
    h=RouteHMM(hairpin());old=h.update(100,0,.004,0);score=h.scores.copy()
    assert h.update(100,0,.009,1)==old
    assert h.update(99,0,.001,2)==old
    assert (h.scores==score).all()
    assert len(h.best_path)==1


def test_off_route_and_impossible_transitions_are_not_forced_into_a_match():
    h=RouteHMM(hairpin());h.update(100,0,.001,0)
    assert h.update(101,1,1,1) is None
    assert h.reason=='outside_corridor'
    assert h.update(102,0,.009,2) is None
    assert h.reason=='no_feasible_transition'


def test_gap_reinitializes_and_window_remains_bounded():
    h=RouteHMM(hairpin(),window=4)
    for i in range(12):h.update(100+i*5,0,.001+i*.0001,i)
    assert len(h.best_path)<=4
    h.update(600,0,.009,12)
    assert h.reason=='initialized' and h.resets==1
    assert len(h.best_path)==1


def test_real_terminal_wrap_starts_a_new_path():
    # A closed reference route; endpoint proximity alone is not inferred from a line's far ends.
    shape=ShapeProjectionModel.build([(0,0,0,0),(1,0,.01,1113.2),(2,.01,.01,2224.5),
                                       (3,.01,0,3337.7),(4,0,0,4449.)])
    h=RouteHMM(shape)
    for i,(lat,lng) in enumerate([(0,.001),(0,.008),(.008,.01),(.01,.002),(.002,0),(.0005,0)]):
        assert h.update(100+i*100,lat,lng,i) is not None
    match=h.update(610,0,.0005,6)
    assert match is not None and match.s<100
    assert h.reason=='terminal_reset'
    assert len(h.best_path)==1
