"""Explicit first-run GPU check and separate recipient-wallet setup."""
import argparse, hashlib, json, math, msvcrt, os, secrets, threading, time
from paths import APP_ROOT, DATA_ROOT, ensure_data_dirs
from status_io import write_status as write_json_snapshot
from opencl_backend import OpenCL, enumerate_devices
from device_config import select_device, recommended_device_key
from telemetry import Telemetry
from oracle import Oracle
from thermal_control import validate_temperatures
from power_control import PowerSampler

def save(path, data):
    if not write_json_snapshot(path, data):
        raise RuntimeError('A settings file is busy. Close other beta windows and try again.')

def progress(message, state='running', **fields):
    save(DATA_ROOT/'setup-status.json', dict(state=state, message=message, **fields))
    print(message, flush=True)

def safe_temperatures(sensor, require_hotspot):
    metrics=sensor.read()
    validate_temperatures(metrics.get('edge_c'), metrics.get('hotspot_c'), require_hotspot=require_hotspot)
    if metrics['edge_c'] >= 75 or (metrics.get('hotspot_c') is not None and metrics['hotspot_c'] >= 95):
        raise RuntimeError('GPU is too warm for calibration. Let it cool down and run setup again.')
    return metrics

def choose_local(metadata):
    limit=min(metadata['max_work_group'], metadata['kernel_max_work_group'], metadata['max_work_item_size_0'])
    return next(v for v in (32,16,8,4,2,1) if v <= limit)

def correctness(cl, sensor, require_hotspot, local):
    from validate import rfc_vectors
    count=0
    for v in rfc_vectors():
        safe_temperatures(sensor, require_hotspot)
        o=Oracle(seed=bytes.fromhex(v['sk']))
        try:
            alpha=bytes.fromhex(v['alpha'])
            cl.prepare(o.pubkey, o.scalar, alpha, 1)
            data,_=cl.run(0,1,False,local_size=1)
            if data.hex()!=v['beta'] or data!=o.evaluate(alpha):
                raise RuntimeError('GPU correctness check failed. Mining is disabled on this configuration.')
            count+=1
        finally:o.close()
    for start in (0,(1<<32)-128,(1<<64)-128):
        safe_temperatures(sensor, require_hotspot)
        o=Oracle(seed=secrets.token_bytes(32));prefix=secrets.token_bytes(37)
        try:
            cl.prepare(o.pubkey,o.scalar,prefix,1024)
            data,_=cl.run(start,1024,local_size=local)
            indices={0,1,127,128,1023}
            indices.update(secrets.randbelow(1024) for _ in range(32))
            for i in indices:
                alpha=prefix+((start+i)&((1<<64)-1)).to_bytes(8,'little')
                if data[i*64:(i+1)*64]!=o.evaluate(alpha):
                    raise RuntimeError('GPU proof comparison failed. Mining is disabled on this configuration.')
                count+=1
        finally:o.close()
    return {'passed':True,'official_proof_checks':count,'rfc_vectors':3,'nonce_carry_and_wrap':True}

def calibrate(cl, sensor, device_key, require_hotspot, local, power_available):
    stop=threading.Event();sampler=None;idle_samples=[];load_samples=[]
    if power_available:
        sampler=PowerSampler(stop,telemetry_factory=lambda:Telemetry(device_key));sampler.start()
    o=Oracle(seed=secrets.token_bytes(32));prefix=secrets.token_bytes(37)
    try:
        progress('Measuring idle power. Keep other GPU applications closed.')
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            safe_temperatures(sensor,require_hotspot)
            time.sleep(.2)
            if sampler:
                r=sampler.read_window(1)
                if r['healthy']:idle_samples.append(r['average_w'])
        progress('Checking basic GPU speed and safe batch size. This takes about 25 seconds.')
        batch=1024;cl.prepare(o.pubkey,o.scalar,prefix,batch);nonce=0
        while True:
            safe_temperatures(sensor,require_hotspot)
            t=time.perf_counter();cl.run(nonce,batch,local_size=local);duration=time.perf_counter()-t
            if duration>.5:raise RuntimeError('A GPU dispatch is too slow for this beta. Try another GPU or driver.')
            if batch>=131072 or duration>=.045:break
            batch*=2;cl.prepare(o.pubkey,o.scalar,prefix,batch)
        # Keep each dispatch short enough for UI responsiveness and thermal checks.
        if duration>.15 and batch>1024:
            batch//=2;cl.prepare(o.pubkey,o.scalar,prefix,batch)
        started=time.monotonic();measured_at=started+5;end=started+22
        measured_attempts=0;max_seconds=0;next_read=started
        while time.monotonic()<end:
            t=time.monotonic()
            if t>=next_read:
                safe_temperatures(sensor,require_hotspot);next_read=t+.3
                if sampler and t>=measured_at:
                    r=sampler.read_window(1)
                    if r['healthy']:load_samples.append(r['average_w'])
            cl.run(nonce,batch,local_size=local);now=time.monotonic()
            max_seconds=max(max_seconds,now-t)
            if now-t>.5:raise RuntimeError('GPU dispatch stalled during calibration. Setup has stopped.')
            nonce=(nonce+batch)&((1<<64)-1)
            if t>=measured_at:measured_attempts+=batch
        rate=measured_attempts/(time.monotonic()-measured_at)
        result={'batch':batch,'local':local,'attempts_per_second':rate,'max_batch_seconds':max_seconds}
        modes={'maximum':{'enabled':True},'balanced':{'enabled':False,'reason':'Board-power telemetry is unavailable.'},'eco':{'enabled':False,'reason':'Board-power telemetry is unavailable.'}}
        if power_available:
            if len(idle_samples)<8 or len(load_samples)<20:
                raise RuntimeError('Board-power readings were incomplete. Close other GPU tools and retry setup.')
            idle=sum(idle_samples)/len(idle_samples);reference=sum(load_samples)/len(load_samples)
            if not math.isfinite(reference) or reference<=idle+5:
                raise RuntimeError('GPU was already busy or power calibration was inconclusive. Close other GPU applications and retry setup.')
            profiles={'reference_board_power_w':reference,'idle_board_power_w':idle}
            for name,fraction in (('balanced',.5),('eco',.25)):
                target=reference*fraction;enabled=target>idle+1
                modes[name]={'enabled':enabled,'reason':'' if enabled else 'Target power is below this GPU idle power.'}
                profiles[name]={'target_w':target,'initial_rate':max(1,rate*max(.001,(target-idle)/(reference-idle))*.9),'batch':min(batch,16384),'local':local}
            result.update(power_profiles=profiles,reference_max_board_w=reference,idle_board_w=idle)
        else:result['power_profiles']=None
        result['modes']=modes
        return result
    finally:
        stop.set()
        if sampler:sampler.join()
        o.close()

def setup(device_key=None):
    from run_mining import contain_children,build_info
    job_handle=contain_children()
    ensure_data_dirs()
    lock=(DATA_ROOT/'logs/mining.lock').open('a+')
    lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:lock.close();raise RuntimeError('Stop beta mining or another setup session before running setup.')
    cl=sensor=None
    try:
        progress('Checking package integrity and the selected GPU.')
        build_info()
        devices=enumerate_devices()
        if device_key in (None, 'auto'):
            device_key=recommended_device_key(devices)
        device=select_device(devices,device_key)
        if device.get('identity_error'):raise RuntimeError(device['identity_error'])
        sensor=Telemetry(device_key);metrics=sensor.read()
        require_hotspot=metrics.get('hotspot_c') is not None
        safe_temperatures(sensor,require_hotspot)
        power=metrics.get('board_power_w')
        power_available=type(power) in (int,float) and math.isfinite(power) and power>0
        caps={'core_temperature':True,'hotspot_temperature':require_hotspot,'board_power':power_available,'memory_temperature':metrics.get('memory_c') is not None,'gpu_busy':metrics.get('gpu_busy_percent') is not None}
        progress('Compiling the GPU kernel for '+device['name']+'.',device_name=device['name'])
        cl=OpenCL(device_key);cl.build();local=choose_local(cl.metadata)
        progress('Comparing GPU results with the official VRF implementation.',device_name=device['name'])
        checks=correctness(cl,sensor,require_hotspot,local)
        measured=calibrate(cl,sensor,device_key,require_hotspot,local,power_available)
        from device_profile import device_fingerprint
        kernel_hash=hashlib.sha256((APP_ROOT/'miner/vrf.cl').read_bytes()).hexdigest()
        profile=dict(schema_version=1,device_key=device_key,device_name=device['name'],vendor=device['vendor'],driver=device['driver'],kernel_sha256=kernel_hash,fingerprint=device_fingerprint(device,kernel_hash),sensor_capabilities=caps,power_available=power_available,self_test=checks,created_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),**measured)
        progress('Creating or checking your separate encrypted wallet. No private information is logged.')
        from wallet import create
        create()
        save(DATA_ROOT/'device-profile.json',profile)
        from device_profile import load_validated_profile
        load_validated_profile()
        save(DATA_ROOT/'performance.json',{'mode':'maximum'})
        progress('Setup passed. Back up your wallet and recovery password, then click Start mining.',state='ready',device_name=device['name'],device_key=device_key)
    finally:
        if cl:cl.close()
        if sensor:sensor.close()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--list-devices',action='store_true');p.add_argument('--device');a=p.parse_args()
    if a.list_devices:
        devices=enumerate_devices()
        inventory={'devices':devices,'recommended_device_key':None}
        try:inventory['recommended_device_key']=recommended_device_key(devices)
        except RuntimeError as exc:inventory['recommendation_error']=str(exc)
        print(json.dumps(inventory));return
    ensure_data_dirs()
    try:setup(a.device)
    except Exception as exc:
        progress(str(exc),state='failed');raise SystemExit(1)

if __name__=='__main__':main()
