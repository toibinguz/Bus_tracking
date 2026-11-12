"""U6 repeatable domain workflow: published Silver -> ETA Gold -> verified offline release."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history import eta_snapshot as pipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot')
    source.add_argument('--source-window',type=Path,help='pinned dataset/revision/paths/reference JSON; run HF stage/upload and Silver first')
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--dates',nargs='+',required=True)
    parser.add_argument('--routes',nargs='+')
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--pointer',type=Path,required=True)
    args=parser.parse_args()
    workspace=args.workspace.resolve()
    if ROOT not in workspace.parents:
        parser.error('workspace must be inside the repository for the read-only container mount')
    if args.source_window:
        window=json.loads(args.source_window.read_text(encoding='utf-8'))
        staging=workspace/'staging'
        stage=[sys.executable,str(ROOT/'scripts/hf_hdfs_ingest.py'),'stage','--stage-dir',str(staging),'--dataset',window['dataset'],'--revision',window['revision']]
        for path in window['paths']:
            stage+=['--path',path]
        for command in (stage,[sys.executable,str(ROOT/'scripts/hf_hdfs_ingest.py'),'upload','--stage-dir',str(staging)]):
            result=subprocess.run(command,capture_output=True,text=True,timeout=600)
            print(result.stdout,flush=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
        process=['docker','compose','-f',str(ROOT/'docker-compose.hdfs.yml'),'exec','-T','spark-master','/opt/spark/bin/spark-submit','--master','spark://spark-master:7077','--conf','spark.cores.max=2','--conf','spark.executor.cores=1','--conf','spark.executor.memory=512m','--conf','spark.executorEnv.PYTHONPATH=/workspace','/workspace/scripts/hdfs_build_history_snapshot.py','--reference',window['reference']]
        processed=subprocess.run(process,capture_output=True,text=True,timeout=600)
        if processed.returncode:
            raise RuntimeError(processed.stderr)
        lines=[line for line in processed.stdout.splitlines() if line.startswith('U3_RESULT=')]
        if len(lines)!=1:
            raise ValueError('missing Silver publication result')
        args.snapshot=json.loads(lines[0][len('U3_RESULT='):])['snapshot_id']
        print('ETA_SOURCE_SNAPSHOT='+args.snapshot,flush=True)
    cache,output=workspace/'cache',workspace/'output'
    if cache.exists():
        info=pipeline.verify_cache(cache)
        if info['snapshot_id']!=args.snapshot or info['dates']!=sorted(args.dates) or info['routes']!=(sorted(args.routes) if args.routes else None):
            raise ValueError('workspace belongs to a different history selection')
    else:
        info=pipeline.materialize(args.snapshot,cache,args.dates,args.routes)
    if output.exists():
        artifact=pipeline.verify_artifact(output)
        if artifact['cache_id']!=info['cache_id']:
            raise ValueError('output belongs to another cache')
        if artifact['pipeline_sha256']!=pipeline.digest(Path(pipeline.__file__).read_bytes()):
            raise ValueError('pipeline changed; choose a new workspace to rebuild')
        for relative,expected in artifact['code'].items():
            if pipeline.digest((ROOT/relative).read_bytes())!=expected:
                raise ValueError('domain code changed; choose a new workspace')
    else:
        artifact=pipeline.build(cache,output,args.workers)
    base=['docker','compose','-f',str(ROOT/'docker-compose.hdfs.yml'),'--profile','eta','run','--rm','--no-deps','eta-artifacts','python3','/workspace/scripts/eta_snapshot_pipeline.py']
    mounted_output='/workspace/'+output.relative_to(ROOT).as_posix()
    publish=subprocess.run(base+['publish','--output',mounted_output,'--transport','webhdfs'],capture_output=True,text=True,timeout=300)
    print(publish.stdout,flush=True)
    if publish.returncode:
        raise RuntimeError(publish.stderr)
    download=subprocess.run(base+['download','--artifact',artifact['artifact_id'],'--release-root','/releases','--transport','webhdfs'],capture_output=True,text=True,timeout=300)
    print(download.stdout,flush=True)
    if download.returncode:
        raise RuntimeError(download.stderr)
    release=ROOT/'runtime'/'eta_releases'/artifact['artifact_id']
    result=pipeline.activate(release,args.pointer)
    print('ETA_WORKFLOW_RESULT='+json.dumps(dict(result,baseline_result=artifact['baseline_result'],feature_result=artifact['feature_result'])),flush=True)


if __name__=='__main__':
    main()
