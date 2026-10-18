"""Session-latched software thermal protection; never changes driver settings."""
import math

GPU_EMERGENCY_C = 80.0
HOTSPOT_EMERGENCY_C = 105.0
HOTSPOT_TRIGGER_C = 95.0
HOTSPOT_HOLD_SECONDS = 60.0
THERMAL_POWER_FRACTION = .95


def _finite(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def validate_temperatures(edge_c, hotspot_c, edge_limit_c=GPU_EMERGENCY_C, require_hotspot=True):
    """Independent hard-stop checks shared by seeker and supervisor."""
    if not _finite(edge_limit_c) or not 1 <= edge_limit_c <= GPU_EMERGENCY_C:
        raise ValueError('Invalid GPU emergency temperature')
    if not _finite(edge_c) or (require_hotspot and not _finite(hotspot_c)) or (hotspot_c is not None and not _finite(hotspot_c)):
        raise RuntimeError('Required temperature telemetry unavailable')
    if edge_c >= edge_limit_c:
        raise RuntimeError('GPU edge emergency temperature reached')
    if hotspot_c is not None and hotspot_c >= HOTSPOT_EMERGENCY_C:
        raise RuntimeError('GPU hotspot emergency temperature reached')


class ThermalGuard:
    """Require continuously hot observations, then latch until a new session.

    A gap longer than max_sample_gap_seconds restarts the timer; unobserved
    time must not count as a continuous high-temperature interval.
    """
    def __init__(self, trigger_c=HOTSPOT_TRIGGER_C, hold_seconds=HOTSPOT_HOLD_SECONDS,
                 max_sample_gap_seconds=3.0, edge_limit_c=GPU_EMERGENCY_C, require_hotspot=True):
        if not _finite(trigger_c) or not 1 <= trigger_c <= HOTSPOT_TRIGGER_C:
            raise ValueError('Invalid GPU hotspot reduction trigger')
        if not _finite(hold_seconds) or hold_seconds <= 0:
            raise ValueError('Invalid GPU hotspot hold time')
        if not _finite(max_sample_gap_seconds) or max_sample_gap_seconds <= 0:
            raise ValueError('Invalid GPU temperature sampling gap')
        if not _finite(edge_limit_c) or not 1 <= edge_limit_c <= GPU_EMERGENCY_C:
            raise ValueError('Invalid GPU emergency temperature')
        self.require_hotspot=bool(require_hotspot)
        self.trigger_c = float(trigger_c) if require_hotspot else 75.0
        self.hold_seconds = float(hold_seconds)
        self.max_sample_gap_seconds = float(max_sample_gap_seconds)
        self.edge_limit_c = float(edge_limit_c)
        self.last_observation = None
        self.hot_since = None
        self.hot_seconds = 0.0
        self.limited = False

    def update(self, now, edge_c, hotspot_c):
        if not _finite(now) or now < 0:
            raise ValueError('Invalid GPU temperature sample time')
        if self.last_observation is not None and now < self.last_observation:
            raise ValueError('GPU temperature sample time moved backwards')
        validate_temperatures(edge_c, hotspot_c, self.edge_limit_c, self.require_hotspot)
        gap = (self.last_observation is not None and
               now - self.last_observation > self.max_sample_gap_seconds)
        self.last_observation = float(now)
        monitored = hotspot_c if self.require_hotspot else edge_c
        if monitored < self.trigger_c:
            self.hot_since = None
            self.hot_seconds = 0.0
        else:
            if self.hot_since is None or gap:
                self.hot_since = float(now)
            self.hot_seconds = float(now) - self.hot_since
            if self.hot_seconds >= self.hold_seconds:
                self.limited = True
        return self.snapshot()

    def snapshot(self):
        return {'thermal_limited': self.limited,
                'thermal_sensor': 'hotspot' if self.require_hotspot else 'core',
                'thermal_hot_seconds': self.hot_seconds,
                'thermal_power_fraction': THERMAL_POWER_FRACTION if self.limited else None}
