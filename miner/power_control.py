"""Software-only board-power feedback. No GPU/driver or wallet access."""
import json
import math
import random
import threading
import time
from collections import deque

MODES = ('maximum', 'balanced', 'eco')


class PowerSampler:
    """Own-context ADL sampling independent of dispatch/sleep phase.

    Call start(), then read_window(1.0) once a second. Stop the supplied event
    and join() on cleanup. Neither this thread nor this module computes VRFs.
    """
    def __init__(self, stop_event, telemetry_factory=None, clock=time.monotonic):
        self.stop_event = stop_event
        self.factory = telemetry_factory
        self.clock = clock
        self.lock = threading.Lock()
        self.samples = deque(maxlen=2048)
        self.failed = True
        self.thread = threading.Thread(target=self._run, daemon=True, name='board-power-sampler')

    def start(self):
        self.thread.start()

    def join(self, timeout=2):
        self.thread.join(timeout)
        return not self.thread.is_alive()

    def _record(self, now, value):
        valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                 and math.isfinite(value) and value > 0)
        with self.lock:
            if not valid:
                self.failed = True
                self.samples.clear()
            else:
                if self.failed:
                    self.samples.clear()
                self.failed = False
                self.samples.append((now, float(value)))

    def _run(self):
        telemetry = None
        rng = random.Random()
        try:
            if self.factory is None:
                from telemetry import Telemetry
                telemetry = Telemetry()
            else:
                telemetry = self.factory()
            while not self.stop_event.is_set():
                try:
                    reading = telemetry.read()
                    self._record(self.clock(), reading.get('board_power_w'))
                except Exception:
                    self._record(self.clock(), None)
                self.stop_event.wait(rng.uniform(.035, .065))
        except Exception:
            self._record(self.clock(), None)
        finally:
            if telemetry is not None:
                try:
                    telemetry.close()
                except Exception:
                    pass

    def read_window(self, seconds=1.0, now=None):
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not .5 <= seconds <= 30:
            raise ValueError('Invalid power sampling window')
        now = self.clock() if now is None else now
        with self.lock:
            points = list(self.samples)
            failed = self.failed
        result = {'average_w': None, 'healthy': False, 'sample_count': 0,
                  'duration_seconds': 0.0, 'latest_age_seconds': None}
        if failed or len(points) < 2:
            return result
        age = now - points[-1][0]
        result['latest_age_seconds'] = age
        if age < 0 or age > .25:
            return result
        cutoff = now - seconds
        index = 0
        while index + 1 < len(points) and points[index + 1][0] <= cutoff:
            index += 1
        points = points[index:]
        if len(points) > 1 and points[0][0] < cutoff:
            ta, pa = points[0]
            tb, pb = points[1]
            points[0] = (cutoff, pa + (pb - pa) * (cutoff - ta) / (tb - ta))
        duration = now - points[0][0]
        result['sample_count'] = len(points)
        result['duration_seconds'] = duration
        if duration < seconds * .8 or len(points) < 8:
            return result
        # Extend only a recent sample to the query instant (at most250ms).
        if age > 0:
            points.append((now, points[-1][1]))
        energy = sum((tb - ta) * (pa + pb) * .5
                     for (ta, pa), (tb, pb) in zip(points, points[1:]))
        result['average_w'] = energy / duration
        result['healthy'] = True
        return result


def _number(value, name, positive=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Invalid power profile: ' + name)
    if value < 0 or (positive and value == 0):
        raise ValueError('Invalid power profile: ' + name)
    return float(value)


def _dispatch_settings(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid GPU dispatch profile')
    batch, local = value.get('batch'), value.get('local')
    if type(batch) is not int or type(local) is not int:
        raise ValueError('Invalid GPU dispatch profile')
    if not 64 <= batch <= 131072 or local not in (1, 2, 4, 8, 16, 32, 64, 128, 256) or batch % local:
        raise ValueError('Invalid GPU dispatch profile')
    return batch, local


def load_mode(path, explicit=None):
    if explicit is None:
        if path.exists():
            document = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(document, dict) or set(document) != {'mode'}:
                raise ValueError('Performance configuration must contain only mode')
            value = document['mode']
        else:
            value = 'maximum'
    else:
        value = explicit
    if not isinstance(value, str) or value not in MODES:
        raise ValueError('Performance mode must be maximum, balanced, or eco')
    return value


def dispatch_deadline(started, batch, rate):
    # Anchor each batch to its actual start; idle periods never accumulate credit.
    return started + batch / rate if rate else 0


class PowerController:
    """Fast five-second feedback and separate twenty-second UI average.

    The target is an average board-power budget, not an instantaneous peak cap.
    Missing power data pauses dispatch; this module never changes hardware.
    """
    WINDOW_SECONDS = 20.0
    FAST_WINDOW_SECONDS = 5.0
    CONTROL_SECONDS = 3.0
    MIN_OBSERVATION_SECONDS = 12.0

    def __init__(self, settings, mode):
        if mode not in MODES:
            raise ValueError('Invalid performance mode')
        batch, local = _dispatch_settings(settings)
        self.power_available = settings.get('power_available', True)
        if type(self.power_available) is not bool:
            raise ValueError('Invalid power sensor capability')
        requested = settings.get('modes', {}).get(mode, {'enabled': True})
        if requested.get('enabled') is not True:
            raise ValueError(requested.get('reason', 'This power mode is unavailable on the selected GPU'))
        self.mode = mode
        self.reference = None
        self.reference_rate = settings.get('attempts_per_second')
        self.idle = 0.0
        self.target = None
        self.rate = 0.0
        self.batch, self.local = batch, local
        self.max_rate = 0.0
        self.min_rate = 0.0
        if self.power_available:
            profiles = settings.get('power_profiles')
            if not isinstance(profiles, dict):
                raise ValueError('Validated power profiles are required')
            self.reference = _number(profiles.get('reference_board_power_w'), 'reference watts')
            self.idle = _number(profiles.get('idle_board_power_w'), 'idle watts')
            if self.idle >= self.reference:
                raise ValueError('Idle power must be below the measured reference power')
            validated = {}
            for name, fraction in (('balanced', .5), ('eco', .25)):
                profile = profiles.get(name)
                pb, pl = _dispatch_settings(profile)
                target = _number(profile.get('target_w'), name+' target watts')
                rate = _number(profile.get('initial_rate'), name+' initial rate')
                if abs(target-self.reference*fraction) > max(.05,self.reference*1e-6):
                    raise ValueError('Power target does not match the measured reference')
                validated[name] = (target,rate,pb,pl)
            if mode != 'maximum':
                self.target,self.rate,self.batch,self.local=validated[mode]
                self.max_rate=self.rate*8
                self.min_rate=max(1.0,self.rate/128)
        elif mode != 'maximum':
            raise ValueError('Board-power telemetry is required for a limited-power mode')
        self.samples = deque()
        self.fast_samples = deque()
        self.work_samples = deque()
        self.average = None
        self.fast_average = None
        self.utilization = 0.0
        self.hold_until = None
        self.last_control = None
        self.last_attempts = 0
        self.last_observation = None
        self.sensor_valid = False
        self.unreachable = self.target is not None and self.target <= self.idle + 1.0
        self.status = 'target_below_idle' if self.unreachable else 'waiting_for_power_sensor'

    def apply_thermal_limit(self, fraction=.95):
        """Lower the session's average-power budget without changing its mode.

        Existing 50%/25% budgets and pacing are never raised or reset. A newly
        capped maximum mode starts conservatively from recent completed work,
        falling back to the validated calibration only when no work is recent.
        """
        if not self.power_available:
            raise RuntimeError('Sustained high temperature: automatic power limiting is unavailable on this GPU; mining stopped')
        fraction = _number(fraction, 'thermal power fraction')
        if fraction > .95:
            raise ValueError('Thermal power fraction cannot exceed 95 percent')
        cap = self.reference * fraction
        if self.target is not None and self.target <= cap:
            return
        if self.target is not None:
            self.rate = max(self.min_rate, self.rate * cap / self.target)
            self.target = cap
        else:
            measured_rate = 0.0
            if len(self.work_samples) >= 2:
                duration = self.work_samples[-1][0] - self.work_samples[0][0]
                if duration > 0:
                    measured_rate = (self.work_samples[-1][1] - self.work_samples[0][1]) / duration
            baseline = (measured_rate if measured_rate > 0 else
                        _number(self.reference_rate, 'calibrated attempts per second'))
            observed_power = self.fast_average if self.fast_average is not None else self.reference
            # Account for the idle floor and take no initial rate increase,
            # even when recent workload has not reached the reference power.
            ratio = min(fraction, max(.01, (cap - self.idle) / max(1.0, observed_power - self.idle)))
            self.rate = max(1.0, baseline * ratio)
            self.max_rate = baseline * 1.10
            self.min_rate = max(1.0, self.rate / 128.0)
            self.target = cap
        self.unreachable = self.target <= self.idle + 1.0
        # Existing maximum-mode observations already provide a warm history.
        # A cold controller still performs its normal sensor warm-up.
        if self.sensor_valid and self.last_observation is not None:
            self.hold_until = self.last_observation
            self.last_control = self.last_observation
        self.status = ('target_below_idle' if self.unreachable else
                       'tracking' if self.sensor_valid else 'waiting_for_power_sensor')

    @property
    def dispatch_allowed(self):
        return (not self.power_available or self.sensor_valid) and not self.unreachable

    @staticmethod
    def _append_window(samples, now, value, seconds):
        if samples and now <= samples[-1][0]:
            samples[-1] = (now, value)
        else:
            samples.append((now, value))
        cutoff = now - seconds
        while len(samples) > 1 and samples[1][0] <= cutoff:
            samples.popleft()
        if len(samples) > 1 and samples[0][0] < cutoff:
            ta, pa = samples[0]
            tb, pb = samples[1]
            samples[0] = (cutoff, pa + (pb - pa) * (cutoff - ta) / (tb - ta))

    @staticmethod
    def _average(samples, now):
        duration = now - samples[0][0]
        if duration <= 0:
            return samples[-1][1], 0.0
        points = list(samples)
        energy = sum((tb - ta) * (pa + pb) * .5
                     for (ta, pa), (tb, pb) in zip(points, points[1:]))
        return energy / duration, duration

    def update(self, now, board_power_w, completed_attempts):
        _number(now, 'sample time', positive=False)
        if not self.power_available:
            self.status='maximum_power_unavailable'
            self.average=None
            return
        valid = (not isinstance(board_power_w, bool)
                 and isinstance(board_power_w, (int, float))
                 and math.isfinite(board_power_w) and board_power_w > 0)
        if type(completed_attempts) is not int or completed_attempts < 0:
            raise ValueError('Invalid completed-attempt count')
        if self.last_observation is not None and now < self.last_observation:
            raise ValueError('Power sample time moved backwards')
        if completed_attempts < self.last_attempts:
            raise ValueError('Completed-attempt count moved backwards')
        gap = self.last_observation is not None and now - self.last_observation > 5
        self.last_attempts = completed_attempts
        self.last_observation = now
        if not valid:
            self.sensor_valid = False
            self.average = None
            self.fast_average = None
            self.samples.clear()
            self.fast_samples.clear()
            self.work_samples.clear()
            self.last_control = now
            self.status = 'power_sensor_unavailable'
            return
        if gap or not self.sensor_valid:
            self.samples.clear()
            self.fast_samples.clear()
            self.work_samples.clear()
            self.last_control = now
            self.hold_until = now + self.MIN_OBSERVATION_SECONDS
        self.sensor_valid = True
        self._append_window(self.samples, now, float(board_power_w), self.WINDOW_SECONDS)
        self._append_window(self.fast_samples, now, float(board_power_w), self.FAST_WINDOW_SECONDS)
        self._append_window(self.work_samples, now, completed_attempts, self.FAST_WINDOW_SECONDS)
        self.average, duration = self._average(self.samples, now)
        self.fast_average, _ = self._average(self.fast_samples, now)
        work_duration = now - self.work_samples[0][0]
        measured_rate = ((completed_attempts - self.work_samples[0][1]) / work_duration
                         if work_duration > 0 else 0)
        self.utilization = measured_rate / self.rate if self.rate else 1.0
        if self.unreachable:
            self.status = 'target_below_idle'
            return
        if self.target is None:
            self.status = 'maximum'
            return
        self.status = 'tracking' if now >= self.hold_until else 'calibrating'
        if now < self.hold_until or now - self.last_control < self.CONTROL_SECONDS:
            return
        self.last_control = now
        # Keep margin for sensor quantization and timing jitter. A cold/no-job
        # interval cannot increase the rate before useful work has resumed.
        # Low-duty eco pulses make a one-to-two-watt sampling error material.
        # Reserve three watts there; retain the already-validated balanced rule.
        margin = max(3.0 if self.mode == 'eco' else 1.5, self.target * .02)
        effective = self.target - margin
        deadband = max(1.0, self.target * .01)
        target_dynamic = max(1.0, effective - self.idle)
        measured_dynamic = max(1.0, self.fast_average - self.idle)
        # Do not repeatedly reduce against old high-power history once the
        # most recent full-second measurement has already fallen below target.
        if self.fast_average > effective + deadband and board_power_w > effective + deadband:
            factor = max(.9, min(.995, (target_dynamic / measured_dynamic) ** .35))
            self.rate = max(self.min_rate, self.rate * factor)
        elif self.utilization >= .85 and self.fast_average < effective - deadband:
            factor = min(1.04, max(1.005, (target_dynamic / measured_dynamic) ** .35))
            self.rate = min(self.max_rate, self.rate * factor)

    def snapshot(self):
        return {'performance_mode': self.mode, 'power_target_w': self.target,
                'power_average_w': self.average,
                'power_fast_average_w': self.fast_average,
                'power_rate_utilization': self.utilization,
                'target_attempts_per_second': self.rate if self.dispatch_allowed else 0.0,
                'power_target_unreachable': self.unreachable,
                'power_dispatch_paused': not self.dispatch_allowed,
                'power_status': self.status}
