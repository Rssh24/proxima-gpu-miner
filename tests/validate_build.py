"""Explicit, bounded GPU validation against a local synthetic protocol server.

This tests only the selected GPU and driver. It does not certify other cards,
calibrate power modes, create a recipient wallet, or contact public mining nodes.
"""
import argparse
import ctypes as C
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from validation_common import child_path,load_json,sha256,upstream_hashes,verify_hash_map,write_json


def verify_build(source,package,protocol):
    manifest=load_json(package/'build-manifest.json')
    verify_hash_map(source,manifest.get('source_sha256'))
    verify_hash_map(package,manifest.get('artifact_sha256'))
    info=load_json(package/'tools/build-info.json')
    if set(info.get('artifacts',{}))!={'proxi.exe','oracle.exe','gpu-seeker.exe'}:
        raise RuntimeError('Required built binaries are missing from build-info')
    verify_hash_map(package/'tools',info['artifacts'])
    verify_hash_map(package/'miner',info.get('seeker_sources'))
    for name,digest in info['artifacts'].items():
        if manifest['artifact_sha256'].get('tools/'+name)!=digest:
            raise RuntimeError('Build-info and manifest artifact hashes disagree')
    for name,digest in info['seeker_sources'].items():
        if manifest['source_sha256'].get('miner/'+name)!=digest:
            raise RuntimeError('Build-info and manifest miner sources disagree')
    vectors='upstream/util/vrf/vrf_test.go'
    expected=manifest['source_sha256'].get(vectors)
    if not expected or sha256(package/vectors)!=expected:
        raise RuntimeError('Packaged official RFC vectors differ from pinned source')
    receipt=load_json(protocol.parent/'protocol-build.json')
    if receipt.get('compiled') is not True or receipt.get('executable_sha256')!=sha256(protocol):
        raise RuntimeError('Protocol executable lacks a matching compile receipt')
    if receipt.get('overlay_sha256')!=sha256(source/'tests/protocol/mine_seeker_binary_test.go'):
        raise RuntimeError('Protocol test overlay changed; recompile it')
    if receipt.get('upstream_sha256')!=upstream_hashes(source/'upstream'):
        raise RuntimeError('Pinned protocol source changed; recompile the protocol test')
    return manifest,info,receipt


def wait_for_gate():
    gate=os.environ.get('PROXIMA_VALIDATION_START_GATE')
    if not gate:raise RuntimeError('Proof worker must be launched by the validator')
    deadline=time.monotonic()+10
    while not Path(gate).is_file():
        if time.monotonic()>=deadline:raise RuntimeError('Validation containment gate timed out')
        time.sleep(.02)


def proof_worker(a):
    wait_for_gate()
    package=a.package_root.resolve();data=a.worker_data.resolve()
    os.environ['PROXIMA_MINER_DATA']=str(data)
    sys.path.insert(0,str(package/'miner'))
    from opencl_backend import OpenCL,enumerate_devices
    from device_config import recommended_device_key,select_device
    from device_profile import device_fingerprint,validate_profile
    from telemetry import Telemetry
    from oracle import Oracle
    from setup import correctness,choose_local,safe_temperatures
    from validate import rfc_vectors
    devices=enumerate_devices();key=recommended_device_key(devices) if a.device=='auto' else a.device
    device=select_device(devices,key);sensor=cl=oracle=None
    if len(rfc_vectors())!=3:raise RuntimeError('Expected exactly three pinned RFC proof vectors')
    try:
        sensor=Telemetry(key);metrics=sensor.read();hotspot=metrics.get('hotspot_c') is not None
        safe_temperatures(sensor,hotspot)
        cl=OpenCL(key);cl.build();local=choose_local(cl.metadata)
        checks=correctness(cl,sensor,hotspot,local)
        oracle=Oracle(seed=secrets.token_bytes(32));batch=1024
        cl.prepare(oracle.pubkey,oracle.scalar,secrets.token_bytes(37),batch)
        safe_temperatures(sensor,hotspot)
        _,seconds=cl.run(0,batch,local_size=local)
        if not math.isfinite(seconds) or seconds<=0 or seconds>.5:
            raise RuntimeError('GPU dispatch timing was invalid or too slow')
        # Local protocol only: power modes deliberately disabled, no fabricated
        # idle/reference watts and no 25-second recipient power calibration.
        kernel=sha256(package/'miner/vrf.cl')
        profile=dict(schema_version=1,device_key=key,device_name=device['name'],
            vendor=device['vendor'],driver=device['driver'],kernel_sha256=kernel,
            fingerprint=device_fingerprint(device,kernel),self_test=checks,
            sensor_capabilities={'core_temperature':True,'hotspot_temperature':hotspot,
                                 'board_power':False},power_available=False,power_profiles=None,
            modes={'maximum':{'enabled':True},'balanced':{'enabled':False,'reason':'Local validation only'},
                   'eco':{'enabled':False,'reason':'Local validation only'}},
            batch=batch,local=local,attempts_per_second=batch/seconds,
            validation_fixture=True)
        validate_profile(profile,devices,kernel)
        write_json(data/'device-profile.json',profile)
        write_json(data/'performance.json',{'mode':'maximum'})
        write_json(a.worker_output,{'passed':True,'device':device,'checks':checks,
            'local':local,'batch':batch,'brief_dispatch_seconds':seconds,
            'temperature_check_passed':True,'power_calibration_performed':False})
    finally:
        if oracle:oracle.close()
        if cl:cl.close()
        if sensor:sensor.close()


def run_contained(command,env,cwd,log_path,gate,timeout):
    """Keep the launched test and every child in a Windows kill-on-close job.

    Both workers wait for the gate before they launch a GPU or oracle child,
    eliminating the process-start/AssignProcessToJobObject race.
    """
    kernel=C.WinDLL('kernel32.dll',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[C.c_void_p,C.c_wchar_p];kernel.CreateJobObjectW.restype=C.c_void_p
    kernel.SetInformationJobObject.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_uint];kernel.SetInformationJobObject.restype=C.c_int
    kernel.AssignProcessToJobObject.argtypes=[C.c_void_p,C.c_void_p];kernel.AssignProcessToJobObject.restype=C.c_int
    kernel.CloseHandle.argtypes=[C.c_void_p];kernel.CloseHandle.restype=C.c_int
    job=kernel.CreateJobObjectW(None,None)
    if not job:raise C.WinError(C.get_last_error())
    info=C.create_string_buffer(144);C.c_uint32.from_buffer(info,16).value=0x2000
    proc=None
    try:
        if not kernel.SetInformationJobObject(job,9,info,144):raise C.WinError(C.get_last_error())
        with Path(log_path).open('w',encoding='utf-8') as log:
            proc=subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            if not kernel.AssignProcessToJobObject(job,int(proc._handle)):
                proc.kill();proc.wait();raise C.WinError(C.get_last_error())
            Path(gate).write_text('contained synthetic test',encoding='ascii')
            try:code=proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('Local validation exceeded its bounded timeout') from exc
        if code!=0:
            raise RuntimeError('Local validation worker failed (exit '+str(code)+'): '+Path(log_path).read_text(encoding='utf-8',errors='replace')[-2000:])
        return Path(log_path).read_text(encoding='utf-8',errors='replace')
    finally:
        kernel.CloseHandle(job) # stops any surviving child, including on timeout
        if proc and proc.poll() is None:proc.wait(timeout=10)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package-root',type=Path,required=True)
    p.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--device',default='auto')
    p.add_argument('--protocol-exe',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--proof-worker',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--worker-data',type=Path,help=argparse.SUPPRESS)
    p.add_argument('--worker-output',type=Path,help=argparse.SUPPRESS)
    a=p.parse_args()
    if os.name!='nt':raise RuntimeError('This validator targets Windows only')
    if a.proof_worker:
        proof_worker(a);return 0
    if not a.protocol_exe:p.error('--protocol-exe is required; compile it with Build-ProtocolTest.ps1')
    source=a.source_root.resolve();package=a.package_root.resolve();protocol=a.protocol_exe.resolve()
    manifest,info,receipt=verify_build(source,package,protocol)
    compatibility=package/'tools/compatibility-validation.json'
    report=dict(schema_version=1,validation_passed=False,gpu_validated=False,
                source_commit=info['source_commit'],miner_version=info['miner_version'],
                artifacts=info['artifacts'],seeker_sources=info['seeker_sources'],
                source_sha256=manifest['source_sha256'],artifact_sha256=manifest['artifact_sha256'],
                real_wallet_accessed=False,public_network_used=False)
    write_json(compatibility,report)
    scratch=(source/'build/gpu-validation-work').resolve();scratch.mkdir(parents=True,exist_ok=True)
    fixture=Path(tempfile.mkdtemp(prefix='synthetic-',dir=scratch)).resolve()
    if not fixture.is_relative_to(scratch) or fixture==scratch:raise RuntimeError('Unexpected validation fixture path')
    started=time.monotonic()
    try:
        data=fixture/'data';data.mkdir();(data/'logs').mkdir();temp=fixture/'temp';temp.mkdir()
        env=dict(os.environ,PROXIMA_MINER_DATA=str(data),PYTHONDONTWRITEBYTECODE='1',TEMP=str(temp),TMP=str(temp))
        # Do not inherit a real wallet secret into either synthetic worker.
        for key in ('PROXIMA_KEY_PASSPHRASE','NONCE_SEEKER_SEED'):env.pop(key,None)
        proof_gate=fixture/'proof.gate';env['PROXIMA_VALIDATION_START_GATE']=str(proof_gate)
        proof_output=fixture/'proof.json'
        print('Checking the selected GPU against official RFC and nonce carry/wrap proofs.',flush=True)
        command=[str(package/'tools/python/python.exe'),'-B',str(Path(__file__).resolve()),
                 '--proof-worker','--package-root',str(package),'--source-root',str(source),
                 '--device',a.device,'--worker-data',str(data),'--worker-output',str(proof_output)]
        run_contained(command,env,fixture,fixture/'proof.log',proof_gate,120)
        proof=load_json(proof_output)
        if proof.get('passed') is not True or proof.get('checks',{}).get('official_proof_checks',0)<18:
            raise RuntimeError('GPU proof comparison did not complete')
        protocol_gate=fixture/'protocol.gate';env['PROXIMA_PROTOCOL_START_GATE']=str(protocol_gate)
        env['NONCE_SEEKER_BIN']=str(package/'tools/gpu-seeker.exe')
        print('Checking four accepted improvements with local synthetic plain/encrypted wallets.',flush=True)
        output=run_contained([str(protocol),'-test.run','^TestNonceSeekerBinary$','-test.v',
                              '-test.count=1','-test.timeout=150s'],env,fixture,
                             fixture/'protocol.log',protocol_gate,170)
        if '--- PASS: TestNonceSeekerBinary' not in output or '--- SKIP:' in output:
            raise RuntimeError('Official protocol test did not execute and pass')
        totals=load_json(data/'logs/acceptance-totals.json')
        if totals.get('total_accepted')!=4 or totals.get('migrated_log_count')!=0 or sorted(totals.get('session_counts',{}).values())!=[2,2]:
            raise RuntimeError('Four local accepted improvements did not persist across both processes')
        after,after_info,after_receipt=verify_build(source,package,protocol)
        if (after,after_info,after_receipt)!=(manifest,info,receipt):
            raise RuntimeError('Build changed during validation; rebuild and retry')
        report.update(validation_passed=True,gpu_validated=True,
            scope='Selected GPU/driver only; local synthetic tests; no public-node rewards or power-mode calibration',
            device=proof['device'],proof_checks=proof['checks'],
            protocol={'passed':True,'test':'TestNonceSeekerBinary','accepted_improvements':4,
                      'plain_and_encrypted_synthetic_keys':True,'restart_persistence':True,
                      'executable_sha256':receipt['executable_sha256'],'overlay_sha256':receipt['overlay_sha256']},
            elapsed_seconds=round(time.monotonic()-started,3))
        write_json(compatibility,report)
        if a.output:write_json(a.output.resolve(),report)
        print('Selected GPU proofs and local protocol passed. Exact rebuilt artifacts are now validated.',flush=True)
        return 0
    except Exception as exc:
        report.update(error=str(exc),elapsed_seconds=round(time.monotonic()-started,3))
        write_json(compatibility,report)
        if a.output:write_json(a.output.resolve(),report)
        raise
    finally:
        target=fixture.resolve()
        if target==scratch or not target.is_relative_to(scratch):raise RuntimeError('Unsafe validation cleanup path')
        shutil.rmtree(target)


if __name__=='__main__':raise SystemExit(main())
