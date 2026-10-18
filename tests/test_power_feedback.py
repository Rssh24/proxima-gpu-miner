"""Repeatable power-controller simulations; no driver or GPU access."""
import copy
import json
import math
from pathlib import Path
import unittest
from bootstrap import MINER, temporary_directory
import power_control as power

SETTINGS = {'batch':131072,'local':32,'power_profiles':{
    'reference_board_power_w':300.,'idle_board_power_w':40.,
    'balanced':{'target_w':150.,'initial_rate':600000.,'batch':32768,'local':128},
    'eco':{'target_w':75.,'initial_rate':180000.,'batch':8192,'local':64}}}


class PowerFeedbackTests(unittest.TestCase):
    def test_sensor_gate_and_uncapped_maximum(self):
        for mode in power.MODES:
            p=power.PowerController(SETTINGS,mode)
            self.assertFalse(p.dispatch_allowed);p.update(0,40.,0)
            self.assertTrue(p.dispatch_allowed)
            self.assertEqual(p.snapshot()['performance_mode'],mode)
            if mode=='maximum':
                p.update(1,350.,1500000)
                self.assertEqual(p.rate,0);self.assertIsNone(p.target)

    def test_invalid_config_and_modes(self):
        changes=[(('batch',),131073),(('local',),48),(('power_profiles',),None),
                 (('power_profiles','reference_board_power_w'),float('inf')),
                 (('power_profiles','reference_board_power_w'),True),
                 (('power_profiles','idle_board_power_w'),301),
                 (('power_profiles','balanced'),[]),
                 (('power_profiles','balanced','target_w'),155),
                 (('power_profiles','eco','target_w'),float('nan')),
                 (('power_profiles','eco','initial_rate'),0),
                 (('power_profiles','eco','initial_rate'),'800000'),
                 (('power_profiles','eco','initial_rate'),False),
                 (('power_profiles','eco','local'),48),
                 (('power_profiles','eco','batch'),8200)]
        invalid=[None,[],{}, {'batch':1,'local':32},{'batch':True,'local':32}]
        for path,value in changes:
            p=copy.deepcopy(SETTINGS);parent=p
            for component in path[:-1]:parent=parent[component]
            parent[path[-1]]=value;invalid.append(p)
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):power.PowerController(value,'balanced')
        for mode in (None,True,0,'50%','10%','low',[],{}):
            with self.subTest(mode=mode),self.assertRaises(ValueError):power.PowerController(SETTINGS,mode)

    def test_saved_mode_schema(self):
        with temporary_directory('power-mode-') as folder:
            path=Path(folder)/'performance.json'
            self.assertEqual(power.load_mode(path),'maximum')
            for mode in power.MODES:
                path.write_text(json.dumps({'mode':mode}))
                self.assertEqual(power.load_mode(path),mode)
                self.assertEqual(power.load_mode(path,'maximum'),'maximum')
            for value in ([],{}, {'mode':'10%'},{'mode':False},
                          {'target_attempts_per_second':800000},
                          {'mode':'balanced','target_attempts_per_second':800000}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):power.load_mode(path)

    def test_over_target_reduces_dispatch_rate(self):
        p=power.PowerController(SETTINGS,'balanced')
        for now in range(31):p.update(float(now),300.,now*600000)
        self.assertLess(p.rate,600000*.6)
        self.assertTrue(p.dispatch_allowed);self.assertFalse(p.unreachable)

    def test_sampler_weighting_stale_and_invalid_samples(self):
        class Flag:
            t=0.;steps=0
            def is_set(self):return self.steps>=40
            def wait(self,duration):self.steps+=1;self.t+=.05;return self.is_set()
        class Sensor:
            closed=False
            def read(self):return {'board_power_w':150.}
            def close(self):self.closed=True
        flag=Flag();sensor=Sensor()
        sampler=power.PowerSampler(flag,telemetry_factory=lambda:sensor,clock=lambda:flag.t)
        sampler._run();sample=sampler.read_window(1.)
        self.assertTrue(sensor.closed);self.assertTrue(sample['healthy'])
        self.assertAlmostEqual(sample['average_w'],150.);self.assertGreaterEqual(sample['sample_count'],19)
        self.assertFalse(sampler.read_window(1.,now=flag.t+.3)['healthy'])
        sampler._record(flag.t,None);self.assertFalse(sampler.read_window(1.)['healthy'])
        for i in range(21):sampler._record(i*.05,100+i*5.)
        sample=sampler.read_window(1.,now=1.)
        self.assertTrue(sample['healthy']);self.assertAlmostEqual(sample['average_w'],150.)

    def test_idle_jobs_do_not_wind_up_or_catch_up(self):
        p=power.PowerController(SETTINGS,'balanced');initial=p.rate
        for now in range(60):p.update(float(now),40.,0)
        self.assertEqual(p.rate,initial)
        self.assertGreater(power.dispatch_deadline(600.,32768,p.rate),600.)
        self.assertEqual(power.dispatch_deadline(600.,32768,0),0)

    def test_converges_to_target_on_linear_power_plant(self):
        for mode in ('balanced','eco'):
            settings=copy.deepcopy(SETTINGS)
            settings['power_profiles'][mode]['initial_rate']=300000. if mode=='balanced' else 400000.
            p=power.PowerController(settings,mode);attempts=0;watts=[]
            for now in range(360):
                value=40+260*min(p.rate/1500000.,1);attempts+=int(p.rate)
                p.update(float(now),value,attempts);watts.append(value)
            mean=sum(watts[-60:])/60
            self.assertGreater(mean,p.target*.88);self.assertLessEqual(mean,p.target)
            self.assertGreater(p.average,p.target*.9);self.assertLessEqual(p.average,p.target)

    def test_noise_and_efficiency_step_do_not_collapse_rate(self):
        for mode in ('balanced','eco'):
            p=power.PowerController(SETTINGS,mode);count=0;watts=[];rates=[]
            for now in range(450):
                coefficient=330. if 150<=now<300 else 260.
                noise=(4. if mode=='balanced' else 2.)*math.sin(now*.73)
                value=40+coefficient*min(p.rate/1500000.,1.)+noise
                count+=int(p.rate);p.update(float(now),value,count)
                watts.append(value);rates.append(p.rate)
            for end in (150,300,450):
                mean=sum(watts[end-60:end])/60
                self.assertGreaterEqual(mean,p.target*.9);self.assertLessEqual(mean,p.target+1)
            self.assertGreaterEqual(min(rates),SETTINGS['power_profiles'][mode]['initial_rate']*.65)

    def test_missing_power_pauses_then_recovers(self):
        p=power.PowerController(SETTINGS,'eco');p.update(0.,40.,0)
        for index,bad in enumerate((None,0,-1,False,'75',float('nan'),float('inf')),1):
            p.update(float(index),bad,0)
            self.assertFalse(p.dispatch_allowed);self.assertIsNone(p.average)
            self.assertEqual(p.snapshot()['target_attempts_per_second'],0)
            self.assertEqual(p.status,'power_sensor_unavailable')
        p.update(8.,40.,0)
        self.assertTrue(p.dispatch_allowed);self.assertEqual(p.status,'calibrating')

    def test_target_below_idle_is_unreachable(self):
        settings=copy.deepcopy(SETTINGS)
        settings['power_profiles']['reference_board_power_w']=150.
        settings['power_profiles']['balanced']['target_w']=75.
        settings['power_profiles']['eco']['target_w']=37.5
        p=power.PowerController(settings,'eco');p.update(0.,40.,0)
        self.assertFalse(p.dispatch_allowed);self.assertTrue(p.unreachable)
        self.assertEqual(p.status,'target_below_idle')


if __name__=='__main__':unittest.main(verbosity=2)
