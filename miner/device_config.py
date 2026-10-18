"""Recipient device choice. Never select another GPU implicitly."""
import json


def selected_device_key(device_key=None):
    if device_key is not None:
        if not isinstance(device_key, str) or not device_key.strip():
            raise RuntimeError('Choose a GPU in Setup first.')
        return device_key
    from paths import DATA_ROOT
    try:
        profile = json.loads((DATA_ROOT / 'device-profile.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise RuntimeError('GPU setup is missing or unreadable. Run Setup first.') from exc
    key = profile.get('device_key') if isinstance(profile, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError('GPU setup has no selected device. Run Setup first.')
    return key


def select_device(devices, device_key):
    matches = [d for d in devices if d.get('device_key') == device_key]
    if len(matches) != 1:
        raise RuntimeError('Selected GPU is missing or ambiguous. Run Setup again; no other GPU was selected.')
    return matches[0]


def recommended_device_key(devices):
    """First-setup default only; normal mining never switches the saved GPU.

    Dedicated memory is preferred over shared memory. Compute units/memory are
    coarse defaults for multiple cards, not a cross-vendor speed benchmark.
    """
    key_counts={}
    for device in devices:
        key=device.get('device_key')
        if isinstance(key,str) and key: key_counts[key]=key_counts.get(key,0)+1
    eligible=[device for device in devices if device.get('vendor_id') in (0x1002,0x10de)
              and not device.get('identity_error') and not device.get('telemetry_error')
              and isinstance(device.get('device_key'),str) and key_counts.get(device['device_key'])==1]
    if not eligible:
        raise RuntimeError('No supported AMD or NVIDIA GPU with an unambiguous identity was detected.')
    def rank(device):
        shared=device.get('host_unified_memory')
        dedicated_rank=2 if shared is False else (0 if shared is True else 1)
        def positive_int(field):
            value=device.get(field)
            return value if isinstance(value,int) and not isinstance(value,bool) and value>0 else 0
        return (-dedicated_rank,-positive_int('compute_units'),-positive_int('global_memory_bytes'),device['device_key'])
    return sorted(eligible,key=rank)[0]['device_key']


def pci_tuple(device):
    values = tuple(device.get('pci_' + field) for field in ('bus', 'device', 'function'))
    if any(isinstance(x, bool) or not isinstance(x, int) for x in values):
        raise RuntimeError('GPU PCI identity is unavailable; safe sensor matching is not supported.')
    if not (0 <= values[0] <= 255 and 0 <= values[1] <= 31 and 0 <= values[2] <= 7):
        raise RuntimeError('GPU PCI identity is invalid.')
    return values


def match_adl_adapter(device, adapters):
    target = pci_tuple(device)
    matches = [a for a in adapters if a['present'] and
               a['vendor'] in (0x1002, 1002) and
               (a['bus'], a['device'], a['function']) == target]
    # ADL may enumerate multiple display entries for one physical adapter.
    # Its documented physical adapter ID must agree; names are insufficient.
    if not matches:
        raise RuntimeError('No AMD temperature sensor matches the selected GPU PCI address.')
    identities = {a.get('physical_id') for a in matches if a.get('physical_id')}
    if len(matches) > 1 and (len(identities) != 1 or any(not a.get('physical_id') for a in matches)):
        raise RuntimeError('AMD sensor PCI address is ambiguous; no GPU sensor was selected.')
    return min(matches, key=lambda a: a['index'])
