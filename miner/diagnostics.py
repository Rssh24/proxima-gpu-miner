"""Export only bounded, scrubbed feedback data; never open wallet files."""
import datetime,json,os,re,zipfile
from pathlib import Path
from paths import APP_ROOT,DATA_ROOT,ensure_data_dirs
from status_io import write_status as write_json_snapshot

LOG_FILES=('setup.log','supervisor.out.log','supervisor.err.log','live-proxi.log','live-gpu.log','gpu-status.json','telemetry.jsonl','validation.json','supervisor.json')
LIMIT=2*1024*1024
PRIVATE_FIELD=re.compile(r'(?i)(passphrase|password|private.?key|seed|scalar|unlock|holder_id|pubkey)')
def scrub_value(text):
    for path in (str(DATA_ROOT),str(APP_ROOT),os.environ.get('USERPROFILE','')):
        if path:
            for variant in (path,path.replace('\\','/'),path.replace('\\','\\\\')):
                text=re.sub(re.escape(variant),'<local-path>',text,flags=re.I)
    text=re.sub(r'(?i)\ba/[0-9a-f]{64}\b','<wallet-address>',text)
    text=re.sub(r'(?i)\b[0-9a-f]{64,}\b','<hex-data>',text)
    text=re.sub(r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\\r\n"/]+','<user-profile>',text)
    return text

def scrub_object(value):
    if isinstance(value,dict):return {k:('[private field omitted]' if PRIVATE_FIELD.search(k) else scrub_object(v)) for k,v in value.items()}
    if isinstance(value,list):return [scrub_object(v) for v in value]
    if isinstance(value,str):return scrub_value(value)
    return value

def scrub(text):
    try:return json.dumps(scrub_object(json.loads(text)),indent=2)
    except ValueError:pass
    result=[]
    for line in text.splitlines():
        try:result.append(json.dumps(scrub_object(json.loads(line))));continue
        except ValueError:pass
        if re.search(r'(?i)(passphrase|password|private.?key|["\']?seed["\']?\s*[=:]|"scalar"|unlock\.dpapi)',line):
            result.append('[private field omitted]')
        else:result.append(scrub_value(line))
    return '\n'.join(result)+'\n'

def read_tail(path):
    with path.open('rb') as f:
        f.seek(0,2);size=f.tell();f.seek(max(0,size-LIMIT));data=f.read(LIMIT)
    if size>LIMIT:data=data.split(b'\n',1)[-1]
    return scrub(data.decode('utf-8',errors='replace'))

def export():
    ensure_data_dirs();destination=DATA_ROOT/'diagnostics';destination.mkdir(exist_ok=True)
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out=destination/('Proxima-diagnostics-'+stamp+'.zip')
    metadata={'beta_version':'0.1.1','created_at':datetime.datetime.now().astimezone().isoformat(),'contents':'Recent miner logs and GPU setup only. No wallet files, recovery passwords or private keys are included.'}
    profile=DATA_ROOT/'device-profile.json'
    if profile.is_file():
        p=json.loads(profile.read_text(encoding='utf-8'))
        metadata['gpu']={k:p.get(k) for k in ('device_name','vendor','driver','sensor_capabilities','power_available','modes','batch','local','attempts_per_second','max_batch_seconds','power_profiles','self_test')}
    counter=DATA_ROOT/'logs/acceptance-totals.json'
    if counter.is_file():
        counts=json.loads(counter.read_text(encoding='utf-8'))
        metadata['local_accepted_solutions']={k:counts.get(k) for k in ('schema_version','total_accepted','migrated_log_count')}
    build=APP_ROOT/'tools/build-info.json'
    if build.is_file():
        b=json.loads(build.read_text(encoding='utf-8-sig'))
        metadata['build']={k:b.get(k) for k in ('version','source_commit','miner_version','gpu_revision','thermal_revision','status_io_revision')}
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('diagnostics.json',json.dumps(scrub_object(metadata),indent=2))
        for name in LOG_FILES:
            path=DATA_ROOT/'logs'/name
            if path.is_file():z.writestr('logs/'+name,read_tail(path))
        for name in ('setup-status.json','performance.json'):
            path=DATA_ROOT/name
            if path.is_file():z.writestr(name,read_tail(path))
        z.writestr('README.txt','Review this archive before sharing. Logs may include public node URLs, transaction identifiers and times. Wallet files and recovery credentials are never read by this export. This program does not upload or send the archive.\n')
    if not write_json_snapshot(DATA_ROOT/'logs/diagnostics-export.json',{'path':str(out)}):
        raise RuntimeError('Could not publish the diagnostic archive location. Try again.')
    return out

if __name__=='__main__':print(export())
