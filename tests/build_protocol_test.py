"""Compile the official local protocol test. This command never runs a GPU."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from validation_common import sha256,upstream_hashes,write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--go',type=Path,required=True)
    p.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--output-directory',type=Path)
    p.add_argument('--gomodcache',type=Path)
    a=p.parse_args();source=a.source_root.resolve();upstream=source/'upstream'
    output=(a.output_directory or source/'build/protocol').resolve()
    if output==upstream or output.is_relative_to(upstream):
        raise RuntimeError('Protocol build output must be outside pinned upstream source')
    overlay=source/'tests/protocol/mine_seeker_binary_test.go'
    target=upstream/'proxi/node_cmd/mine/mine_seeker_binary_test.go'
    if not overlay.is_file() or not target.is_file() or not (upstream/'go.mod').is_file():
        raise RuntimeError('Pinned upstream or protocol overlay is missing')
    output.mkdir(parents=True,exist_ok=True)
    cache=output/'gocache';temp=output/'temp';cache.mkdir(exist_ok=True);temp.mkdir(exist_ok=True)
    receipt=output/'protocol-build.json'
    # A failed recompilation cannot leave a success receipt for old output.
    write_json(receipt,{'schema_version':1,'compiled':False,'gpu_executed':False})
    overlay_file=output/'overlay.json'
    write_json(overlay_file,{'Replace':{str(target):str(overlay)}})
    before=upstream_hashes(upstream);overlay_sha=sha256(overlay)
    env=dict(os.environ,GOTOOLCHAIN='local',GOTELEMETRY='off',GOPROXY='off',GOSUMDB='off',
             CGO_ENABLED='0',GOCACHE=str(cache),GOTMPDIR=str(temp))
    if a.gomodcache:env['GOMODCACHE']=str(a.gomodcache.resolve())
    exe=output/'protocol-tests.exe'
    command=[str(a.go.resolve()),'test','-c','-trimpath','-buildvcs=false','-mod=readonly',
             '-overlay',str(overlay_file),'-o',str(exe),'./proxi/node_cmd/mine']
    subprocess.run(command,cwd=upstream,env=env,check=True)
    if upstream_hashes(upstream)!=before or sha256(overlay)!=overlay_sha:
        raise RuntimeError('Protocol source changed during compilation; rebuild')
    write_json(receipt,{'schema_version':1,'compiled':True,'gpu_executed':False,
                       'executable_sha256':sha256(exe),'overlay_sha256':overlay_sha,
                       'upstream_sha256':before,'package':'./proxi/node_cmd/mine',
                       'test':'TestNonceSeekerBinary'})
    print('Compiled protocol-tests.exe. No protocol or GPU test was executed.')


if __name__=='__main__':main()
