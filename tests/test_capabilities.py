import json,sys,unittest
from pathlib import Path
from bootstrap import MINER, SCRATCH, temporary_directory
from thermal_control import ThermalGuard,validate_temperatures
from power_control import PowerController
class CapabilityTests(unittest.TestCase):
    def profile(self,power=False):
        p={'batch':1024,'local':16,'attempts_per_second':100000,'power_available':power,'modes':{'maximum':{'enabled':True},'balanced':{'enabled':power,'reason':'Power unavailable'},'eco':{'enabled':power,'reason':'Power unavailable'}}}
        if power:p['power_profiles']={'reference_board_power_w':300,'idle_board_power_w':40,'balanced':{'target_w':150,'initial_rate':40000,'batch':1024,'local':16},'eco':{'target_w':75,'initial_rate':10000,'batch':1024,'local':16}}
        return p
    def test_no_power_maximum_no_fake_reading(self):
        p=PowerController(self.profile(),'maximum');p.update(1,None,1024)
        self.assertTrue(p.dispatch_allowed);self.assertIsNone(p.reference);self.assertIsNone(p.average);self.assertIsNone(p.target)
    def test_no_power_limited_disabled(self):
        for mode in ('balanced','eco'):
            with self.assertRaises(ValueError):PowerController(self.profile(),mode)
    def test_no_power_thermal_stops_explicitly(self):
        with self.assertRaisesRegex(RuntimeError,'automatic power limiting is unavailable'):PowerController(self.profile(),'maximum').apply_thermal_limit()
    def test_no_hotspot_core_timer_exact(self):
        guard=ThermalGuard(require_hotspot=False)
        for t in range(60):self.assertFalse(guard.update(t,75,None)['thermal_limited'])
        self.assertTrue(guard.update(60,75,None)['thermal_limited'])
        self.assertEqual(guard.snapshot()['thermal_sensor'],'core')
    def test_no_hotspot_fallback_gap_resets(self):
        guard=ThermalGuard(require_hotspot=False)
        for t in range(50):guard.update(t,75,None)
        self.assertEqual(guard.update(55,75,None)['thermal_hot_seconds'],0)
        self.assertEqual(guard.update(56,74,None)['thermal_hot_seconds'],0)
    def test_required_sensor_loss_stops(self):
        for core,hot,required in ((None,None,False),(50,None,True),(50,float('nan'),False),(80,None,False),(50,105,False)):
            with self.assertRaises(RuntimeError):validate_temperatures(core,hot,require_hotspot=required)
    def test_existing_lower_power_never_raised(self):
        for mode in ('balanced','eco'):
            p=PowerController(self.profile(True),mode);before=p.target;p.apply_thermal_limit();self.assertEqual(p.target,before)
    def test_maximum_cap_uses_real_reference(self):
        p=PowerController(self.profile(True),'maximum');p.apply_thermal_limit();self.assertEqual(p.target,285)
if __name__=='__main__':unittest.main()
