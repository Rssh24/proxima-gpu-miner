"""Mock-only regression checks: do not create a context or submit GPU work."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from bootstrap import MINER, SCRATCH, temporary_directory
from device_config import selected_device_key,select_device,pci_tuple,match_adl_adapter
from opencl_backend import OpenCL,deduplicate_devices,public_device
from telemetry import parse_pci_bus_id,matching_nvml_entries,NVIDIA,Telemetry


def row(bus=3, domain=None, platform=0):
    return {'vendor_id':0x1002,'name':'Same model','driver':'1','global_memory_bytes':16*1024**3,
            'compute_units':32,'pci_bus':bus,'pci_device':0,'pci_function':0,'pci_domain':domain,
            '_device':42+platform,'_platform':9+platform,'_registration':(platform,0),'max_work_group':256}


def adapter(index=1, bus=3, physical_id=27):
    return dict(index=index,bus=bus,device=0,function=0,present=1,vendor=1002,pnp='not-used',physical_id=physical_id)


class DeviceBindingTests(unittest.TestCase):
    def test_explicit_key_does_not_read_profile(self):
        self.assertEqual(selected_device_key('chosen'), 'chosen')

    def test_missing_profile_cannot_auto_select(self):
        with patch.dict(sys.modules,{'paths':types.SimpleNamespace(DATA_ROOT=Path('unused'))}), patch.object(Path,'read_text',side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError,'Setup'): selected_device_key()

    def test_profile_key_read_only(self):
        with patch.dict(sys.modules,{'paths':types.SimpleNamespace(DATA_ROOT=Path('unused'))}), patch.object(Path,'read_text',return_value=json.dumps({'device_key':'chosen'})):
            self.assertEqual(selected_device_key(),'chosen')

    def test_invalid_explicit_key_does_not_fall_back(self):
        for key in ('',0,False,[],{}):
            with self.subTest(key=key),self.assertRaises(RuntimeError): selected_device_key(key)

    def test_missing_selected_device_fails(self):
        with self.assertRaises(RuntimeError): select_device([{'device_key':'other'}],'missing')

    def test_ambiguous_selected_device_fails(self):
        with self.assertRaises(RuntimeError): select_device([{'device_key':'same'},{'device_key':'same'}],'same')

    def test_duplicate_platforms_merge(self):
        devices=deduplicate_devices([row(),row(platform=1)])
        self.assertEqual(len(devices),1); self.assertEqual(devices[0]['registrations'],2)

    def test_two_identical_model_cards_stay_separate(self):
        devices=deduplicate_devices([row(bus=3),row(bus=4),row(bus=3,platform=1),row(bus=4,platform=1)])
        self.assertEqual(len(devices),2); self.assertNotEqual(devices[0]['device_key'],devices[1]['device_key'])

    def test_domain_separates_physical_cards(self):
        devices=deduplicate_devices([row(domain=0),row(domain=1)])
        self.assertEqual(len(devices),2); self.assertNotEqual(devices[0]['device_key'],devices[1]['device_key'])

    def test_unknown_domain_does_not_choose_known_domain_if_ambiguous(self):
        devices=deduplicate_devices([row(domain=0),row(domain=1),row(domain=None,platform=2)])
        self.assertEqual(len(devices),3); self.assertTrue(devices[-1].get('identity_error'))

    def test_same_card_with_known_and_unknown_domain_merges(self):
        devices=deduplicate_devices([row(domain=0),row(domain=None,platform=1)])
        self.assertEqual(len(devices),1); self.assertEqual(devices[0]['pci_domain'],0)

    def test_conflicting_pci_hardware_is_unsupported(self):
        different=row(platform=1); different['compute_units']=99
        self.assertIn('identity_error',deduplicate_devices([row(),different])[0])

    def test_conflicting_uuid_is_unsupported(self):
        a=row(); b=row(platform=1); a['uuid']='1'; b['uuid']='2'
        self.assertIn('identity_error',deduplicate_devices([a,b])[0])

    def test_no_pci_identity_is_not_name_matched(self):
        a=row(); a['pci_bus']=None
        self.assertIn('identity_error',deduplicate_devices([a])[0])

    def test_public_inventory_hides_handles(self):
        public=public_device(row()); self.assertFalse(any(k.startswith('_') for k in public)); json.dumps(public)

    def test_adl_binds_pci_not_index(self):
        self.assertEqual(match_adl_adapter(row(),[adapter(index=0,bus=4),adapter(index=5,bus=3)])['index'],5)

    def test_adl_display_duplicates_require_same_physical_id(self):
        self.assertEqual(match_adl_adapter(row(),[adapter(index=5),adapter(index=6)])['index'],5)

    def test_adl_ambiguous_physical_ids_fail(self):
        with self.assertRaises(RuntimeError): match_adl_adapter(row(),[adapter(5,physical_id=1),adapter(6,physical_id=2)])

    def test_adl_missing_physical_id_duplicates_fail(self):
        with self.assertRaises(RuntimeError): match_adl_adapter(row(),[adapter(5,physical_id=None),adapter(6,physical_id=None)])

    def test_adl_wrong_vendor_fails(self):
        a=adapter(); a['vendor']=0x10de
        with self.assertRaises(RuntimeError): match_adl_adapter(row(),[a])

    def test_adl_missing_bus_fails(self):
        a=row(); a['pci_bus']=None
        with self.assertRaises(RuntimeError): match_adl_adapter(a,[adapter()])

    def test_nvml_pci_parse(self):
        self.assertEqual(parse_pci_bus_id(b'00000000:03:00.0'),(0,3,0,0))

    def test_nvml_bad_pci_rejected(self):
        for value in ('x','03:00','0000:03:20.0','0000:03:00.9'):
            with self.subTest(value=value),self.assertRaises(RuntimeError): parse_pci_bus_id(value)

    def test_nvml_card_binding_uses_pci_domain(self):
        entries=[{'pci':(0,3,0,0)},{'pci':(1,3,0,0)}]
        self.assertEqual(matching_nvml_entries(row(domain=1),entries)['pci'],(1,3,0,0))

    def test_nvml_ambiguous_unknown_domain_fails(self):
        entries=[{'pci':(0,3,0,0)},{'pci':(1,3,0,0)}]
        with self.assertRaises(RuntimeError): matching_nvml_entries(row(domain=None),entries)

    def test_nvml_optional_unsupported_is_not_zero(self):
        nv=NVIDIA.__new__(NVIDIA); nv.handle=None; nv.lib=types.SimpleNamespace(test=lambda *a:3)
        self.assertIsNone(nv.optional_uint('test'))

    def test_nvml_lost_gpu_is_error_not_missing_optional_sensor(self):
        nv=NVIDIA.__new__(NVIDIA); nv.handle=None; nv.lib=types.SimpleNamespace(test=lambda *a:15)
        with self.assertRaises(RuntimeError): nv.optional_uint('test')

    def test_kernel_and_device_work_group_limits_enforced(self):
        cl=OpenCL.__new__(OpenCL); cl.capacity=4096
        cl.metadata={'max_work_group':64,'kernel_max_work_group':32,'max_work_item_size_0':64}
        cl.validate_dispatch(1024,32)
        with self.assertRaises(ValueError): cl.validate_dispatch(1024,64)

    def test_small_device_uses_valid_small_group(self):
        cl=OpenCL.__new__(OpenCL); cl.capacity=64
        cl.metadata={'max_work_group':8,'kernel_max_work_group':4,'max_work_item_size_0':8}
        cl.validate_dispatch(16,4)
        with self.assertRaises(ValueError): cl.validate_dispatch(16,8)

    def test_invalid_dispatch_sizes_fail(self):
        cl=OpenCL.__new__(OpenCL); cl.capacity=64; cl.metadata={'max_work_group':32}
        for count,local in ((65,1),(0,1),(16,0),(16,3),(16,-1),(16,True)):
            with self.subTest(count=count,local=local),self.assertRaises(ValueError): cl.validate_dispatch(count,local)

    def test_nvidia_read_never_invents_hotspot(self):
        nv=NVIDIA.__new__(NVIDIA); nv.handle=None; nv.lib=types.SimpleNamespace()
        nv.optional_uint=lambda name,*args: 61 if name=='nvmlDeviceGetTemperature' else (187000 if name=='nvmlDeviceGetPowerUsage' else None)
        reading=nv.read(); self.assertEqual(reading['edge_c'],61); self.assertEqual(reading['board_power_w'],187)
        self.assertIsNone(reading['hotspot_c']); self.assertIsNone(reading['memory_c'])

    def test_required_core_missing_fails(self):
        tel=Telemetry.__new__(Telemetry); tel.device=dict(row(),device_key='selected',vendor='AMD')
        tel.backend=types.SimpleNamespace(read=lambda:{'edge_c':None,'hotspot_c':None})
        with self.assertRaisesRegex(RuntimeError,'core temperature'): tel.read()


if __name__=='__main__': unittest.main(verbosity=2)
