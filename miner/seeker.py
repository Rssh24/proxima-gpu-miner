from paths import DATA_ROOT, ensure_data_dirs
"""Loopback-only Proxima external GPU nonce seeker. Never transmits private keys."""
import argparse,json,time,secrets,threading,urllib.request,urllib.error,urllib.parse,getpass,os
from pathlib import Path
from opencl_backend import OpenCL
from oracle import Oracle,ROOT
from telemetry import Telemetry
from gpu_filter import candidate_indices
from power_control import PowerController, PowerSampler, load_mode, dispatch_deadline
from thermal_control import ThermalGuard
from status_io import write_status, append_diagnostic
from acceptance_totals import AcceptanceTotals
import uuid
MASK=(1<<64)-1
def trailing(beta):
    n=int.from_bytes(beta,'big');return 512 if n==0 else (n&-n).bit_length()-1
def beat_bytes(value):
    if value is None or value=='':return None
    if not isinstance(value,str):raise ValueError('invalid beat bound')
    bound=bytes.fromhex(value)
    if len(bound)!=64:raise ValueError('invalid beat bound')
    return bound
def tighten_beat(job,*bounds):
    # Callers hold the shared-state lock. Missing/older polls must never undo
    # a stronger result response or a locally verified candidate.
    current=beat_bytes(job.get('beat'))
    for bound in bounds:
        if bound is not None and (current is None or bound<current):current=bound
    if current is not None:job['beat']=current.hex()
def unlock_passphrase(key_file):
    meta=json.loads(key_file.read_text(encoding='utf-8'))
    if not meta.get('crypto'):return ''
    named=Path.cwd()/meta.get('holder_id','__absent__')
    if named.is_file():return named.read_text(encoding='utf-8').strip()
    if os.environ.get('PROXIMA_KEY_PASSPHRASE'):return os.environ['PROXIMA_KEY_PASSPHRASE']
    local=DATA_ROOT/'wallet/unlock.dpapi'
    if key_file.resolve()==(DATA_ROOT/'wallet/proxima.key').resolve() and local.exists():
        from wallet import unprotect
        return unprotect(local.read_bytes()).decode()
    return getpass.getpass('Wallet passphrase: ')
def main():
    p=argparse.ArgumentParser();p.add_argument('--proxi',default='http://127.0.0.1:18100');p.add_argument('--token',default='');p.add_argument('--key-file',default='proxima.key');p.add_argument('--name',default='opencl-beta');p.add_argument('--threads',type=int,default=0,help='compatibility argument; GPU performs the search');p.add_argument('--mode',choices=['maximum','balanced','eco']);p.add_argument('--batch',type=int);p.add_argument('--local',type=int);p.add_argument('--max-seconds',type=float,default=0);p.add_argument('--max-hotspot',type=int,default=95,help='hotspot trigger for 95 percent average-power cap after 60 continuous seconds; emergency stop remains 105 C');p.add_argument('--max-edge',type=int,default=80);a=p.parse_args()
    url=urllib.parse.urlparse(a.proxi)
    if url.scheme!='http' or url.hostname not in ['127.0.0.1','localhost','::1']:raise RuntimeError('Seeker requires a local loopback HTTP server')
    if not 1<=a.max_hotspot<=95 or not 1<=a.max_edge<=80:raise RuntimeError('Temperature trigger and edge cutoff cannot be raised above defaults')
    from device_profile import load_validated_profile
    ensure_data_dirs()
    settings=load_validated_profile()
    power=PowerController(settings,load_mode(DATA_ROOT/'performance.json',a.mode))
    thermal=ThermalGuard(trigger_c=a.max_hotspot,edge_limit_c=a.max_edge,require_hotspot=settings.get('sensor_capabilities',{}).get('hotspot_temperature',False))
    batch=a.batch or power.batch;local=a.local or power.local
    if power.mode!='maximum' and (batch!=power.batch or local!=power.local):raise RuntimeError('Power modes require their validated GPU dispatch configuration')
    if batch<64 or batch>131072 or local not in [1,2,4,8,16,32,64,128,256] or batch%local:raise RuntimeError('Invalid GPU batch configuration')
    key=Path(a.key_file).resolve()
    if key.is_file():o=Oracle(key_file=key,passphrase=unlock_passphrase(key))
    else:
        seed=os.environ.get('NONCE_SEEKER_SEED','')
        if len(seed)!=64:raise RuntimeError('Local wallet key file missing')
        o=Oracle(seed=bytes.fromhex(seed))
    cl=OpenCL();cl.build();tel=Telemetry();stop=threading.Event();lock=threading.Lock()
    state={'job':{'id':0},'deadline':0,'attempts':0,'failure':None,'accepted':0,'stale':0,'stale_id':None}
    totals=AcceptanceTotals(DATA_ROOT);session_id=str(uuid.uuid4());totals.observe(session_id,0)
    print('Local cumulative accepted solutions: '+str(totals.snapshot()['total_accepted'])+' (not a token balance)',flush=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path,data=None,timeout=12):
        headers={'Content-Type':'application/json'}
        if a.token:headers['Authorization']='Bearer '+a.token
        req=urllib.request.Request(a.proxi.rstrip('/')+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        try:
            with opener.open(req,timeout=timeout) as r:return r.status,json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code,json.loads(e.read() or b'{}')
    def poll():
        after=0;backoff=.5
        while not stop.is_set():
            try:
                status,job=request('/seeker/job?after='+str(after)+'&wait=100',timeout=3)
                if status==401:raise ValueError('authentication failed')
                if status!=200:raise OSError('job server HTTP '+str(status))
                if job.get('id'):
                    if job.get('pubkey')!=o.pubkey.hex():raise ValueError('job public key differs from local wallet')
                    prefix=bytes.fromhex(job['alpha_prefix']);k=int(job['k']);ttl=int(job['ttl_ms'])
                    if len(prefix)!=37 or not 0<=k<=512 or not 0<=ttl<=600000:raise ValueError('invalid job fields')
                    incoming_beat=beat_bytes(job.get('beat'))
                with lock:
                    if job.get('id') and job['id']==state['stale_id']:
                        state['job']={'id':0};state['deadline']=0
                    else:
                        if job.get('id') and state['job'].get('id')==job['id']:
                            previous=state['job']
                            if any(job.get(field)!=previous.get(field) for field in ('pubkey','alpha_prefix','k')):
                                raise ValueError('job fields changed without a new id')
                            tighten_beat(job,beat_bytes(previous.get('beat')),incoming_beat)
                        state['job']=job
                        state['deadline']=time.monotonic()+job.get('ttl_ms',0)/1000
                        if job.get('id'):state['stale_id']=None
                after=job.get('id',0);backoff=.5
                if not after:stop.wait(.2)
            except ValueError as e:
                with lock:state['failure']=str(e)
                stop.set()
            except Exception:
                # Keep the existing work/bound until its deadline on a
                # transient connection error, as the reference seeker does.
                stop.wait(backoff);backoff=min(backoff*2,5)
    def report():
        while not stop.wait(1):
            with lock:n=state['attempts'];state['attempts']=0;jid=state['job'].get('id',0)
            if not n:continue
            try:
                status,_=request('/seeker/report',{'id':jid,'attempts':n,'seeker':a.name},3)
                if status!=200:
                    with lock:state['attempts']+=n
            except Exception:
                # An ambiguous response cannot be replayed without risking double counting.
                print('Attempt report connection error; rate may be undercounted',flush=True)
    threads=[threading.Thread(target=poll,daemon=True),threading.Thread(target=report,daemon=True)]
    for t in threads:t.start()
    print('GPU seeker ready: '+cl.name+f'; batch={batch}, local={local}; mode={power.mode}',flush=True)
    started=time.monotonic();current=None;nonce=0;last_telemetry=0;last_display=started;count=0;total_attempts=0;jobs_received=0
    # Public session diagnostics (seeker_diagnostics_v1).
    eligible_attempts=0;discarded_attempts=0;eligible_attempts_by_k={}
    k_candidates=0;beat_filtered_candidates=0;result_post_attempts=0;results_not_improved=0
    next_dispatch=0;last_power_warning=None;status_write_ok=True
    power_sampler=PowerSampler(stop);power_sampler.start()
    try:
        while not stop.is_set():
            now=time.monotonic()
            if a.max_seconds and now-started>=a.max_seconds:break
            if now-last_telemetry>=1:
                metrics=tel.read();last_telemetry=now
                was_thermal_limited=thermal.limited
                thermal_snapshot=thermal.update(now,metrics.get('edge_c'),metrics.get('hotspot_c'))
                if thermal.limited:
                    power.apply_thermal_limit(thermal_snapshot['thermal_power_fraction'])
                    if not was_thermal_limited:
                        print('Temperature threshold sustained for 60 seconds; session average board-power cap is now '+str(round(power.target,1))+' W',flush=True)
                power_sample=power_sampler.read_window(1.0)
                power.update(now,power_sample['average_w'] if power_sample['healthy'] else None,total_attempts)
                if not power.dispatch_allowed and power.status!=last_power_warning:
                    print('GPU dispatch paused: '+power.status,flush=True);last_power_warning=power.status
                elif power.dispatch_allowed:last_power_warning=None
                with lock: accepted=state['accepted'];stale=state['stale']
                cumulative=totals.observe(session_id,accepted)
                snapshot=dict(metrics,total_attempts=total_attempts,jobs_received=jobs_received,solutions_accepted=accepted,stale_results=stale,elapsed_seconds=now-started,
                    eligible_attempts=eligible_attempts,discarded_attempts=discarded_attempts,
                    eligible_attempts_by_k=dict(eligible_attempts_by_k),k_candidates=k_candidates,
                    beat_filtered_candidates=beat_filtered_candidates,result_post_attempts=result_post_attempts,
                    results_not_improved=results_not_improved,
                    expected_k_hits=sum(n/(1<<k) for k,n in eligible_attempts_by_k.items()))
                snapshot.update(power.snapshot())
                snapshot.update(thermal_snapshot)
                snapshot.update(cumulative_solutions_accepted=cumulative,cumulative_totals_persisted=totals.persisted)
                status_file=DATA_ROOT/'logs/gpu-status.json'
                published=write_status(status_file,snapshot,stop)
                if not published and status_write_ok:
                    print('Status file temporarily locked; mining continues while status publication retries',flush=True)
                elif published and not status_write_ok:
                    print('Status file publication recovered',flush=True)
                status_write_ok=published
            if not power.dispatch_allowed:
                stop.wait(.02);continue
            if power.rate and now<next_dispatch:
                stop.wait(min(.02,next_dispatch-now));continue
            with lock:job=dict(state['job']);deadline=state['deadline']
            if not job.get('id') or now>=deadline:stop.wait(.02);continue
            if current!=job['id']:
                cl.prepare(o.pubkey,o.scalar,bytes.fromhex(job['alpha_prefix']),batch);current=job['id'];nonce=secrets.randbits(64);jobs_received+=1
                print(f'GPU job received: slot={job["slot"]}, K={job["k"]}, ttl_ms={job["ttl_ms"]}, improvement={bool(job.get("beat"))}',flush=True)
            dispatch_started=time.monotonic()
            data,seconds=cl.run(nonce,batch,local_size=local);count+=batch;total_attempts+=batch
            next_dispatch=dispatch_deadline(dispatch_started,batch,power.rate)
            with lock:state['attempts']+=batch;live=state['job'].get('id')==job['id'] and time.monotonic()<state['deadline']
            if not live:discarded_attempts+=batch
            if live:
                with lock:
                    # The job may have tightened while the GPU batch ran.
                    live=state['job'].get('id')==job['id'] and time.monotonic()<state['deadline']
                    beat=beat_bytes(state['job'].get('beat')) if live else None
                if not live:
                    discarded_attempts+=batch
                    nonce=(nonce+batch)&MASK
                    continue
                eligible_attempts+=batch
                eligible_attempts_by_k[job['k']]=eligible_attempts_by_k.get(job['k'],0)+batch
                best=None;best_i=0
                for i in candidate_indices(data,job['k']):
                    k_candidates+=1
                    beta=data[i*64:(i+1)*64]
                    if beat is not None and beta>=beat:beat_filtered_candidates+=1
                    if (beat is None or beta<beat) and (best is None or beta<best):best=beta;best_i=i
                if best is not None:
                    nb=((nonce+best_i)&MASK).to_bytes(8,'little')
                    # Independent official prover and full proof check on every candidate.
                    if best!=o.evaluate(bytes.fromhex(job['alpha_prefix'])+nb):raise RuntimeError('GPU candidate differs from official VRF')
                    with lock:
                        live=state['job'].get('id')==job['id'] and time.monotonic()<state['deadline']
                        bound=beat_bytes(state['job'].get('beat')) if live else None
                        submit=live and (bound is None or best<bound)
                        if live and bound is not None and best>=bound:beat_filtered_candidates+=1
                        if submit:
                            n=state['attempts'];state['attempts']=0
                    if not submit:
                        nonce=(nonce+batch)&MASK
                        continue
                    try:
                        result_post_attempts+=1
                        status,res=request('/seeker/result',{'id':job['id'],'nonce':nb.hex(),'beta':best.hex(),'attempts':n,'seeker':a.name},3)
                        if status==200:
                            if type(res.get('accepted')) is not bool:raise ValueError('invalid result verdict')
                            response_beat=beat_bytes(res.get('beat'))
                            with lock:
                                # Only acknowledged candidates lower our bound:
                                # a lost POST must not hide valid improvements.
                                if state['job'].get('id')==job['id']:tighten_beat(state['job'],best,response_beat)
                                if res['accepted']:state['accepted']+=1
                                else:results_not_improved+=1
                            if res['accepted']:
                                totals.observe(session_id,state['accepted'])
                                print('Verified GPU solution accepted; continuing same job',flush=True)
                        elif status==409:
                            with lock:
                                state['stale']+=1
                                if state['job'].get('id')==job['id']:
                                    state['stale_id']=job['id'];state['job']={'id':0};state['deadline']=0
                        elif status==422:raise ValueError('proxi rejected the GPU solution')
                        else:raise ValueError('result HTTP '+str(status))
                    except ValueError:raise
                    except Exception:print('Result connection error; continuing until the job deadline',flush=True)
            totals.observe(session_id,state['accepted'])
            nonce=(nonce+batch)&MASK
            now=time.monotonic()
            if now-last_display>=10:
                print(f'GPU {count/(now-last_display):.0f} attempts/s; edge {metrics["edge_c"]} C; hotspot {metrics["hotspot_c"]} C; busy {metrics.get("gpu_busy_percent")}%',flush=True)
                if not append_diagnostic(DATA_ROOT/'logs/telemetry.jsonl',snapshot):
                    print('Optional telemetry history temporarily locked; sample skipped',flush=True)
                last_display=now;count=0
        if state['failure']:raise RuntimeError(state['failure'])
    finally:
        stop.set()
        for t in threads:t.join(4)
        if not power_sampler.join(2):print('Power sampler shutdown is still pending',flush=True)
        tel.close();cl.close();o.close()
        totals.close()
if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:pass
    except Exception as e:
        # Exception messages are controlled above and must not contain key material.
        print('GPU seeker stopped: '+str(e),flush=True);raise SystemExit(1)
