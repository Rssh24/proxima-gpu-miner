"""Deterministic thermal and power-cap policy tests; no GPU workload."""
import unittest
from bootstrap import MINER
import thermal_control as thermal
import power_control as power_module

def settings():
    return {'batch': 131072, 'local': 32, 'attempts_per_second': 2_000_000,
            'power_profiles': {'reference_board_power_w': 300, 'idle_board_power_w': 40,
                               'balanced': {'target_w': 150, 'initial_rate': 1_180_000, 'batch': 131072, 'local': 32},
                               'eco': {'target_w': 75, 'initial_rate': 490_000, 'batch': 131072, 'local': 32}}}


class ThermalTests(unittest.TestCase):
    def test_exact_continuous_boundary(self):
        guard = thermal.ThermalGuard()
        for second in range(60):
            state = guard.update(second, 50, 95)
            self.assertFalse(state['thermal_limited'])
        state = guard.update(60, 50, 95)
        self.assertTrue(state['thermal_limited'])
        self.assertEqual(state['thermal_hot_seconds'], 60)
        self.assertEqual(state['thermal_power_fraction'], .95)

    def test_subthreshold_resets_all_elapsed_time(self):
        guard = thermal.ThermalGuard()
        for second in range(59):
            guard.update(second, 50, 96)
        self.assertEqual(guard.update(59, 50, 94.999)['thermal_hot_seconds'], 0)
        for second in range(60, 120):
            self.assertFalse(guard.update(second, 50, 95)['thermal_limited'])
        self.assertTrue(guard.update(120, 50, 95)['thermal_limited'])

    def test_sample_gap_does_not_count_unknown_time(self):
        guard = thermal.ThermalGuard()
        for second in range(59):
            guard.update(second, 50, 100)
        state = guard.update(65, 50, 100)
        self.assertFalse(state['thermal_limited'])
        self.assertEqual(state['thermal_hot_seconds'], 0)
        for second in range(66, 125):
            self.assertFalse(guard.update(second, 50, 100)['thermal_limited'])
        self.assertTrue(guard.update(125, 50, 100)['thermal_limited'])

    def test_exact_sample_gap_boundary(self):
        guard = thermal.ThermalGuard()
        for second in range(0, 60, 3):
            self.assertFalse(guard.update(second, 50, 95)['thermal_limited'])
        self.assertTrue(guard.update(60, 50, 95)['thermal_limited'])

    def test_latch_survives_cooling_until_new_guard(self):
        guard = thermal.ThermalGuard()
        for second in range(61):
            guard.update(second, 50, 95)
        state = guard.update(61, 50, 50)
        self.assertTrue(state['thermal_limited'])
        self.assertEqual(state['thermal_hot_seconds'], 0)
        self.assertFalse(thermal.ThermalGuard().update(62, 50, 50)['thermal_limited'])

    def test_emergency_boundaries_and_missing_nonfinite_sensors(self):
        thermal.validate_temperatures(79.999, 104.999)
        for edge, hotspot in [(80, 95), (50, 105), (81, 106)]:
            with self.subTest(edge=edge, hotspot=hotspot), self.assertRaises(RuntimeError):
                thermal.ThermalGuard().update(0, edge, hotspot)
        for value in [None, float('nan'), float('inf'), -float('inf'), True, '95']:
            for edge, hotspot in [(value, 95), (50, value)]:
                with self.subTest(edge=edge, hotspot=hotspot), self.assertRaises(RuntimeError):
                    thermal.ThermalGuard().update(0, edge, hotspot)

    def test_clock_must_be_monotonic_and_finite(self):
        guard = thermal.ThermalGuard()
        guard.update(10, 50, 95)
        self.assertEqual(guard.update(10, 50, 95)['thermal_hot_seconds'], 0)
        for value in [9, None, float('nan'), float('inf'), -1, True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                guard.update(value, 50, 95)

    def test_trigger_cannot_disable_fixed_emergency_limit(self):
        for kwargs in [{'trigger_c': 96}, {'trigger_c': 105}, {'edge_limit_c': 81},
                       {'hold_seconds': 0}, {'max_sample_gap_seconds': 0},
                       {'trigger_c': float('nan')}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                thermal.ThermalGuard(**kwargs)
        guard = thermal.ThermalGuard(trigger_c=90, edge_limit_c=70)
        self.assertEqual(guard.update(0, 50, 90)['thermal_hot_seconds'], 0)
        with self.assertRaises(RuntimeError):
            guard.update(1, 70, 90)
        with self.assertRaises(RuntimeError):
            guard.update(1, 50, 105)


class PowerTests(unittest.TestCase):
    def test_maximum_becomes_95_percent_average_power_budget(self):
        controller = power_module.PowerController(settings(), 'maximum')
        for second in range(61):
            controller.update(second, 310, second * 2_000_000)
        controller.apply_thermal_limit()
        self.assertEqual(controller.target, 285)
        self.assertEqual(controller.mode, 'maximum')
        self.assertAlmostEqual(controller.rate, 2_000_000 * 245 / 270)
        self.assertTrue(controller.dispatch_allowed)
        initial_rate = controller.rate
        for second in range(61, 67):
            controller.update(second, 310, second * 2_000_000)
        self.assertLess(controller.rate, initial_rate)
        self.assertEqual(controller.snapshot()['power_status'], 'tracking')

    def test_existing_modes_never_raised_or_reset(self):
        for mode in ['balanced', 'eco']:
            controller = power_module.PowerController(settings(), mode)
            for second in range(14):
                controller.update(second, controller.target, int(second * controller.rate))
            original = (controller.target, controller.rate, controller.hold_until,
                        controller.last_control, controller.max_rate, controller.min_rate)
            controller.apply_thermal_limit()
            controller.apply_thermal_limit()
            self.assertEqual(original, (controller.target, controller.rate, controller.hold_until,
                                       controller.last_control, controller.max_rate, controller.min_rate))

    def test_cold_maximum_uses_calibration_and_does_not_bypass_sensor_gate(self):
        controller = power_module.PowerController(settings(), 'maximum')
        controller.apply_thermal_limit()
        self.assertEqual(controller.target, 285)
        self.assertLess(controller.rate, 2_000_000)
        self.assertFalse(controller.dispatch_allowed)
        self.assertEqual(controller.snapshot()['target_attempts_per_second'], 0)
        controller.update(10, None, 0)
        self.assertFalse(controller.dispatch_allowed)
        self.assertEqual(controller.target, 285)
        controller.update(11, 280, 0)
        self.assertTrue(controller.dispatch_allowed)
        self.assertEqual(controller.hold_until, 23)

    def test_thermal_application_is_idempotent_even_after_feedback(self):
        controller = power_module.PowerController(settings(), 'maximum')
        for second in range(61):
            controller.update(second, 310, second * 2_000_000)
        controller.apply_thermal_limit()
        controller.update(64, 320, 128_000_000)
        state = (controller.target, controller.rate, controller.last_control, controller.hold_until)
        for _ in range(20):
            controller.apply_thermal_limit()
        self.assertEqual(state, (controller.target, controller.rate, controller.last_control, controller.hold_until))

    def test_recent_rate_preferred_and_initial_rate_never_increased(self):
        controller = power_module.PowerController(settings(), 'maximum')
        for second in range(61):
            controller.update(second, 200, second * 1_000_000)
        controller.apply_thermal_limit()
        self.assertEqual(controller.rate, 950_000)

    def test_power_target_below_idle_pauses_without_hardware_writes(self):
        controller = power_module.PowerController(settings(), 'maximum')
        controller.update(0, 300, 0)
        controller.apply_thermal_limit(.1)
        self.assertTrue(controller.unreachable)
        self.assertFalse(controller.dispatch_allowed)

    def test_invalid_fractions_cannot_remove_cap(self):
        controller = power_module.PowerController(settings(), 'maximum')
        for fraction in [1, 1.1, 0, -.1, float('nan'), None, True]:
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                controller.apply_thermal_limit(fraction)



if __name__=='__main__': unittest.main(verbosity=2)
