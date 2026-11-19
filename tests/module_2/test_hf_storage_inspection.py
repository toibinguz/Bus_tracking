import json

from scripts.inspect_hf_storage_contract import describe


def test_describe_distinguishes_missing_naive_invalid_and_offset():
    rows = [{'device_update_time': value} for value in ('2026-11-01T01:00:00+07:00', '2026-11-01T01:00:00', 'bad')]
    rows.append({})
    report = describe('\n'.join(json.dumps(row) for row in rows).encode())
    assert report['rows'] == 4
    assert report['timestamps']['device_update_time'] == {'offset_present': 1, 'offset_missing': 1, 'invalid': 1, 'missing': 1}


def test_incident_capture_timestamp_is_not_bus_event_time():
    report = describe(b'{"timestamp":"2026-11-01T01:00:00Z","delay_seconds":null}\n')
    assert report['timestamps']['timestamp'] == {'offset_present': 1}
    assert report['timestamps']['device_update_time'] == {'missing': 1}
    assert report['samples'][0]['delay_seconds'] is None
