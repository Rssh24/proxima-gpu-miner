from paths import DATA_ROOT, ensure_data_dirs
"""Supervised official miner with a local GPU seeker, bound to a named ledger."""
import argparse,json,re,subprocess,urllib.request,urllib.parse,os,time,hashlib
import ctypes as C,struct
from pathlib import Path
from oracle import ROOT
from thermal_control import validate_temperatures
HOME='https://raw.githubusercontent.com/lunfardo314/lunfardo314.github.io/main/README.md'
def contain_children():
    kernel=C.WinDLL('kernel32.dll')
    kernel.CreateJobObjectW.argtypes=[C.c_void_p,C.c_void_p];kernel.CreateJobObjectW.restype=C.c_void_p
    kernel.SetInformationJobObject.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_uint];kernel.SetInformationJobObject.restype=C.c_int
    kernel.GetCurrentProcess.restype=C.c_void_p
    kernel.AssignProcessToJobObject.argtypes=[C.c_void_p,C.c_void_p];kernel.AssignProcessToJobObject.restype=C.c_int
    job=kernel.CreateJobObjectW(None,None);info=C.create_string_buffer(144);struct.pack_into('<I',info,16,0x2000)
    if not job or not kernel.SetInformationJobObject(job,9,info,144) or not kernel.AssignProcessToJobObject(job,kernel.GetCurrentProcess()):raise RuntimeError('Windows process containment failed')
    return job
def process_started_unix():
    kernel=C.WinDLL('kernel32.dll')
    kernel.GetCurrentProcess.restype=C.c_void_p
    kernel.GetProcessTimes.argtypes=[C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p]
    times=[C.c_ulonglong() for _ in range(4)]
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(),*[C.byref(t) for t in times]):raise RuntimeError('Cannot verify process start identity')
    return times[0].value/10000000-11644473600

def get(url):
    with urllib.request.urlopen(url,timeout=15) as r:return r.read().decode()
def build_info():
    info=json.loads((ROOT/'tools/build-info.json').read_text(encoding='utf-8-sig'))
    validation=json.loads((ROOT/'tools/compatibility-validation.json').read_text(encoding='utf-8-sig'))
    expected={'proxi.exe','oracle.exe','gpu-seeker.exe'}
    if set(info.get('artifacts',{}))!=expected or validation.get('validation_passed') is not True or validation.get('source_commit')!=info.get('source_commit') or validation.get('miner_version')!=info.get('miner_version') or validation.get('artifacts')!=info.get('artifacts'):
        raise RuntimeError('This build has not passed GPU and compatibility validation; run Validate-GPU.ps1')
    for name,digest in info['artifacts'].items():
        if hashlib.sha256((ROOT/'tools'/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Installed binary differs from the validated build; rebuild and validate')
    sources=info.get('seeker_sources',{})
    if not sources or validation.get('seeker_sources')!=sources:
        raise RuntimeError('GPU source validation record differs from the installed build')
    for name,digest in sources.items():
        path=ROOT/'miner'/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Installed GPU source differs from the validated build')
    return info
def gate(config):
    network=config.get('network','take1')
    if network not in ['take1','testnet4']:raise RuntimeError('Unsupported network identity')
    h=config.get('ledger_definitions_hash','').lower();genesis=config.get('genesis_time_unix',0)
    if network=='take1':
        text=get(HOME)
        if re.search(r'Network status:\s*\*\*stopped\*\*',text,re.I):raise RuntimeError('Official network is stopped; Take 1 genesis is not published')
        if not re.search(r'take\s*1',text,re.I):raise RuntimeError('Official home does not identify Take 1')
        if h not in text.lower() or str(genesis) not in text:raise RuntimeError('Set launch.json to the officially published Take 1 hash and genesis time')
    elif config.get('temporary_test_network') is not True:
        raise RuntimeError('testnet4 must be explicitly marked temporary and subject to reset')
    if not re.fullmatch('[0-9a-f]{64}',h) or not genesis:raise RuntimeError('Pinned ledger hash and genesis time are missing')
    node=config.get('node_url','');witnesses=config.get('witness_urls',[])
    if not witnesses or len(set([node]+witnesses))<2 or node in witnesses or len(set(witnesses))!=len(witnesses):raise RuntimeError('At least two distinct official node endpoints are required, including a witness')
    info=build_info()
    for endpoint in [node]+witnesses:
        u=urllib.parse.urlparse(endpoint)
        if u.scheme not in ['http','https'] or not u.hostname or u.username or u.password:raise RuntimeError('Invalid public node endpoint')
        base=endpoint.rstrip('/')+'/api/v1/ledger_constants'
        genesis_constants=json.loads(get(base+'?slot=0'))
        constants=json.loads(get(base))
        if genesis_constants.get('hash')!=h or genesis_constants.get('genesis_time_unix')!=genesis or constants.get('genesis_time_unix')!=genesis:raise RuntimeError('Node ledger identity differs from the pinned network')
        pattern=r'take\s*1' if network=='take1' else r'testnet\s*4'
        if not re.search(pattern,constants.get('description',''),re.I):raise RuntimeError('Node does not identify as '+network)
        if constants.get('miner_version')!=info['miner_version']:
            raise RuntimeError('Node requires another miner version; update proxi, rebuild and validate')
    if config.get('source_commit')!=info['source_commit']:raise RuntimeError('Profile and validated build source identity differ')
    seq=config.get('bootstrap_sequencer_id','')
    if seq and not re.fullmatch('[0-9a-fA-F]{48}',seq):raise RuntimeError('Official bootstrap sequencer chain ID is missing')
def render_profile(config,public):
    q=lambda s:json.dumps(str(s))
    witnesses='\n'.join('    - '+q(u) for u in config['witness_urls'])
    text=f'''# Official Take 1 miner places newly minted rewards into own delegations.
# Separate consolidation/transfers are not launched by this supervisor.
default_sequencer_id: {q(config.get('bootstrap_sequencer_id',''))}
wallet:
  key_file: {q(str(DATA_ROOT/'wallet/proxima.key'))}
  holder_id: {q(public['holder_id'])}
api:
  node_url: {q(config['node_url'])}
  node_urls:
{witnesses}
tag_along:
  fee: 1000000
  sequencer_id: random
consolidate:
  autodelegate: random
  target_delegations: 5
  target_delegation_prox: 10000
mine:
  seeker:
    listen: "127.0.0.1:18100"
    token: ""
    spawn: false
'''
    return text
def profile(config):
    public=json.loads((DATA_ROOT/'wallet/public.json').read_text())
    text=render_profile(config,public)
    (DATA_ROOT/'wallet/proxi.yaml').write_text(text,encoding='utf-8')
def mining_command(cpu_workers,count=0):
    return [str(ROOT/'tools/proxi.exe'),'node','mine','--workers',str(cpu_workers),'--count',str(count),'--stream','http://79.137.70.25:8001,http://51.254.47.76:8001']
def stop_processes(processes):
    for process in reversed(processes):
        if process.poll() is None:process.terminate()
    for process in processes:
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
def wait_for_processes(processes,max_seconds=0):
    deadline=time.monotonic()+max_seconds if max_seconds else None
    from telemetry import Telemetry
    telemetry=Telemetry()
    from device_profile import load_validated_profile
    device_profile=load_validated_profile()
    started=time.monotonic();last_check=0
    try:
        while all(p.poll() is None for p in processes):
            now=time.monotonic()
            if now-last_check>=2:
                metrics=telemetry.read();last_check=now
                # The seeker owns the timed95C soft cap. The independent supervisor
                # still stops both workers on invalid sensors or emergency heat.
                validate_temperatures(metrics.get('edge_c'),metrics.get('hotspot_c'),require_hotspot=device_profile.get('sensor_capabilities',{}).get('hotspot_temperature',False))
                status=DATA_ROOT/'logs/gpu-status.json'
                if now-started>60 and (not status.exists() or time.time()-status.stat().st_mtime>60):raise RuntimeError('GPU progress monitor stopped updating')
            if deadline is not None and time.monotonic()>=deadline:return 'configured time limit reached'
            time.sleep(.5)
        if processes[0].poll()==0:return 'official miner completed normally'
        raise RuntimeError('A mining process exited; both processes are being stopped. Review local logs')
    finally:telemetry.close()

def require_reward_consent(allowed):
    if not allowed:raise RuntimeError('The official Take 1 miner places newly minted rewards into delegations in the mining transaction; explicit AllowRewardDelegation consent is required before submitting transactions')
def main():
    ensure_data_dirs()
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--cpu-workers',type=int,default=0);p.add_argument('--network',choices=['take1','testnet4'],default='take1');p.add_argument('--allow-reward-delegation',action='store_true');p.add_argument('--count',type=int,default=0);p.add_argument('--max-seconds',type=float,default=0);a=p.parse_args()
    config_path=ROOT/('testnet4.json' if a.network=='testnet4' else 'launch.json')
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if config.get('network','take1')!=a.network:raise RuntimeError('Selected network differs from the configuration')
    if a.check_only:gate(config);print(a.network+' ledger identity and validated binary checks passed');return
    require_reward_consent(a.allow_reward_delegation)
    if a.cpu_workers!=0:raise RuntimeError('This GPU beta does not enable CPU mining')
    if a.count<0 or a.max_seconds<0:raise RuntimeError('Mining count and time limit must not be negative')
    job_handle=contain_children()
    import msvcrt
    lock=(DATA_ROOT/'logs/mining.lock').open('a+')
    lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:lock.close();raise RuntimeError('Another Take 1 mining supervisor is running')
    lock.seek(0);lock.truncate();lock.write(str(os.getpid()));lock.flush();processes=[];handles=[]
    (DATA_ROOT/'logs/supervisor.json').write_text(json.dumps({'pid':os.getpid(),'started_unix':time.time(),'process_started_unix':process_started_unix(),'network':a.network,'cpu_workers':a.cpu_workers}),encoding='utf-8')
    try:
        gate(config)
        from device_profile import load_validated_profile
        load_validated_profile()
        if not a.cpu_workers:
            subprocess.run([str(ROOT/'tools/python/python.exe'),str(ROOT/'miner/validate.py'),'--samples','16','--batch','1024'],check=True,cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
        profile(config)
        for name in ['proxi','gpu']:
            h=(DATA_ROOT/f'logs/live-{name}.log').open('a',encoding='utf-8');h.write('\n=== Take 1 mining session '+time.strftime('%Y-%m-%d %H:%M:%S')+' ===\n');h.flush();handles.append(h)
        env=dict(os.environ)
        from wallet import passphrase
        env['PROXIMA_KEY_PASSPHRASE']=passphrase()
        proxi=subprocess.Popen(mining_command(a.cpu_workers,a.count),cwd=DATA_ROOT/'wallet',env=env,stdout=handles[0],stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(proxi)
        if not a.cpu_workers:
            gpu=subprocess.Popen([str(ROOT/'tools/gpu-seeker.exe'),'--proxi','http://127.0.0.1:18100','--key-file',str(DATA_ROOT/'wallet/proxima.key')],cwd=ROOT,stdout=handles[1],stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);processes.append(gpu)
        print('Mining '+a.network+'. Rewards can be reset. Logs are in '+str(DATA_ROOT/'logs'),flush=True)
        print(wait_for_processes(processes,a.max_seconds),flush=True)
    finally:
        stop_processes(processes)
        for h in handles:h.close()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('Mining stopped')
    except Exception as e:print('Mining start blocked: '+str(e));raise SystemExit(1)
