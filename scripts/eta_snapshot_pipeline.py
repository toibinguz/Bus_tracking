"""Explicit U4/U5 commands for observed HDFS history, domain Gold and offline releases."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history import eta_snapshot as pipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    materialize=commands.add_parser('materialize')
    materialize.add_argument('--snapshot',required=True)
    materialize.add_argument('--cache',type=Path,required=True)
    materialize.add_argument('--dates',nargs='+',required=True)
    materialize.add_argument('--routes',nargs='+')
    build=commands.add_parser('build')
    build.add_argument('--cache',type=Path,required=True)
    build.add_argument('--output',type=Path,required=True)
    build.add_argument('--workers',type=int,default=2)
    publish=commands.add_parser('publish')
    publish.add_argument('--output',type=Path,required=True)
    publish.add_argument('--transport',choices=['docker','webhdfs'],default='docker')
    download=commands.add_parser('download')
    download.add_argument('--artifact',required=True)
    download.add_argument('--release-root',type=Path,required=True)
    download.add_argument('--transport',choices=['docker','webhdfs'],default='docker')
    activate=commands.add_parser('activate')
    activate.add_argument('--release',type=Path,required=True)
    activate.add_argument('--pointer',type=Path,required=True)
    inspect=commands.add_parser('inspect')
    inspect.add_argument('--pointer',type=Path,required=True)
    lookup=commands.add_parser('baseline')
    lookup.add_argument('--source',choices=['local','release'],required=True)
    lookup.add_argument('--pointer',type=Path)
    lookup.add_argument('--database',type=Path,default=Path('data/hanoi_bus_system.db'))
    lookup.add_argument('--route',required=True)
    lookup.add_argument('--direction',choices=['go','re'],required=True)
    lookup.add_argument('--from-order',type=int,required=True)
    lookup.add_argument('--to-order',type=int,required=True)
    lookup.add_argument('--day-type',type=int,choices=[0,1,2],required=True)
    lookup.add_argument('--hour-slot',type=int,choices=range(5,22),required=True)
    args=parser.parse_args()
    store=None
    if getattr(args,'transport',None)=='webhdfs':
        from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.artifact_transport import PrivateWebHdfs
        store=PrivateWebHdfs()
    if args.command=='materialize':
        result=pipeline.materialize(args.snapshot,args.cache,args.dates,args.routes)
    elif args.command=='build':
        result=pipeline.build(args.cache,args.output,args.workers)
    elif args.command=='publish':
        result=pipeline.publish(args.output,store)
    elif args.command=='download':
        result=dict(release=str(pipeline.download(args.artifact,args.release_root,store)))
    elif args.command=='activate':
        result=pipeline.activate(args.release,args.pointer)
    elif args.command=='inspect':
        result=pipeline.inspect_active(args.pointer)
    else:
        identity={}
        database=args.database
        if args.source=='release':
            if not args.pointer:
                parser.error('release source requires --pointer')
            identity=pipeline.inspect_active(args.pointer)
            database=Path(identity['release'])/'baseline.db'
        result=dict(source=args.source,identity=identity,row=pipeline.baseline_lookup(database,args.route,args.direction,args.from_order,args.to_order,args.day_type,args.hour_slot))
    print('ETA_PIPELINE_RESULT='+json.dumps(result),flush=True)


if __name__=='__main__':
    main()
