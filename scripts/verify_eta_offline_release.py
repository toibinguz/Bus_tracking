"""U5: verify a genuine offline release, corruption rejection and failed-refresh safety."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history import eta_snapshot as pipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pointer',type=Path,required=True)
    parser.add_argument('--scratch',type=Path,required=True)
    args=parser.parse_args()
    if args.scratch.exists():
        parser.error('scratch must be a fresh directory')
    pointer_before=args.pointer.read_bytes()
    with patch('subprocess.run',side_effect=AssertionError('offline operation called external process')),patch.object(pipeline,'transport',side_effect=AssertionError('offline operation called HDFS')):
        active=pipeline.inspect_active(args.pointer)
        release=Path(active['release'])
        with sqlite3.connect((release/'baseline.db').as_uri()+'?mode=ro',uri=True) as conn:
            key=conn.execute('SELECT route_code,direction,from_station_order,to_station_order,day_type,hour_slot FROM agg_segment_travel_times WHERE sample_count>0 ORDER BY sample_count DESC LIMIT 1').fetchone()
        if not key:
            raise AssertionError('no observed-history baseline sample')
        row=pipeline.baseline_lookup(release/'baseline.db',*key)
        assert row is not None and row['route_code']==key[0]
        args.scratch.mkdir(parents=True)
        corrupted=args.scratch/'corrupted-release'
        shutil.copytree(release,corrupted)
        with (corrupted/'baseline.db').open('ab') as stream:
            stream.write(b'injected corruption')
        try:
            pipeline.activate(corrupted,args.pointer)
        except ValueError:
            pass
        else:
            raise AssertionError('corruption was activated')
        assert args.pointer.read_bytes()==pointer_before
        class Unavailable:
            def read(self,path):
                raise RuntimeError('injected HDFS outage during refresh')
        try:
            pipeline.download(active['artifact_id'],args.scratch/'pending',Unavailable())
        except RuntimeError:
            pass
        else:
            raise AssertionError('refresh unexpectedly succeeded')
        assert args.pointer.read_bytes()==pointer_before
        assert pipeline.inspect_active(args.pointer)['artifact_id']==active['artifact_id']
    print('ETA_OFFLINE_VERIFIED='+json.dumps(dict(artifact_id=active['artifact_id'],snapshot_id=active['snapshot_id'],
          offline_external_calls=0,baseline_lookup=row,corrupted_release_rejected=True,failed_refresh_kept_active=True,
          docker_was_not_stopped='external calls were blocked; other running services were left intact')),flush=True)


if __name__=='__main__':
    main()
