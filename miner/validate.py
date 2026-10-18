from paths import DATA_ROOT, ensure_data_dirs
"""RFC vectors and independent official Go proof checks of GPU results."""
from pathlib import Path
import re,json,time,secrets,argparse
from opencl_backend import OpenCL
from oracle import Oracle,ROOT
from telemetry import Telemetry
def vectors():
    s=(ROOT/'upstream/util/vrf/vrf_test.go').read_text(encoding='utf-8')
    return [dict(re.findall(r'(name|sk|pk|alpha|beta):\s*"([^"]*)"',b)) for b in s.split('name:')[1:]]
def rfc_vectors():
    s=(ROOT/'upstream/util/vrf/vrf_test.go').read_text(encoding='utf-8')
    return [dict(re.findall(r'(name|sk|pk|alpha|beta):\s*"([^"]*)"',b)) for b in re.findall(r'\{\s*name:.*?\},',s,re.S)]
def tz(beta):
    n=int.from_bytes(beta,'big');return 512 if n==0 else (n&-n).bit_length()-1
def main():
    p=argparse.ArgumentParser();p.add_argument('--samples',type=int,default=128);p.add_argument('--batch',type=int,default=1024);args=p.parse_args()
    ensure_data_dirs()
    from device_profile import load_validated_profile
    local=load_validated_profile()['local']
    cl=OpenCL();t=time.perf_counter();cl.build();result={'device':cl.metadata,'build_seconds':time.perf_counter()-t,'rfc_vectors':[]}
    try:
        for v in rfc_vectors():
            o=Oracle(seed=bytes.fromhex(v['sk']))
            try:
                alpha=bytes.fromhex(v['alpha']);cl.prepare(o.pubkey,o.scalar,alpha,1)
                b,seconds=cl.run(0,1,False,local_size=1)
                if b.hex()!=v['beta'] or b!=o.evaluate(alpha):raise RuntimeError('RFC mismatch: '+v['name'])
                result['rfc_vectors'].append({'name':v['name'],'passed':True,'seconds':seconds})
                print(v['name']+' GPU/RFC/Go proof passed',flush=True)
            finally:o.close()
        checked=0;total_seconds=0
        # New keys and realistic 37-byte prefixes; include uint64 nonce carry/wrap.
        for start in [0,(1<<32)-128,(1<<64)-128]:
            o=Oracle(seed=secrets.token_bytes(32));prefix=secrets.token_bytes(37)
            try:
                cl.prepare(o.pubkey,o.scalar,prefix,args.batch)
                data,seconds=cl.run(start,args.batch,local_size=local);total_seconds+=seconds
                indices={0,1,127,128,args.batch-1}
                indices.update(secrets.randbelow(args.batch) for _ in range(args.samples))
                for i in sorted(indices):
                    if i>=args.batch:continue
                    nonce=((start+i)&((1<<64)-1)).to_bytes(8,'little')
                    beta=data[i*64:(i+1)*64]
                    if beta!=o.evaluate(prefix+nonce):raise RuntimeError('GPU/Go differential mismatch')
                    checked+=1
                print(f'Random key, carry/wrap batch: {len(indices)} official proof checks passed, {args.batch/seconds:.1f} attempts/s',flush=True)
            finally:o.close()
        result.update({'differential_checks':checked,'differential_passed':True,'batch':args.batch,'gpu_attempts':args.batch*3,'gpu_seconds':total_seconds,'gpu_attempts_per_second':args.batch*3/total_seconds})
        (DATA_ROOT/'logs/validation.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    finally:cl.close()
if __name__=='__main__':main()
