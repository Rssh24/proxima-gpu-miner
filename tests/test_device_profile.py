"""Pure profile validation checks; no GPU work or wallet access."""
import copy
from pathlib import Path
import sys
import unittest
from bootstrap import MINER, SCRATCH, temporary_directory
from device_profile import device_fingerprint,validate_profile

HASH='1'*64


def fixtures(power=True):
    device=dict(device_key='pci:1002:unknown:03:00.0',name='AMD Test GPU',opencl_name='gfx-test',
                vendor='AMD',vendor_id=0x1002,driver='test-driver-1',version='OpenCL 2.0',
                global_memory_bytes=8*1024**3,compute_units=32,max_work_group=256,
                max_work_item_size_0=1024,pci_domain=None,pci_bus=3,pci_device=0,pci_function=0)
    profile=dict(device_key=device['device_key'],device_name=device['name'],vendor=device['vendor'],
                 driver=device['driver'],kernel_sha256=HASH,fingerprint=device_fingerprint(device,HASH),
                 self_test={'passed':True},sensor_capabilities=dict(core_temperature=True,
                 hotspot_temperature=power,board_power=power),power_available=power,
                 batch=32768,local=32,attempts_per_second=1000000,
                 modes={'maximum':{'enabled':True},'balanced':{'enabled':power,'reason':'' if power else 'No power sensor'},
                        'eco':{'enabled':power,'reason':'' if power else 'No power sensor'}},power_profiles=None)
    if power:
        profile['power_profiles']={'reference_board_power_w':300,'idle_board_power_w':40,
                                  'balanced':dict(target_w=150,initial_rate=500000,batch=32768,local=32),
                                  'eco':dict(target_w=75,initial_rate=250000,batch=32768,local=32)}
    return device,profile


class ProfileTests(unittest.TestCase):
    def check(self,device,profile): return validate_profile(profile,[device],HASH)

    def test_valid_power_profile(self):
        device,profile=fixtures(); before=copy.deepcopy(profile)
        self.assertIs(self.check(device,profile),profile); self.assertEqual(profile,before)

    def test_setup_device_name_contract_does_not_require_name(self):
        device,profile=fixtures(); self.assertNotIn('name',profile)
        self.assertEqual(profile['device_name'],device['name']); self.check(device,profile)

    def test_device_name_mismatch_rejected(self):
        device,profile=fixtures(); profile['device_name']='Wrong GPU'
        with self.assertRaisesRegex(RuntimeError,'device_name'): self.check(device,profile)

    def test_runtime_batch_boundaries(self):
        for batch in (64,131072):
            device,profile=fixtures(False); profile['batch']=batch
            with self.subTest(batch=batch): self.check(device,profile)
        for batch in (1,32,63,131073,262144):
            device,profile=fixtures(False); profile['batch']=batch
            with self.subTest(batch=batch),self.assertRaises(RuntimeError): self.check(device,profile)

    def test_runtime_local_whitelist(self):
        for local in (1,2,4,8,16,32,64,128,256):
            device,profile=fixtures(False); profile['local']=local
            with self.subTest(local=local): self.check(device,profile)
        device,profile=fixtures(False); device['max_work_group']=1024
        profile['fingerprint']=device_fingerprint(device,HASH); profile['local']=512
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_valid_without_power_has_maximum_only(self):
        device,profile=fixtures(False); self.check(device,profile)

    def test_driver_change_rejected(self):
        device,profile=fixtures(); device['driver']='new-driver'
        with self.assertRaisesRegex(RuntimeError,'driver changed'): self.check(device,profile)

    def test_kernel_change_rejected(self):
        device,profile=fixtures()
        with self.assertRaisesRegex(RuntimeError,'kernel changed'): validate_profile(profile,[device],'2'*64)

    def test_missing_device_rejected(self):
        _,profile=fixtures()
        with self.assertRaisesRegex(RuntimeError,'missing'): validate_profile(profile,[],HASH)

    def test_ambiguous_device_rejected(self):
        device,profile=fixtures()
        with self.assertRaisesRegex(RuntimeError,'ambiguous'): validate_profile(profile,[device,device],HASH)

    def test_driver_metadata_cannot_hide_behind_fingerprint(self):
        device,profile=fixtures(); profile['driver']='false'
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_name_not_used_as_device_fallback(self):
        device,profile=fixtures(); device['device_key']='different'
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_test_passed_must_be_true_boolean(self):
        for bad in (False,1,'true',None):
            device,profile=fixtures(); profile['self_test']['passed']=bad
            with self.subTest(bad=bad),self.assertRaises(RuntimeError): self.check(device,profile)

    def test_core_temperature_required(self):
        device,profile=fixtures(); profile['sensor_capabilities']['core_temperature']=False
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_hotspot_absence_is_explicit_and_valid(self):
        device,profile=fixtures(); profile['sensor_capabilities']['hotspot_temperature']=False
        self.check(device,profile)

    def test_capability_boolean_strict(self):
        for key in ('hotspot_temperature','board_power'):
            device,profile=fixtures(); profile['sensor_capabilities'][key]=1
            with self.subTest(key=key),self.assertRaises(RuntimeError): self.check(device,profile)

    def test_power_availability_must_match_sensor(self):
        device,profile=fixtures(); profile['power_available']=False
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_no_power_sensor_cannot_enable_eco(self):
        device,profile=fixtures(False); profile['modes']['eco']['enabled']=True
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_no_power_sensor_cannot_claim_power_profile(self):
        device,profile=fixtures(False); profile['power_profiles']={}
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_disabled_modes_need_reason(self):
        device,profile=fixtures(); profile['modes']['eco']={'enabled':False}
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_unreachable_eco_disabled_is_valid(self):
        device,profile=fixtures(); profile['power_profiles']['idle_board_power_w']=90
        profile['modes']['eco']={'enabled':False,'reason':'Below idle power'}
        self.check(device,profile)

    def test_unreachable_eco_enabled_is_rejected(self):
        device,profile=fixtures(); profile['power_profiles']['idle_board_power_w']=90
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_power_fraction_must_match(self):
        device,profile=fixtures(); profile['power_profiles']['balanced']['target_w']=180
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_optional_power_alias_must_agree(self):
        device,profile=fixtures(); profile['reference_max_board_w']=310
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_power_reference_must_be_above_idle(self):
        device,profile=fixtures(); profile['power_profiles']['idle_board_power_w']=400
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_nonfinite_rate_rejected(self):
        device,profile=fixtures(); profile['attempts_per_second']=float('nan')
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_small_workgroup_profile_supported(self):
        device,profile=fixtures(False); device['max_work_group']=4
        profile['fingerprint']=device_fingerprint(device,HASH); profile['local']=4
        self.check(device,profile)

    def test_device_workgroup_limit_enforced(self):
        device,profile=fixtures(); profile['local']=512
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_power_profile_dispatch_limit_enforced(self):
        device,profile=fixtures(); profile['power_profiles']['eco']['local']=512
        with self.assertRaises(RuntimeError): self.check(device,profile)

    def test_fingerprint_excludes_transient_enumeration(self):
        device,profile=fixtures(); device['_registration']=(9,1); device['registrations']=4
        self.assertEqual(device_fingerprint(device,HASH),profile['fingerprint'])

    def test_bad_sha_rejected(self):
        device,profile=fixtures(); profile['fingerprint']='bad'
        with self.assertRaises(RuntimeError): self.check(device,profile)


if __name__=='__main__': unittest.main(verbosity=2)
