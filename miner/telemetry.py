"""Read-only AMD ADL / NVIDIA NVML sensors bound to the selected PCI GPU."""
import ctypes as C
import os
from pathlib import Path
import re
import time
from device_config import selected_device_key, select_device, pci_tuple, match_adl_adapter
from opencl_backend import enumerate_devices

P=C.c_void_p; I=C.c_int; U=C.c_uint


class Adapter(C.Structure):
    _fields_=[('size',I),('index',I),('udid',C.c_char*256),('bus',I),('device',I),('function',I),('vendor',I),('name',C.c_char*256),('display',C.c_char*256),('present',I),('exists',I),('driver',C.c_char*256),('driver_ext',C.c_char*256),('pnp',C.c_char*256),('os_index',I)]


class Sensor(C.Structure): _fields_=[('supported',I),('value',I)]
class PMLog(C.Structure): _fields_=[('size',I),('sensors',Sensor*256)]


def _system_dll(name):
    return Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/name


class AMD:
    def __init__(self, device):
        self.device=device; pci_tuple(device)
        self.lib=C.WinDLL(str(_system_dll('atiadlxx.dll'))); self.allocs=[]; self.context=P()
        def alloc(n):
            b=C.create_string_buffer(n); self.allocs.append(b); return C.addressof(b)
        self.cb=C.CFUNCTYPE(P,I)(alloc)
        signatures=[('ADL2_Main_Control_Create',[P,I,P]),('ADL2_Adapter_NumberOfAdapters_Get',[P,P]),
                    ('ADL2_Adapter_AdapterInfo_Get',[P,P,I]),('ADL2_Adapter_ID_Get',[P,I,P]),('ADL2_New_QueryPMLogData_Get',[P,I,P]),
                    ('ADL2_Main_Control_Destroy',[P])]
        for name,args in signatures:
            f=getattr(self.lib,name); f.argtypes=args; f.restype=I
        self.check(self.lib.ADL2_Main_Control_Create(self.cb,1,C.byref(self.context)))
        try:
            n=I(); self.check(self.lib.ADL2_Adapter_NumberOfAdapters_Get(self.context,C.byref(n)))
            a=(Adapter*n.value)()
            for item in a: item.size=C.sizeof(Adapter)
            self.check(self.lib.ADL2_Adapter_AdapterInfo_Get(self.context,a,C.sizeof(a)))
            adapters=[{'index':x.index,'bus':x.bus,'device':x.device,'function':x.function,
                       'vendor':x.vendor,'present':x.present,'pnp':x.pnp.decode(errors='replace')} for x in a]
            for adapter in adapters:
                physical_id=I()
                if self.lib.ADL2_Adapter_ID_Get(self.context,adapter['index'],C.byref(physical_id))==0:
                    adapter['physical_id']=physical_id.value
            self.adapter=match_adl_adapter(device,adapters)['index']
        except Exception:
            self.close(); raise

    @staticmethod
    def check(err):
        if err: raise RuntimeError('AMD sensor read error '+str(err))

    def read(self):
        data=PMLog(); data.size=C.sizeof(data)
        self.check(self.lib.ADL2_New_QueryPMLogData_Get(self.context,self.adapter,C.byref(data)))
        result={}
        for name,idx in [('edge_c',8),('memory_c',9),('gpu_busy_percent',19),('memory_busy_percent',20),
                         ('asic_power_w',23),('hotspot_c',27),('gfx_clock_mhz',1),('gfx_power_w',30),('board_power_w',73)]:
            s=data.sensors[idx]; result[name]=s.value if s.supported else None
        return result

    def close(self):
        if self.context:
            self.lib.ADL2_Main_Control_Destroy(self.context); self.context=P(); self.allocs.clear()


class PciInfo(C.Structure):
    _fields_=[('busIdLegacy',C.c_char*16),('domain',U),('bus',U),('device',U),
              ('pciDeviceId',U),('pciSubSystemId',U),('busId',C.c_char*32)]


class Utilization(C.Structure): _fields_=[('gpu',U),('memory',U)]


def parse_pci_bus_id(value):
    if isinstance(value,bytes): value=value.decode('ascii')
    match=re.fullmatch(r'([0-9a-fA-F]+):([0-9a-fA-F]{1,2}):([0-9a-fA-F]{1,2})\.([0-7])',value)
    if not match: raise RuntimeError('NVIDIA driver returned an invalid PCI identity.')
    domain,bus,device,function=(int(x,16) for x in match.groups())
    if bus>255 or device>31: raise RuntimeError('NVIDIA driver returned an invalid PCI address.')
    return domain,bus,device,function


def matching_nvml_entries(device, entries):
    target=pci_tuple(device); domain=device.get('pci_domain')
    matches=[entry for entry in entries if tuple(entry['pci'][1:])==target and
             (domain is None or entry['pci'][0]==domain)]
    if len(matches)!=1:
        raise RuntimeError('NVIDIA sensor PCI identity is missing or ambiguous; no other GPU was selected.')
    return matches[0]


class NVIDIA:
    def __init__(self,device):
        self.device=device; pci_tuple(device); self.initialized=False
        # Only official driver installation locations; no PATH/archive DLL search.
        locations=[_system_dll('nvml.dll')]
        program_files=os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles')
        if program_files: locations.append(Path(program_files)/'NVIDIA Corporation'/'NVSMI'/'nvml.dll')
        self.lib=None
        for path in locations:
            if path.is_file():
                try: self.lib=C.WinDLL(str(path)); break
                except OSError: continue
        if self.lib is None: raise RuntimeError('NVIDIA NVML sensors are unavailable. Install the official NVIDIA display driver.')
        signatures={
            'nvmlInit_v2':([],I),'nvmlShutdown':([],I),'nvmlDeviceGetCount_v2':([P],I),
            'nvmlDeviceGetHandleByIndex_v2':([U,P],I),'nvmlDeviceGetHandleByPciBusId_v2':([C.c_char_p,P],I),
            'nvmlDeviceGetPciInfo_v3':([P,P],I),'nvmlDeviceGetTemperature':([P,U,P],I),
            'nvmlDeviceGetPowerUsage':([P,P],I),'nvmlDeviceGetUtilizationRates':([P,P],I),
            'nvmlDeviceGetClockInfo':([P,U,P],I)}
        for name,(args,ret) in signatures.items():
            f=getattr(self.lib,name,None)
            if f is None:
                if name in ('nvmlDeviceGetPowerUsage','nvmlDeviceGetUtilizationRates','nvmlDeviceGetClockInfo'): continue
                raise RuntimeError('NVIDIA driver lacks required sensor function '+name)
            f.argtypes=args; f.restype=ret
        self.check(self.lib.nvmlInit_v2()); self.initialized=True
        try:
            count=U(); self.check(self.lib.nvmlDeviceGetCount_v2(C.byref(count))); entries=[]
            for i in range(count.value):
                handle=P()
                # An inaccessible unrelated GPU must not prevent access to a known GPU.
                if self.lib.nvmlDeviceGetHandleByIndex_v2(i,C.byref(handle))!=0: continue
                pci=PciInfo()
                if self.lib.nvmlDeviceGetPciInfo_v3(handle,C.byref(pci))!=0: continue
                bus_id=pci.busId or pci.busIdLegacy
                parsed=parse_pci_bus_id(bus_id)
                entries.append({'pci':parsed,'bus_id':bus_id})
            selected=matching_nvml_entries(device,entries); self.handle=P()
            self.check(self.lib.nvmlDeviceGetHandleByPciBusId_v2(selected['bus_id'],C.byref(self.handle)))
            verify=PciInfo(); self.check(self.lib.nvmlDeviceGetPciInfo_v3(self.handle,C.byref(verify)))
            if parse_pci_bus_id(verify.busId or verify.busIdLegacy)!=selected['pci']:
                raise RuntimeError('NVIDIA sensor device changed during selection.')
        except Exception:
            self.close(); raise

    @staticmethod
    def check(err):
        if err: raise RuntimeError('NVIDIA sensor read error '+str(err))

    def optional_uint(self,name,*args):
        function=getattr(self.lib,name,None)
        if function is None: return None
        value=U(); status=function(self.handle,*args,C.byref(value))
        if status in (3,4): return None  # NOT_SUPPORTED / NO_PERMISSION are capabilities, never zero measurements.
        self.check(status); return value.value

    def read(self):
        edge=self.optional_uint('nvmlDeviceGetTemperature',0)
        power=self.optional_uint('nvmlDeviceGetPowerUsage')
        util=Utilization(); gpu_busy=memory_busy=None
        function=getattr(self.lib,'nvmlDeviceGetUtilizationRates',None)
        if function is not None:
            status=function(self.handle,C.byref(util))
            if status==0: gpu_busy=util.gpu; memory_busy=util.memory
            elif status not in (3,4): self.check(status)
        return {'edge_c':edge,'hotspot_c':None,'memory_c':None,
                'board_power_w':None if power is None else power/1000.0,
                'gpu_busy_percent':gpu_busy,'memory_busy_percent':memory_busy,
                'gfx_clock_mhz':self.optional_uint('nvmlDeviceGetClockInfo',0),
                'asic_power_w':None,'gfx_power_w':None}

    def close(self):
        if self.initialized:
            self.lib.nvmlShutdown(); self.initialized=False


class Telemetry:
    def __init__(self,device_key=None):
        key=selected_device_key(device_key)
        self.device=select_device(enumerate_devices(),key)
        if self.device.get('identity_error'): raise RuntimeError(self.device['identity_error'])
        vendor=self.device['vendor_id']
        if vendor==0x1002: self.backend=AMD(self.device)
        elif vendor==0x10de: self.backend=NVIDIA(self.device)
        else: raise RuntimeError('This beta supports AMD and NVIDIA telemetry only.')

    def read(self):
        reading=self.backend.read()
        reading.update(time=time.time(),device_key=self.device['device_key'],vendor=self.device['vendor'],
                       vendor_id=self.device['vendor_id'],name=self.device['name'],
                       pci_domain=self.device.get('pci_domain'),pci_bus=self.device['pci_bus'],
                       pci_device=self.device['pci_device'],pci_function=self.device['pci_function'])
        reading['capabilities']={field:reading.get(field) is not None for field in
                                 ('edge_c','hotspot_c','memory_c','board_power_w','gpu_busy_percent')}
        if reading.get('edge_c') is None:
            raise RuntimeError('The selected GPU does not provide a readable core temperature. Mining is unavailable.')
        return reading

    def close(self): self.backend.close()


def collect_inventory():
    """Read-only inventory plus available sensors; no GPU computation."""
    devices=enumerate_devices()
    for device in devices:
        sensor=None
        try:
            sensor=Telemetry(device['device_key']); device['telemetry']=sensor.read()
        except Exception as exc: device['telemetry_error']=str(exc)
        finally:
            if sensor is not None: sensor.close()
    return devices


if __name__=='__main__':
    import json
    print(json.dumps(collect_inventory(),indent=2))
