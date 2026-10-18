import subprocess, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class Oracle:
    def __init__(self,seed=None,key_file=None,passphrase=''):
        self.proc=subprocess.Popen([str(ROOT/'tools/oracle.exe')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        r=self.call(op='init',seed=seed.hex() if seed is not None else '',key_file=str(key_file) if key_file else '',passphrase=passphrase)
        self.scalar=bytes.fromhex(r['scalar']);self.pubkey=bytes.fromhex(r['pubkey'])
    def call(self,**data):
        self.proc.stdin.write(json.dumps(data)+'\n');self.proc.stdin.flush()
        r=json.loads(self.proc.stdout.readline())
        if 'error' in r:raise RuntimeError(r['error'])
        return r
    def evaluate(self,alpha):
        r=self.call(op='eval',alpha=alpha.hex())
        if not r['verified']:raise RuntimeError('official VRF proof verification failed')
        return bytes.fromhex(r['beta'])
    def close(self):
        self.proc.stdin.close();self.proc.wait(timeout=5);self.scalar=b''
