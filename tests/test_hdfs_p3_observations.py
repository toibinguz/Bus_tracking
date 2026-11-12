from scripts.hdfs_p3_validate import observations, arrival_functions
import pytest


def test_strict_split_and_unknown_date():
    with pytest.raises(ValueError, match='strictly later'):
        observations([], [], '2026-11-01', '2026-11-01')
    with pytest.raises(ValueError, match='outside declared split'):
        observations([{'device_update_time':'2026-10-01'}], [], '2026-10-27', '2026-11-01')


def test_no_train_does_not_fabricate_history():
    stations = [{'direction':'go','station_order':i,'station_id':i,'station_name':str(i),'cum_distance_m':i*200.0} for i in range(8)]
    pings = [{'direction':'go','vehicle_id':'v1','device_epoch':1000+i*40,'s_bus_m':i*200.0,'derived_speed_kmh':18.,'device_update_time':'2026-11-01 06:00:00'} for i in range(8)]
    train, heldout, counts, trips = observations(pings, stations, '2026-10-27', '2026-11-01', {'go':10000})
    assert train == {}
    assert len(heldout) == 5
    assert counts['test_trips'] == 1
    assert len(trips) == 1


def test_bracketing_guard_and_adaptive_long_segment():
    arrival, _ = arrival_functions()
    stations = [(0,0,'a',0.), (1,1,'b',1200.), (2,2,'c',2400.)]
    assert arrival([('',0.,0.,0.), ('',100.,1400.,0.)], stations)[1] == pytest.approx(1200/14)
    assert arrival([('',0.,0.,0.), ('',151.,1400.,0.)], stations) == {}


def test_heldout_changes_do_not_change_train_samples():
    stations = [{'direction':'go','station_order':i,'station_id':i,'station_name':str(i),'cum_distance_m':i*200.0} for i in range(8)]
    def make(day, step):
        return [{'direction':'go','vehicle_id':'v','device_epoch':1000+i*step,'s_bus_m':i*200.,'derived_speed_kmh':18.,'device_update_time':day+' 06:00:00'} for i in range(8)]
    training = make('2026-10-27',40)
    before = observations(training+make('2026-11-01',30), stations,'2026-10-27','2026-11-01',{'go':10000})
    after = observations(training+make('2026-11-01',60), stations,'2026-10-27','2026-11-01',{'go':10000})
    assert dict(before[0]) == dict(after[0])
    assert before[1] != after[1]
