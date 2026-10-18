"""Pure default-device selection and first-setup CLI tests; no GPU workload."""
import contextlib
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from bootstrap import MINER, SCRATCH, temporary_directory
from device_config import recommended_device_key,select_device
import setup
import telemetry


def gpu(key,vendor=0x1002,shared=False,cu=32,memory=16*1024**3):
    return dict(device_key=key,vendor_id=vendor,host_unified_memory=shared,compute_units=cu,global_memory_bytes=memory,
                name='Mock GPU',vendor='AMD' if vendor==0x1002 else 'NVIDIA',pci_domain=0,pci_bus=3,pci_device=0,pci_function=0)


class AutoDeviceTests(unittest.TestCase):
    def test_discrete_preferred_over_large_integrated_gpu(self):
        self.assertEqual(recommended_device_key([gpu('igpu',shared=True,cu=128,memory=128*1024**3),gpu('discrete',cu=8,memory=4*1024**3)]),'discrete')

    def test_nvidia_auto_without_vendor_selection(self):
        self.assertEqual(recommended_device_key([gpu('nvidia',vendor=0x10de)]),'nvidia')

    def test_amd_auto_without_vendor_selection(self):
        self.assertEqual(recommended_device_key([gpu('amd')]),'amd')

    def test_known_discrete_preferred_over_unknown_memory(self):
        self.assertEqual(recommended_device_key([gpu('unknown',shared=None,cu=200),gpu('discrete',cu=8)]),'discrete')

    def test_unknown_memory_preferred_over_integrated(self):
        self.assertEqual(recommended_device_key([gpu('unknown',shared=None,cu=2),gpu('igpu',shared=True,cu=200)]),'unknown')

    def test_integrated_only_can_be_recommended(self):
        self.assertEqual(recommended_device_key([gpu('igpu',shared=True)]),'igpu')

    def test_multiple_discrete_devices_use_basic_capacity_default(self):
        self.assertEqual(recommended_device_key([gpu('small',cu=8),gpu('large',vendor=0x10de,cu=64)]),'large')

    def test_equal_capacity_has_stable_order(self):
        devices=[gpu('b'),gpu('a')]
        self.assertEqual(recommended_device_key(devices),'a')
        self.assertEqual(recommended_device_key(list(reversed(devices))),'a')

    def test_unknown_vendor_excluded(self):
        self.assertEqual(recommended_device_key([gpu('unsupported',vendor=0x8086,cu=256),gpu('supported',cu=8)]),'supported')

    def test_identity_error_excluded(self):
        broken=gpu('broken',cu=256); broken['identity_error']='ambiguous PCI'
        self.assertEqual(recommended_device_key([broken,gpu('valid',cu=8)]),'valid')

    def test_known_missing_sensor_excluded(self):
        broken=gpu('broken',cu=256); broken['telemetry_error']='No core temperature'
        self.assertEqual(recommended_device_key([broken,gpu('valid',cu=8)]),'valid')

    def test_duplicate_device_key_is_not_automatically_chosen(self):
        with self.assertRaises(RuntimeError): recommended_device_key([gpu('same'),gpu('same')])

    def test_no_supported_devices_fails_clearly(self):
        for devices in ([],[gpu('unknown',vendor=0x8086)]):
            with self.subTest(devices=devices),self.assertRaises(RuntimeError): recommended_device_key(devices)

    def test_explicit_override_still_selects_exact_device(self):
        devices=[gpu('small',cu=8),gpu('large',cu=64)]
        self.assertEqual(select_device(devices,'small')['device_key'],'small')

    def test_cli_does_not_require_vendor_or_device_argument(self):
        with patch.object(sys,'argv',['setup.py']),patch.object(setup,'ensure_data_dirs'),patch.object(setup,'setup') as run:
            setup.main(); run.assert_called_once_with(None)

    def test_cli_explicit_override_is_retained(self):
        with patch.object(sys,'argv',['setup.py','--device','chosen']),patch.object(setup,'ensure_data_dirs'),patch.object(setup,'setup') as run:
            setup.main(); run.assert_called_once_with('chosen')

    def test_cli_inventory_contains_backend_recommendation(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['setup.py','--list-devices']),patch.object(setup,'enumerate_devices',return_value=[gpu('igpu',shared=True),gpu('discrete')]),contextlib.redirect_stdout(output):
            setup.main()
        self.assertEqual(json.loads(output.getvalue())['recommended_device_key'],'discrete')

    def test_cli_inventory_no_devices_returns_reason(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['setup.py','--list-devices']),patch.object(setup,'enumerate_devices',return_value=[]),contextlib.redirect_stdout(output):
            setup.main()
        result=json.loads(output.getvalue()); self.assertIsNone(result['recommended_device_key']); self.assertIn('recommendation_error',result)

    def test_vendor_routes_to_amd_automatically(self):
        device=gpu('amd')
        with patch.object(telemetry,'enumerate_devices',return_value=[device]),patch.object(telemetry,'AMD') as amd,patch.object(telemetry,'NVIDIA') as nvidia:
            sensor=telemetry.Telemetry('amd'); amd.assert_called_once_with(device); nvidia.assert_not_called(); sensor.close()

    def test_vendor_routes_to_nvidia_automatically(self):
        device=gpu('nvidia',vendor=0x10de)
        with patch.object(telemetry,'enumerate_devices',return_value=[device]),patch.object(telemetry,'AMD') as amd,patch.object(telemetry,'NVIDIA') as nvidia:
            sensor=telemetry.Telemetry('nvidia'); nvidia.assert_called_once_with(device); amd.assert_not_called(); sensor.close()


if __name__=='__main__': unittest.main(verbosity=2)
