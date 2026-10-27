"""
Drone particles: a swarm of tiny glowing lights that drifts around the UI, dodges the mouse, gathers into
shapes (logo, a character's silhouette, any text), escorts the player, and bursts on events.

  swarm = Swarm();  swarm.update(dt, mouse);  swarm.draw(screen, accent, ink, dark)
  swarm.form(points)      all drones fly to these points         swarm.release()   back to drifting
  swarm.orbit(...)        a few drones circle a point             swarm.burst(...)  shock-wave
"""
import math

import numpy as np
import pygame

from themes import lerp

RADII = (3, 5, 7)
LEVELS = (0.22, 0.45, 1.0)             # trail brightness, oldest -> newest


class Swarm:
    def __init__(self, n=140, seed=5):
        self.n = n
        self.rng = np.random.default_rng(seed)
        r = self.rng
        self.w, self.h = 1180.0, 780.0
        self.pos = r.uniform([0, 0], [self.w, self.h], (n, 2)).astype(np.float32)
        self.vel = r.normal(0, 0.4, (n, 2)).astype(np.float32)
        self.target = self.pos.copy()
        self.has_t = np.zeros(n, bool)
        self.phase = r.uniform(0, 6.28, n).astype(np.float32)
        self.size = r.integers(0, 3, n)
        self.tone = r.integers(0, 4, n)
        self.hist = [self.pos.copy() for _ in range(2)]
        self.time = 0.0
        self.alpha = 1.0
        self._sprites = {}

    # ---- controls -----------------------------------------------------------------------------
    def resize(self, w, h):
        if abs(w - self.w) > 1 or abs(h - self.h) > 1:
            self.pos *= np.array([w / self.w, h / self.h], np.float32)
            self.target *= np.array([w / self.w, h / self.h], np.float32)
            self.hist = [self.pos.copy() for _ in range(2)]
            self.w, self.h = float(w), float(h)

    def form(self, points):
        """Send every drone to one of the points (neighbours go to neighbours, so the move looks tidy)."""
        pts = np.asarray(points, np.float32)
        if len(pts) == 0:
            return
        idx = self.rng.choice(len(pts), self.n, replace=len(pts) < self.n)
        pts = pts[idx]
        order_d = np.argsort(self.pos[:, 0] + 0.3 * self.pos[:, 1])
        order_p = np.argsort(pts[:, 0] + 0.3 * pts[:, 1])
        self.target[order_d] = pts[order_p]
        self.has_t[:] = True

    def retarget(self, points):
        """Like form(), but keeps the drones' current assignment (cheap, for moving shapes)."""
        pts = np.asarray(points, np.float32)
        if len(pts) == 0:
            return
        if not self.has_t.all():
            return self.form(pts)
        order_d = np.argsort(self.target[:, 0] + 0.3 * self.target[:, 1])
        order_p = np.argsort(pts[:, 0] + 0.3 * pts[:, 1])
        m = min(len(pts), self.n)
        self.target[order_d[:m]] = pts[order_p[:m]]

    def orbit(self, center, radius, count, angle, squash=0.55):
        """The first `count` drones circle `center` (an escort); the rest keep drifting."""
        count = min(count, self.n)
        a = angle + np.arange(count) * (2 * math.pi / count)
        self.target[:count, 0] = center[0] + np.cos(a) * radius
        self.target[:count, 1] = center[1] + np.sin(a) * radius * squash
        self.has_t[:count] = True

    def release(self):
        self.has_t[:] = False

    def release_first(self, count):
        self.has_t[:count] = False

    def burst(self, center, radius=170.0, strength=9.0, only_free=False):
        d = self.pos - np.asarray(center, np.float32)
        dist = np.hypot(d[:, 0], d[:, 1]) + 1e-3
        m = dist < radius
        if only_free:
            m &= ~self.has_t
        push = (1 - dist / radius).clip(0, 1) * strength
        self.vel[m] += (d[m] / dist[m, None]) * push[m, None]

    def explode(self, center, strength=15.0):
        self.burst(center, radius=1e5, strength=strength)
        self.vel += self.rng.normal(0, 2.0, self.vel.shape).astype(np.float32)

    # ---- physics ------------------------------------------------------------------------------
    def update(self, dt, mouse=None, scroll_velocity=0.0):
        dt = min(dt, 0.05)
        k = dt * 60.0
        self.time += dt
        t = self.time
        free, tgt = ~self.has_t, self.has_t

        fx = np.sin(self.pos[:, 1] * 0.012 + t * 0.6 + self.phase)
        fy = np.cos(self.pos[:, 0] * 0.010 + t * 0.5 + self.phase * 1.3)
        self.vel[free] += (np.stack([fx, fy], 1) * 0.035)[free] * k
        if tgt.any():
            seek = (self.target - self.pos) * 0.018
            shimmer = np.stack([np.sin(t * 3 + self.phase), np.cos(t * 2.6 + self.phase * 1.7)], 1) * 0.05
            self.vel[tgt] += (seek + shimmer)[tgt] * k
        if mouse is not None:
            d = self.pos - np.asarray(mouse, np.float32)
            dist = np.hypot(d[:, 0], d[:, 1]) + 1e-3
            m = dist < 120
            self.vel[m] += (d[m] / dist[m, None]) * ((1 - dist[m] / 120) * 1.3)[:, None] * k
        if scroll_velocity:
            self.vel[:, 1] -= np.float32(scroll_velocity * 0.0009 * k)

        speed = np.hypot(self.vel[:, 0], self.vel[:, 1]) + 1e-6
        damp = np.where(tgt, 0.90, np.where(speed > 3.5, 0.95, 0.985)) ** k       # bursts calm down quickly
        self.vel *= damp[:, None].astype(np.float32)
        self.vel *= np.minimum(1.0, 18.0 / speed)[:, None].astype(np.float32)

        self.hist[0] = self.hist[1]
        self.hist[1] = self.pos.copy()
        self.pos += self.vel * k
        m = 30.0
        for axis, size in ((0, self.w), (1, self.h)):
            wrapped = (self.pos[:, axis] + m) % (size + 2 * m) - m
            self.pos[:, axis] = np.where(free, wrapped, self.pos[:, axis])

    # ---- drawing ------------------------------------------------------------------------------
    def _sprite(self, color, size_idx, level, additive):
        key = (color, size_idx, level, additive)
        s = self._sprites.get(key)
        if s is None:
            r = RADII[size_idx]
            yy, xx = np.mgrid[-r:r, -r:r].astype(np.float32) + 0.5
            d = np.sqrt(xx * xx + yy * yy) / r
            glow = (np.clip(1 - d, 0, 1) ** 2 * 0.85 + np.exp(-(d * 3.2) ** 2)) * level
            glow = np.clip(glow, 0, 1)
            if additive:
                arr = (np.asarray(color, np.float32)[None, None, :] * glow[..., None]).astype(np.uint8)
                s = pygame.surfarray.make_surface(np.ascontiguousarray(arr)).convert()
            else:
                s = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
                s.fill((*color, 0))
                px = pygame.surfarray.pixels_alpha(s)
                px[:, :] = (glow * 235).astype(np.uint8)
                del px
            if len(self._sprites) > 400:
                self._sprites.clear()
            self._sprites[key] = s
        return s

    def draw(self, target, accent, ink, dark, alpha=1.0):
        """Additive glow on dark themes; soft dark dots on light themes."""
        a = float(np.clip(alpha * self.alpha, 0, 1))
        if a < 0.03:
            return
        base_white = (255, 255, 255) if dark else ink
        tones = [lerp(accent, base_white, i / 3 * (0.75 if dark else 0.35)) for i in range(4)]
        flag = pygame.BLEND_RGB_ADD if dark else 0
        seq = []
        frames = (self.hist[0], self.hist[1], self.pos)
        for level, pts in zip(LEVELS, frames):
            lv = round(level * a * 4) / 4
            if lv <= 0:
                continue
            for i in range(self.n):
                r = RADII[self.size[i]]
                spr = self._sprite(tones[self.tone[i]], int(self.size[i]), lv, dark)
                seq.append((spr, (int(pts[i, 0]) - r, int(pts[i, 1]) - r), None, flag))
        target.blits(seq, False)


# ---- shapes to gather into ------------------------------------------------------------------------
def _sample(alpha_arr, box, n, rng, threshold=110):
    xs, ys = np.nonzero(alpha_arr > threshold)
    if len(xs) == 0:
        return np.zeros((0, 2), np.float32)
    w, h = alpha_arr.shape
    k = min(box.w / w, box.h / h)
    pick = rng.integers(0, len(xs), n)
    px = box.centerx + (xs[pick] - w / 2) * k + rng.normal(0, 0.6, n)
    py = box.centery + (ys[pick] - h / 2) * k + rng.normal(0, 0.6, n)
    return np.stack([px, py], 1).astype(np.float32)


def surface_points(surf, box, n=300, rng=None, max_side=96):
    """Points inside the opaque part of a picture (e.g. a character), fitted into `box`."""
    rng = rng or np.random.default_rng(1)
    k = min(1.0, max_side / max(surf.get_size()))
    small = surf if k >= 1 else pygame.transform.smoothscale(surf, (max(2, int(surf.get_width() * k)), max(2, int(surf.get_height() * k))))
    return _sample(pygame.surfarray.array_alpha(small), pygame.Rect(box), n, rng)


def text_points(font, text, center, n=320, rng=None):
    rng = rng or np.random.default_rng(2)
    surf = font.render(text, True, (255, 255, 255))
    box = surf.get_rect(center=center)
    return _sample(pygame.surfarray.array_alpha(surf), box, n, rng)


def logo_points(center, size, n=260):
    """Two glowing diamonds with a line between them (the monolith from the backdrop)."""
    cx, cy = center
    rx, ry = size * 0.34, size * 0.5
    pts = []
    for dx in (-0.36 * size, 0.36 * size):
        verts = [(cx + dx, cy - ry), (cx + dx + rx, cy), (cx + dx, cy + ry), (cx + dx - rx, cy)]
        for a, b in zip(verts, verts[1:] + verts[:1]):
            for t in np.linspace(0, 1, n // 10, endpoint=False):
                pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    for t in np.linspace(-1, 1, n // 8):
        pts.append((cx, cy + t * ry * 1.15))
    return np.asarray(pts, np.float32)
