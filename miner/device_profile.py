"""Validate recipient setup against the present GPU, driver, and immutable kernel."""
import hashlib
import json
import math
import re
from pathlib import Path
from device_config import select_device
from opencl_backend import enumerate_devices
from paths import DATA_ROOT

MODE_NAMES=('maximum','balanced','eco')
FINGERPRINT_FIELDS=('device_key','vendor_id','vendor','name','opencl_name','driver','version',
                    'global_memory_bytes','compute_units','max_work_group','max_work_item_size_0',
                    'pci_domain','pci_bus','pci_device','pci_function')


def kernel_hash():
    return hashlib.sha256((Path(__file__).parent/'vrf.cl').read_bytes()).hexdigest()


def _sha(value,label):
    if not isinstance(value,str) or re.fullmatch('[0-9a-fA-F]{64}',value) is None:
        raise RuntimeError('GPU setup has an invalid '+label+'. Run Setup again.')
    return value.lower()


def device_fingerprint(device,kernel_sha256=None):
    """A reproducible identity, not a signature or a replacement for self-tests."""
    digest=_sha(kernel_sha256 if kernel_sha256 is not None else kernel_hash(),'kernel hash')
    identity={key:device.get(key) for key in FINGERPRINT_FIELDS}
    identity['kernel_sha256']=digest
    encoded=json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _number(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise RuntimeError('GPU setup has an invalid '+label+'. Run Setup again.')
    return float(value)


def _dispatch(settings,device,label):
    if not isinstance(settings,dict): raise RuntimeError('GPU setup lacks '+label+' dispatch settings.')
    batch=settings.get('batch'); local=settings.get('local')
    if isinstance(batch,bool) or not isinstance(batch,int) or not 64<=batch<=131072:
        raise RuntimeError('GPU setup has an invalid '+label+' batch size.')
    limits=[device.get('max_work_group',0),device.get('max_work_item_size_0',device.get('max_work_group',0))]
    if (isinstance(local,bool) or not isinstance(local,int) or local not in (1,2,4,8,16,32,64,128,256) or
            local>min(limits) or batch%local):
        raise RuntimeError('GPU setup local size is unsupported by the selected GPU.')


def validate_profile(profile,devices,current_kernel_sha256):
    """Pure validation core for focused tests; does not mutate profile or GPU."""
    if not isinstance(profile,dict): raise RuntimeError('GPU setup is invalid. Run Setup again.')
    key=profile.get('device_key')
    if not isinstance(key,str) or not key: raise RuntimeError('GPU setup has no selected device.')
    device=select_device(devices,key)
    if device.get('identity_error'): raise RuntimeError(device['identity_error'])
    if device.get('vendor_id') not in (0x1002,0x10de): raise RuntimeError('GPU setup selects an unsupported manufacturer.')
    actual_hash=_sha(current_kernel_sha256,'current kernel hash')
    if _sha(profile.get('kernel_sha256'),'kernel hash')!=actual_hash:
        raise RuntimeError('The GPU kernel changed. Run Setup to verify this version before mining.')
    if _sha(profile.get('fingerprint'),'device fingerprint')!=device_fingerprint(device,actual_hash):
        raise RuntimeError('The GPU or display driver changed. Run Setup to verify this device before mining.')
    for profile_field,device_field in (('device_name','name'),('driver','driver'),('vendor','vendor')):
        if profile.get(profile_field)!=device.get(device_field):
            raise RuntimeError('GPU setup '+profile_field+' no longer matches the selected device. Run Setup again.')
    if 'vendor_id' in profile and profile['vendor_id']!=device['vendor_id']:
        raise RuntimeError('GPU setup manufacturer no longer matches the selected device.')
    test=profile.get('self_test')
    if not isinstance(test,dict) or test.get('passed') is not True:
        raise RuntimeError('This GPU has not passed the required correctness tests. Run Setup first.')
    capabilities=profile.get('sensor_capabilities')
    if not isinstance(capabilities,dict) or capabilities.get('core_temperature') is not True:
        raise RuntimeError('A verified core temperature sensor is required for mining.')
    for field in ('hotspot_temperature','board_power'):
        if not isinstance(capabilities.get(field),bool):
            raise RuntimeError('GPU setup has an invalid sensor capability: '+field)
    for field in ('memory_temperature','gpu_busy'):
        if field in capabilities and not isinstance(capabilities[field],bool):
            raise RuntimeError('GPU setup has an invalid sensor capability: '+field)
    power_available=profile.get('power_available')
    if not isinstance(power_available,bool) or power_available!=capabilities['board_power']:
        raise RuntimeError('GPU setup power sensor capability is inconsistent.')
    modes=profile.get('modes')
    if not isinstance(modes,dict) or set(modes)!=set(MODE_NAMES):
        raise RuntimeError('GPU setup must describe maximum, balanced, and eco mode availability.')
    for name in MODE_NAMES:
        mode=modes[name]
        if not isinstance(mode,dict) or not isinstance(mode.get('enabled'),bool):
            raise RuntimeError('GPU setup has invalid '+name+' mode availability.')
        if 'reason' in mode and not isinstance(mode['reason'],str):
            raise RuntimeError('GPU setup has an invalid mode explanation.')
        if not mode['enabled'] and not str(mode.get('reason','')).strip():
            raise RuntimeError('Disabled GPU modes must explain why they are unavailable.')
    if not modes['maximum']['enabled']: raise RuntimeError('GPU setup cannot disable maximum mode.')
    _dispatch(profile,device,'maximum')
    _number(profile.get('attempts_per_second'),'measured rate')
    profiles=profile.get('power_profiles')
    if not power_available:
        if profiles is not None:
            raise RuntimeError('GPU setup cannot use power profiles without a board power sensor.')
        if modes['balanced']['enabled'] or modes['eco']['enabled']:
            raise RuntimeError('Power-saving modes require a verified board power sensor.')
        if profile.get('reference_max_board_w') is not None or profile.get('idle_board_w') is not None:
            raise RuntimeError('GPU setup cannot claim measured power without a board power sensor.')
        return profile
    if not isinstance(profiles,dict): raise RuntimeError('GPU setup lacks measured power profiles.')
    reference=_number(profiles.get('reference_board_power_w'),'reference board power')
    idle=_number(profiles.get('idle_board_power_w'),'idle board power')
    if idle>=reference: raise RuntimeError('Measured idle power must be below measured maximum power.')
    for alias,expected in (('reference_max_board_w',reference),('idle_board_w',idle)):
        if alias in profile and abs(_number(profile[alias],alias)-expected)>max(.05,expected*1e-6):
            raise RuntimeError('GPU setup power reference fields disagree.')
    for name,fraction in (('balanced',.5),('eco',.25)):
        entry=profiles.get(name); _dispatch(entry,device,name)
        target=_number(entry.get('target_w'),name+' target watts')
        _number(entry.get('initial_rate'),name+' initial rate')
        if abs(target-reference*fraction)>max(.05,reference*1e-6):
            raise RuntimeError('GPU setup power target does not match its reference fraction.')
        if modes[name]['enabled'] and target<=idle+1.0:
            raise RuntimeError('GPU setup enables a power target below the measured idle floor.')
    return profile


def load_validated_profile():
    """Read a saved profile and revalidate identity; no compilation or mining."""
    try:
        profile=json.loads((DATA_ROOT/'device-profile.json').read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:
        raise RuntimeError('GPU setup is missing or unreadable. Run Setup first.') from exc
    return validate_profile(profile,enumerate_devices(),kernel_hash())
