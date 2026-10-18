"""Encrypted recipient wallet. Recovery passphrase stays in local Windows DPAPI."""
import ctypes as C,hashlib,json,os,secrets,subprocess
from paths import APP_ROOT as ROOT,DATA_ROOT,ensure_data_dirs
from oracle import Oracle
from status_io import write_status

class Blob(C.Structure):_fields_=[('size',C.c_ulong),('data',C.POINTER(C.c_ubyte))]

def dpapi(data,decrypt=False):
    src=C.create_string_buffer(data);b=Blob(len(data),C.cast(src,C.POINTER(C.c_ubyte)));out=Blob()
    crypt=C.WinDLL('crypt32.dll');kernel=C.WinDLL('kernel32.dll')
    f=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    f.argtypes=[C.POINTER(Blob),C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_ulong,C.POINTER(Blob)];f.restype=C.c_int
    if not f(C.byref(b),None,None,None,None,1,C.byref(out)):raise RuntimeError('Windows user-bound wallet unlock failed')
    try:return C.string_at(out.data,out.size)
    finally:
        C.memset(out.data,0,out.size);kernel.LocalFree.argtypes=[C.c_void_p];kernel.LocalFree(out.data)

def unprotect(data):return dpapi(data,True)
def passphrase():return unprotect((DATA_ROOT/'wallet/unlock.dpapi').read_bytes()).decode()

def restrict_folder(folder):
    # Grant only the current account and SYSTEM. Never display identity or contents.
    result=subprocess.run(['whoami','/user','/fo','csv','/nh'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
    import csv
    sid=next(csv.reader(result.stdout.splitlines()))[1]
    if not sid.startswith('S-1-'):raise RuntimeError('Cannot determine wallet folder permissions')
    proc=subprocess.run(['icacls',str(folder),'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode:raise RuntimeError('Cannot protect the new wallet folder permissions')

def save_public(o):
    # Same address construction as the official keystore helper (public data only).
    holder=hashlib.blake2b(b'\0'+o.pubkey,digest_size=32).hexdigest()
    document={'pubkey':o.pubkey.hex(),'holder_id':holder,'key_file':'proxima.key','encrypted':True,'unlock':'Windows DPAPI, current user'}
    if not write_status(DATA_ROOT/'wallet/public.json',document):raise RuntimeError('Public wallet metadata is busy; retry setup')

def create():
    ensure_data_dirs();folder=DATA_ROOT/'wallet';folder.mkdir(exist_ok=True)
    restrict_folder(folder)
    key=folder/'proxima.key';unlock=folder/'unlock.dpapi'
    if key.exists() or unlock.exists():
        if not key.exists() or not unlock.exists():raise RuntimeError('Incomplete wallet exists. Files were preserved; recover the existing wallet before continuing.')
        try:
            o=Oracle(key_file=key,passphrase=passphrase())
            try:save_public(o)
            finally:o.close()
        except Exception:raise RuntimeError('Existing wallet could not be unlocked. Files were preserved; use the original Windows account or your recovery backup.') from None
        print('Existing encrypted wallet verified; no wallet was replaced.',flush=True);return
    password=secrets.token_urlsafe(48)
    with unlock.open('xb') as f:
        f.write(dpapi(password.encode()));f.flush();os.fsync(f.fileno())
    proc=subprocess.Popen([str(ROOT/'tools/oracle.exe')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        response,_=proc.communicate(json.dumps({'op':'create','key_file':str(key),'passphrase':password})+'\n',timeout=20)
        r=json.loads(response)
        if proc.returncode or 'error' in r or not key.is_file():raise ValueError()
        o=Oracle(key_file=key,passphrase=password)
        try:save_public(o)
        finally:o.close()
    except Exception:
        if proc.poll() is None:proc.kill();proc.wait()
        raise RuntimeError('Encrypted wallet creation did not complete. Existing files were preserved for recovery.') from None
    finally:password=''
    print('New encrypted wallet and local unlock verified. No credentials were logged.',flush=True)

def start_proxi(arguments,cwd):
    env=dict(os.environ);env['PROXIMA_KEY_PASSPHRASE']=passphrase()
    return subprocess.Popen([str(ROOT/'tools/proxi.exe')]+arguments,cwd=cwd,env=env)

if __name__=='__main__':create()
