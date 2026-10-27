"""
Motion helpers (no pygame): GSAP-style easing + tweens, and a Lenis-style inertial smooth scroll.

    Tween(0, 1, 0.5, "back.out", delay=0.1)     value goes 0 -> 1 with an overshoot
    hover = Tween(0, 0, 0.2);  hover.to(1)       retarget smoothly (used for hover pops)
    scroll = SmoothScroll();  scroll.wheel(90)   wheel adds to a target, the page glides after it
"""
import math


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _power_out(p):
    return lambda t: 1 - (1 - t) ** p


def _power_in(p):
    return lambda t: t ** p


def _power_inout(p):
    return lambda t: (t ** p) * 2 ** (p - 1) if t < 0.5 else 1 - ((1 - t) ** p) * 2 ** (p - 1)


def back_out(t, s=1.70158):
    t -= 1
    return t * t * ((s + 1) * t + s) + 1


def elastic_out(t, amp=1.0, period=0.4):
    if t <= 0 or t >= 1:
        return clamp(t)
    s = period / (2 * math.pi) * math.asin(1 / amp)
    return amp * 2 ** (-10 * t) * math.sin((t - s) * 2 * math.pi / period) + 1


def expo_out(t):
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


EASES = {
    "linear": lambda t: t,
    "power1.out": _power_out(2), "power2.out": _power_out(3), "power3.out": _power_out(4),
    "power2.in": _power_in(3), "power3.in": _power_in(4),
    "power2.inOut": _power_inout(3), "power3.inOut": _power_inout(4),
    "back.out": back_out, "elastic.out": elastic_out, "expo.out": expo_out,
}


def ease(name, t):
    return EASES[name](clamp(t))


class Tween:
    """A number that travels from `start` to `end` over `duration` seconds (after `delay`)."""

    def __init__(self, start=0.0, end=1.0, duration=0.5, ease_name="power3.out", delay=0.0):
        self.start, self.end, self.duration, self.ease_name, self.delay = start, end, duration, ease_name, delay
        self.time = 0.0

    @property
    def progress(self):
        return clamp((self.time - self.delay) / self.duration) if self.duration > 0 else 1.0

    @property
    def value(self):
        return self.start + (self.end - self.start) * EASES[self.ease_name](self.progress)

    @property
    def done(self):
        return self.progress >= 1.0

    def update(self, dt):
        self.time += dt
        return self.value

    def to(self, end, duration=None, ease_name=None):
        """Retarget from wherever the value is now (does nothing if already heading there)."""
        if end == self.end:
            return
        self.start, self.end, self.time, self.delay = self.value, end, 0.0, 0.0
        if duration is not None:
            self.duration = duration
        if ease_name is not None:
            self.ease_name = ease_name


class SmoothScroll:
    """Wheel / drag set a *target*; the position glides to it (exponential smoothing, like Lenis)."""

    def __init__(self, lerp=0.1, wheel_px=90.0):
        self.lerp, self.wheel_px = lerp, wheel_px
        self.target = 0.0
        self.current = 0.0
        self.velocity = 0.0          # pixels per second - drones use it to sway
        self.limit = 0.0

    def set_limit(self, limit):
        self.limit = max(0.0, float(limit))
        self.target = clamp(self.target, 0.0, self.limit)
        self.current = clamp(self.current, 0.0, self.limit)

    def wheel(self, notches):
        """notches > 0 = wheel turned towards you (page moves down)."""
        self.target = clamp(self.target + notches * self.wheel_px, 0.0, self.limit)

    def drag_to(self, value):
        self.target = clamp(value, 0.0, self.limit)

    def jump(self, value=0.0):
        self.target = self.current = clamp(value, 0.0, self.limit)
        self.velocity = 0.0

    def update(self, dt):
        k = 1 - (1 - self.lerp) ** (max(dt, 1e-4) * 60)      # same feel at any frame rate
        before = self.current
        self.current += (self.target - self.current) * k
        if abs(self.target - self.current) < 0.05:
            self.current = self.target
        self.velocity = (self.current - before) / max(dt, 1e-4)
        return self.current
