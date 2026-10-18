"""OpenCL 1.2 backend with explicit, physically identified GPU selection."""
import ctypes as C
from pathlib import Path
import hashlib
import os
import time
from device_config import selected_device_key, select_device

P=C.c_void_p; U=C.c_uint; SZ=C.c_size_t; I=C.c_int; Q=C.c_ulonglong


class _API:
    def __init__(self):
        # Load the installed system ICD, never a DLL from the unpacked archive.
        self.lib=C.WinDLL(str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'/'OpenCL.dll'))
        signatures={
          'clGetPlatformIDs':([U,P,P],I), 'clGetDeviceIDs':([P,Q,U,P,P],I),
          'clGetDeviceInfo':([P,U,SZ,P,P],I), 'clGetPlatformInfo':([P,U,SZ,P,P],I),
          'clCreateContext':([P,U,P,P,P,P],P), 'clCreateCommandQueue':([P,P,Q,P],P),
          'clCreateProgramWithSource':([P,U,P,P,P],P), 'clBuildProgram':([P,U,P,C.c_char_p,P,P],I),
          'clGetProgramBuildInfo':([P,P,U,SZ,P,P],I), 'clCreateKernel':([P,C.c_char_p,P],P),
          'clGetKernelWorkGroupInfo':([P,P,U,SZ,P,P],I),
          'clCreateBuffer':([P,Q,SZ,P,P],P), 'clSetKernelArg':([P,U,SZ,P],I),
          'clEnqueueNDRangeKernel':([P,P,U,P,P,P,U,P,P],I),
          'clEnqueueReadBuffer':([P,P,U,SZ,SZ,P,U,P,P],I),
          'clEnqueueWriteBuffer':([P,P,U,SZ,SZ,P,U,P,P],I), 'clFinish':([P],I),
          'clReleaseMemObject':([P],I), 'clReleaseKernel':([P],I),
          'clReleaseProgram':([P],I), 'clReleaseCommandQueue':([P],I), 'clReleaseContext':([P],I)}
        for name,(args,ret) in signatures.items():
            f=getattr(self.lib,name); f.argtypes=args; f.restype=ret

    @staticmethod
    def check(err):
        if err: raise RuntimeError('OpenCL error '+str(err))

    def raw(self,d,param):
        n=SZ(); self.check(self.lib.clGetDeviceInfo(d,param,0,None,C.byref(n)))
        b=C.create_string_buffer(n.value); self.check(self.lib.clGetDeviceInfo(d,param,n,b,None))
        return b.raw

    def info(self,d,param):
        return self.raw(d,param).split(b'\0',1)[0].decode(errors='replace')

    def number(self,d,param,typ):
        v=typ(); self.check(self.lib.clGetDeviceInfo(d,param,C.sizeof(v),C.byref(v),None)); return v.value

    def platform_name(self,p):
        n=SZ(); self.check(self.lib.clGetPlatformInfo(p,0x0902,0,None,C.byref(n)))
        b=C.create_string_buffer(n.value); self.check(self.lib.clGetPlatformInfo(p,0x0902,n,b,None))
        return b.value.decode(errors='replace')

    def inventory(self):
        count=U(); status=self.lib.clGetPlatformIDs(0,None,C.byref(count))
        if status == -1001: return []
        self.check(status)
        platforms=(P*count.value)(); self.check(self.lib.clGetPlatformIDs(count,platforms,None))
        rows=[]
        for pi,plat in enumerate(platforms):
            dc=U(); err=self.lib.clGetDeviceIDs(plat,4,0,None,C.byref(dc))
            if err==-1: continue
            self.check(err); ds=(P*dc.value)(); self.check(self.lib.clGetDeviceIDs(plat,4,dc,ds,None))
            for di,d in enumerate(ds):
                name=self.info(d,0x102b); vendor=self.info(d,0x102c)
                extensions=set(self.info(d,0x1030).split()); vendor_id=self.number(d,0x1001,U)
                board=''
                if vendor_id == 0x1002 and 'cl_amd_device_attribute_query' in extensions:
                    try: board=self.info(d,0x4038)
                    except RuntimeError: pass
                row={'name':board or name,'opencl_name':name,'vendor':vendor,'vendor_id':vendor_id,
                     'driver':self.info(d,0x102d),'version':self.info(d,0x102f),
                     'global_memory_bytes':self.number(d,0x101f,Q),'compute_units':self.number(d,0x1002,U),
                     'max_work_group':self.number(d,0x1004,SZ),'platform':self.platform_name(plat),
                     'pci_domain':None,'pci_bus':None,'pci_device':None,'pci_function':None,
                     '_device':d,'_platform':plat,'_registration':(pi,di)}
                try: row['host_unified_memory']=bool(self.number(d,0x1035,U))
                except RuntimeError: row['host_unified_memory']=None
                dims=self.number(d,0x1003,U)
                raw=self.raw(d,0x1005)
                if dims and len(raw)>=C.sizeof(SZ):
                    row['max_work_item_size_0']=int.from_bytes(raw[:C.sizeof(SZ)],'little')
                if 'cl_khr_pci_bus_info' in extensions:
                    try:
                        raw=self.raw(d,0x410f)
                        if len(raw)>=16:
                            row.update(zip(('pci_domain','pci_bus','pci_device','pci_function'),
                                           (int.from_bytes(raw[i:i+4],'little') for i in range(0,16,4))))
                    except RuntimeError: pass
                if row['pci_bus'] is None and vendor_id==0x1002 and 'cl_amd_device_attribute_query' in extensions:
                    try:
                        raw=self.raw(d,0x4037)
                        if len(raw)>=24 and int.from_bytes(raw[:4],'little')==1:
                            row.update(pci_bus=raw[21],pci_device=raw[22],pci_function=raw[23])
                    except RuntimeError: pass
                if 'cl_khr_device_uuid' in extensions:
                    try:
                        raw=self.raw(d,0x106a)
                        if len(raw)==16 and any(raw): row['uuid']=raw.hex()
                    except RuntimeError: pass
                rows.append(row)
        return deduplicate_devices(rows)


def deduplicate_devices(rows):
    """Collapse duplicate platform registrations only when PCI identity agrees."""
    groups={}; unknown=[]
    for row in rows:
        if all(row.get('pci_'+f) is not None for f in ('bus','device','function')):
            triple=(row['vendor_id'],row['pci_bus'],row['pci_device'],row['pci_function'])
            groups.setdefault(triple,[]).append(row)
        else: unknown.append(row)
    result=[]
    for triple,group in groups.items():
        known_domains={r['pci_domain'] for r in group if r.get('pci_domain') is not None}
        # A missing domain cannot be assigned to one of multiple actual domains.
        domains=known_domains or {None}
        for domain in domains:
            matches=[r for r in group if r.get('pci_domain')==domain or
                     (r.get('pci_domain') is None and len(domains)==1)]
            if not matches: continue
            signatures={(r['vendor_id'],r['global_memory_bytes'],r['compute_units']) for r in matches}
            uuids={r.get('uuid') for r in matches if r.get('uuid')}
            row=dict(matches[0]); row['pci_domain']=domain
            row['registrations']=len(matches)
            if len(signatures)>1 or len(uuids)>1:
                row['identity_error']='Conflicting devices share a reported PCI address.'
            domain_text=f'{domain:04x}' if domain is not None else 'unknown'
            row['device_key']=f"pci:{triple[0]:04x}:{domain_text}:{triple[1]:02x}:{triple[2]:02x}.{triple[3]}"
            result.append(row)
        if len(domains)>1:
            unknown.extend(r for r in group if r.get('pci_domain') is None)
    for row in unknown:
        row=dict(row); pi,di=row['_registration']
        row['device_key']=f"unbound:{row['vendor_id']:04x}:{pi}:{di}"
        row['identity_error']='The driver does not expose an unambiguous PCI address for sensor matching.'
        row['registrations']=1; result.append(row)
    return result


def public_device(row):
    return {key:value for key,value in row.items() if not key.startswith('_')}


def enumerate_devices():
    """Enumerate only; no context, compilation, GPU workload, or wallet access."""
    return [public_device(row) for row in _API().inventory()]


class OpenCL(_API):
    def __init__(self, device_key=None):
        key=selected_device_key(device_key)
        super().__init__(); devices=self.inventory(); selected=select_device(devices,key)
        if selected.get('identity_error'): raise RuntimeError(selected['identity_error'])
        if selected['vendor_id'] not in (0x1002,0x10de): raise RuntimeError('This beta supports AMD and NVIDIA GPUs only.')
        self.device=selected['_device']; self.name=selected['name']; self.metadata=public_device(selected)
        self.devices=[public_device(d) for d in devices]; self.buffers=[]
        err=I(); dev=P(self.device)
        # Bind explicitly to the enumerated platform.
        props=(C.c_ssize_t*3)(0x1084,selected['_platform'],0)
        self.context=self.lib.clCreateContext(props,1,C.byref(dev),None,None,C.byref(err)); self.check(err.value)
        try:
            self.queue=self.lib.clCreateCommandQueue(self.context,self.device,0,C.byref(err)); self.check(err.value)
        except Exception:
            self.close(); raise

    def num(self,param,typ): return self.number(self.device,param,typ)

    def build(self):
        src=(Path(__file__).parent/'vrf.cl').read_bytes(); s=C.c_char_p(src); n=SZ(len(src)); err=I()
        self.program=self.lib.clCreateProgramWithSource(self.context,1,C.byref(s),C.byref(n),C.byref(err)); self.check(err.value)
        dev=P(self.device); ret=self.lib.clBuildProgram(self.program,1,C.byref(dev),b'-cl-std=CL1.2',None,None)
        if ret:
            size=SZ(); self.lib.clGetProgramBuildInfo(self.program,self.device,0x1183,0,None,C.byref(size))
            log=C.create_string_buffer(size.value); self.lib.clGetProgramBuildInfo(self.program,self.device,0x1183,size,log,None)
            raise RuntimeError(log.value.decode(errors='replace'))
        self.kernel=self.lib.clCreateKernel(self.program,b'vrf_batch',C.byref(err)); self.check(err.value)
        cap=SZ(); self.check(self.lib.clGetKernelWorkGroupInfo(self.kernel,self.device,0x11b0,C.sizeof(cap),C.byref(cap),None))
        self.metadata['kernel_max_work_group']=cap.value

    def buffer(self,data=None,size=None):
        err=I(); buf=C.create_string_buffer(data) if data is not None else None
        m=self.lib.clCreateBuffer(self.context,1|(32 if data is not None else 0),len(data) if data is not None else size,buf,C.byref(err))
        self.check(err.value); self.buffers.append(m); return m

    def release_buffers(self):
        if getattr(self,'scbuf',None) in self.buffers:
            zero=C.create_string_buffer(32)
            self.lib.clEnqueueWriteBuffer(self.queue,self.scbuf,1,0,32,zero,0,None,None)
        for b in self.buffers: self.lib.clReleaseMemObject(b)
        self.buffers=[]

    def prepare(self,pubkey,scalar,prefix,count):
        if len(prefix)>69: raise ValueError('message too long for one-block TAI kernel')
        if len(pubkey)!=32 or len(scalar)!=32 or not isinstance(count,int) or count<=0:
            raise ValueError('invalid VRF inputs or batch size')
        self.release_buffers(); self.pkbuf=self.buffer(pubkey); self.scbuf=self.buffer(scalar)
        self.prefixbuf=self.buffer(prefix or b'\0'); self.outbuf=self.buffer(size=count*64)
        self.prefix_len=len(prefix); self.capacity=count

    def validate_dispatch(self,count,local_size):
        if not isinstance(count,int) or count<=0 or count>self.capacity: raise ValueError('invalid batch size')
        if local_size is not None:
            limits=[self.metadata['max_work_group'],self.metadata.get('kernel_max_work_group',self.metadata['max_work_group']),
                    self.metadata.get('max_work_item_size_0',self.metadata['max_work_group'])]
            if isinstance(local_size,bool) or not isinstance(local_size,int) or local_size<=0 or count%local_size or local_size>min(limits):
                raise ValueError('local size exceeds the selected GPU/kernel limits or does not divide the batch')

    def run(self,start,count,with_nonce=True,local_size=64):
        self.validate_dispatch(count,local_size)
        args=[P(self.pkbuf),P(self.scbuf),P(self.prefixbuf),U(self.prefix_len),Q(start),U(with_nonce),P(self.outbuf)]
        for i,v in enumerate(args): self.check(self.lib.clSetKernelArg(self.kernel,i,C.sizeof(v),C.byref(v)))
        glob=SZ(count); loc=SZ(local_size or 0); out=C.create_string_buffer(count*64); t=time.perf_counter()
        self.check(self.lib.clEnqueueNDRangeKernel(self.queue,self.kernel,1,None,C.byref(glob),C.byref(loc) if local_size else None,0,None,None))
        self.check(self.lib.clEnqueueReadBuffer(self.queue,self.outbuf,1,0,count*64,out,0,None,None))
        return out.raw,time.perf_counter()-t

    def close(self):
        self.release_buffers()
        for attr,fn in [('kernel','clReleaseKernel'),('program','clReleaseProgram'),('queue','clReleaseCommandQueue'),('context','clReleaseContext')]:
            if getattr(self,attr,None): getattr(self.lib,fn)(getattr(self,attr)); setattr(self,attr,None)


def expand(seed):
    x=bytearray(hashlib.sha512(seed).digest()[:32]); x[0]&=248; x[31]&=127; x[31]|=64; return bytes(x)


if __name__=='__main__':
    import json
    print(json.dumps(enumerate_devices(),indent=2))
