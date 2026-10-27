"""
Cartoon sound effects, synthesised with numpy (no audio files needed).

  python sound.py      writes every sound to sounds/*.wav - listen to them, or replace any file with your own
                       (same name); the game loads sounds/<name>.wav when it exists and synthesises it otherwise.
"""
import wave
from pathlib import Path

import numpy as np

SR = 22050
BASE = Path(__file__).resolve().parent


def _t(seconds):
    return np.arange(int(SR * seconds)) / SR


def _phase(freq):
    return 2 * np.pi * np.cumsum(freq) / SR


def _env(n, attack=0.004, decay=6.0):
    t = np.arange(n) / SR
    return np.minimum(1.0, t / attack) * np.exp(-decay * t)


def _fade(x, ms=8):
    n = min(len(x) // 2, int(SR * ms / 1000))
    if n:
        x[-n:] *= np.linspace(1, 0, n)
    return x


def _norm(x, peak=0.8):
    m = np.abs(x).max()
    return _fade(x * (peak / m) if m > 0 else x)


def _lowpass_noise(seconds, cutoff_start, cutoff_end, seed=1):
    """White noise through a one-pole low-pass whose cutoff moves (a 'whoosh' or a 'splat')."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    noise = rng.uniform(-1, 1, n)
    cut = np.linspace(cutoff_start, cutoff_end, n)
    a = 1 - np.exp(-2 * np.pi * cut / SR)
    out = np.zeros(n)
    y = 0.0
    for i in range(n):
        y += a[i] * (noise[i] - y)
        out[i] = y
    return out


# ---- the sounds ---------------------------------------------------------------------------------
def boing():
    """Springy jump: pitch shoots up, then wobbles back down."""
    t = _t(0.45)
    f = 170 * (1 + 2.8 * (1 - np.exp(-t * 18)) * np.exp(-t * 3.2)) * (1 + 0.07 * np.sin(2 * np.pi * 24 * t) * np.exp(-t * 4))
    ph = _phase(f)
    return _norm((np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)) * _env(len(t), 0.004, 6.5))


def coin(step=0):
    """Two quick rising blips; `step` raises the pitch by that many semitones (coin streaks)."""
    k = 2 ** (step / 12)
    a, b = _t(0.07), _t(0.20)
    one = np.sin(_phase(np.full(len(a), 988 * k))) * _env(len(a), 0.002, 14)
    f2 = np.full(len(b), 1319 * k) * (1 + 0.012 * np.sin(2 * np.pi * 30 * b))
    p2 = _phase(f2)
    two = (np.sin(p2) + 0.3 * np.sin(2 * p2)) * _env(len(b), 0.002, 11)
    return _norm(np.concatenate([one, two]), 0.7)


def whistle_down(seconds=0.55, f0=950, f1=110):
    t = _t(seconds)
    f = f0 * (f1 / f0) ** (t / seconds) * (1 + 0.025 * np.sin(2 * np.pi * 9 * t))
    return np.sin(_phase(f)) * np.minimum(1, t / 0.01) * (1 - 0.3 * t / seconds)


def whistle_up(seconds=0.4, f0=220, f1=1150):
    t = _t(seconds)
    f = f0 * (f1 / f0) ** (t / seconds) * (1 + 0.02 * np.sin(2 * np.pi * 11 * t))
    return np.sin(_phase(f)) * np.minimum(1, t / 0.01) * np.exp(-1.6 * t)


def splat():
    n = _lowpass_noise(0.16, 3200, 300, seed=4) * _env(int(SR * 0.16), 0.001, 22)
    t = _t(0.16)
    thump = np.sin(_phase(130 * np.exp(-t * 9))) * _env(len(t), 0.001, 20)
    return n * 1.6 + thump


def death():
    """Slide-whistle down, then a wet splat."""
    return _norm(np.concatenate([whistle_down() * 0.8, np.zeros(int(SR * 0.03)), splat() * 0.9]))


def restart():
    return _norm(whistle_up())


def fanfare():
    """A tiny 'ta-da' on a kazoo-ish wave for a new best."""
    notes = [(523.25, 0.09), (659.25, 0.09), (783.99, 0.09), (1046.5, 0.45)]
    out = []
    for f, d in notes:
        t = _t(d)
        ph = _phase(np.full(len(t), f) * (1 + 0.01 * np.sin(2 * np.pi * 6 * t)))
        wave_ = np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.33 * np.sin(3 * ph) + 0.25 * np.sin(4 * ph)
        out.append(wave_ * _env(len(t), 0.004, 3.0 if d > 0.2 else 8.0))
    return _norm(np.concatenate(out), 0.75)


def pop():
    t = _t(0.09)
    return _norm(np.sin(_phase(720 * np.exp(-t * 14) + 180)) * _env(len(t), 0.001, 38), 0.7)


def tick():
    t = _t(0.025)
    return _norm(np.sin(_phase(np.full(len(t), 1900))) * _env(len(t), 0.001, 130), 0.35)


def whoosh():
    n = _lowpass_noise(0.5, 400, 3500, seed=9)
    t = _t(0.5)
    return _norm(n * np.sin(np.pi * t / 0.5) ** 1.5, 0.55)


def ding():
    a, b = _t(0.08), _t(0.35)
    n1 = np.sin(_phase(np.full(len(a), 1568))) * _env(len(a), 0.002, 14)
    p = _phase(np.full(len(b), 2093))
    n2 = (np.sin(p) + 0.25 * np.sin(3 * p)) * _env(len(b), 0.002, 8)
    return _norm(np.concatenate([n1, n2]), 0.6)


def land():
    t = _t(0.1)
    return _norm(np.sin(_phase(95 * np.exp(-t * 12) + 55)) * _env(len(t), 0.002, 30), 0.45)


def select():
    """A cheerful boing for choosing a character: shorter, higher."""
    t = _t(0.26)
    f = 330 * (1 + 1.6 * (1 - np.exp(-t * 28)) * np.exp(-t * 5)) * (1 + 0.05 * np.sin(2 * np.pi * 28 * t) * np.exp(-t * 6))
    ph = _phase(f)
    return _norm((np.sin(ph) + 0.3 * np.sin(2 * ph)) * _env(len(t), 0.003, 9), 0.7)


LIBRARY = {"boing": boing, "death": death, "restart": restart, "fanfare": fanfare, "pop": pop, "tick": tick,
           "whoosh": whoosh, "ding": ding, "land": land, "select": select}
for _i in range(8):
    LIBRARY[f"coin{_i}"] = (lambda s=_i: coin(s))


def to_wav(name, folder):
    data = (np.clip(LIBRARY[name](), -1, 1) * 32767).astype("<i2")
    folder.mkdir(exist_ok=True)
    with wave.open(str(folder / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


class SoundBank:
    """Loads sounds/<name>.wav if present, else synthesises it.  Never raises: no audio device = silence."""

    def __init__(self, folder=BASE / "sounds"):
        self.muted = False
        self.volume = 0.7
        self.sounds = {}
        self.ok = False
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=SR, size=-16, channels=1, buffer=512)
            self._pg = pygame
            freq, _fmt, channels = pygame.mixer.get_init()
            for name, fn in LIBRARY.items():
                path = folder / f"{name}.wav"
                if path.exists():
                    snd = pygame.mixer.Sound(str(path))
                else:
                    x = np.clip(fn(), -1, 1)
                    if freq != SR:
                        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * freq / SR)), np.arange(len(x)), x)
                    pcm = (x * 32767).astype("<i2")
                    if channels == 2:
                        pcm = np.repeat(pcm, 2)
                    snd = pygame.mixer.Sound(buffer=pcm.tobytes())
                snd.set_volume(self.volume)
                self.sounds[name] = snd
            self.ok = True
        except Exception as e:                       # no sound card, no mixer...
            print(f"[sound] audio is off: {e}")

    def play(self, name, step=0):
        """step: for 'coin', 0-7 semitone-ish steps up."""
        if self.muted or not self.ok:
            return
        snd = self.sounds.get(f"coin{min(7, step)}" if name == "coin" else name)
        if snd:
            snd.play()

    def toggle(self):
        self.muted = not self.muted
        return self.muted


if __name__ == "__main__":
    out = BASE / "sounds"
    for n in LIBRARY:
        to_wav(n, out)
    print(f"wrote {len(LIBRARY)} sounds to {out}")

