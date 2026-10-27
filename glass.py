"""
Drawing toolkit for the glassmorphism look: the rainy city backdrop, frosted glass cards, pill buttons,
text.  Cards are position independent (they sample a pre-blurred copy of the backdrop), so they can move,
scroll and pop on hover without any per-frame blurring.
"""
import numpy as np
import pygame


RAIN_DENSITY = 0.3            # 1.0 = the old heavy rain, 0 = none (try 0.15 for a drizzle)


class Fonts:
    NAMES = "segoeui,helveticaneue,helvetica,arial"

    def __init__(self):
        self._cache = {}

    def get(self, size, bold=False):
        key = (int(size), bold)
        if key not in self._cache:
            self._cache[key] = pygame.font.SysFont(self.NAMES, int(size), bold=bold)
        return self._cache[key]


def text(target, fonts, s, size, color, pos, anchor="topleft", bold=False, alpha=255):
    img = fonts.get(size, bold).render(str(s), True, color)
    if alpha < 255:
        img.set_alpha(max(0, int(alpha)))
    rect = img.get_rect(**{anchor: pos})
    target.blit(img, rect)
    return rect


def fit_text(fonts, s, size, max_w, bold=False):
    """Shorten s with '...' so it fits max_w pixels."""
    f = fonts.get(size, bold)
    if f.size(s)[0] <= max_w:
        return s
    while len(s) > 1 and f.size(s + "...")[0] > max_w:
        s = s[:-1]
    return s + "..."


def make_background(pal, size):
    """The city backdrop (see backdrop.py) as a pygame surface."""
    from backdrop import make_backdrop_image
    img = make_backdrop_image(pal, size)
    return pygame.image.frombuffer(img.tobytes(), img.size, "RGB").convert()


def make_rain_tile(dark, **kw):
    from backdrop import make_rain_image
    img = make_rain_image(dark, **kw)
    return pygame.image.frombuffer(img.tobytes(), img.size, "RGBA").convert_alpha()


def _blur(surf, factor=12):
    w, h = surf.get_size()
    small = pygame.transform.smoothscale(surf, (max(2, w // factor), max(2, h // factor)))
    return pygame.transform.smoothscale(small, (w, h))


def _make_decor(pal, w, h, radius):
    """Everything about a card that does not depend on where it is: tint, gloss, rim, corner mask, shadow."""
    decor = pygame.Surface((w, h), pygame.SRCALPHA)
    decor.fill((*pal.glass, pal.glass_alpha))
    gh = max(2, h // 2)                                                  # soft gloss on the upper half
    gloss = pygame.Surface((w, gh), pygame.SRCALPHA)
    gloss.fill((255, 255, 255, 0))
    px = pygame.surfarray.pixels_alpha(gloss)
    px[:, :] = np.linspace(30 if not pal.is_dark else 16, 0, gh, dtype=np.float32)[None, :].astype(np.uint8)
    del px
    decor.blit(gloss, (0, 0))
    pygame.draw.rect(decor, (*pal.edge, pal.edge_alpha), decor.get_rect(), width=1, border_radius=radius)

    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    mask.fill((255, 255, 255, 0))
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)

    m = 28
    shadow = pygame.Surface((w + 2 * m, h + 2 * m), pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, pal.shadow_alpha), (m, m, w, h), border_radius=radius)
    return decor, mask, _blur(shadow, 8)


class GlassKit:
    def __init__(self):
        self._bg = {}
        self._blur = {}
        self._decor = {}
        self._rain = {}

    def background(self, pal, size):
        key = (pal.key, tuple(size))
        if key not in self._bg:
            if len(self._bg) > 8:
                self._bg.clear()
                self._blur.clear()
            self._bg[key] = make_background(pal, size)
        return self._bg[key]

    def blurred(self, pal, size):
        key = (pal.key, tuple(size))
        if key not in self._blur:
            self._blur[key] = _blur(self.background(pal, size), 10)
        return self._blur[key]

    def rain(self, dark):
        if dark not in self._rain:
            self._rain[dark] = (make_rain_tile(dark, drops=max(4, int(70 * RAIN_DENSITY)), seed=11),
                                make_rain_tile(dark, drops=max(3, int(38 * RAIN_DENSITY)), seed=23))
        return self._rain[dark]

    def paint_background(self, target, pal, rain=True, t=None):
        """Backdrop, then two layers of falling rain.  `t` = rain clock in seconds (default: real time)."""
        target.blit(self.background(pal, target.get_size()), (0, 0))
        if not rain:
            return
        W, H = target.get_size()
        if t is None:
            t = pygame.time.get_ticks() / 1000.0
        for tile, base, off in zip(self.rain(pal.is_dark), (520, 330), (0, 97)):
            size = tile.get_width()
            oy = int(t * base) % size
            ox = int(-oy * 0.18 + off) % size
            for y in range(oy - size, H, size):
                for x in range(ox - size, W, size):
                    target.blit(tile, (x, y))

    def card(self, target, pal, rect, radius=22):
        """A frosted glass card.  `rect` may be anywhere (even partly off-screen)."""
        rect = pygame.Rect(rect)
        if rect.w < 4 or rect.h < 4:
            return rect
        W, H = target.get_size()
        clip = rect.clip(pygame.Rect(0, 0, W, H))
        if clip.w <= 0 or clip.h <= 0:
            return rect
        key = (pal.key, rect.w, rect.h, radius)
        if key not in self._decor:
            if len(self._decor) > 160:
                self._decor.clear()
            self._decor[key] = _make_decor(pal, rect.w, rect.h, radius)
        decor, mask, shadow = self._decor[key]
        panel = pygame.Surface((rect.w, rect.h))
        panel.blit(self.blurred(pal, (W, H)), (clip.x - rect.x, clip.y - rect.y), clip)
        panel = panel.convert_alpha()
        panel.blit(decor, (0, 0))
        panel.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        target.blit(shadow, (rect.x - 28, rect.y - 18))
        target.blit(panel, rect.topleft)
        return rect


def pill(target, fonts, pal, rect, label, primary=False, hover=0.0, selected=False, size=16):
    """A rounded button.  primary = filled with the accent colour.  hover = 0..1 (pops out a little)."""
    hover = float(hover)
    rect = pygame.Rect(rect).inflate(round(hover * 6), round(hover * 4))
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    r = rect.height // 2
    if primary:
        col = tuple(min(255, int(c + 26 * hover)) for c in pal.accent)
        pygame.draw.rect(s, (*col, 255), s.get_rect(), border_radius=r)
        txt = pal.on_accent
    else:
        pygame.draw.rect(s, (*pal.ink, int(20 + 28 * hover) if not selected else 46), s.get_rect(), border_radius=r)
        pygame.draw.rect(s, (*(pal.accent if selected else pal.ink), 160 if selected else int(55 + 60 * hover)),
                         s.get_rect(), width=2 if selected else 1, border_radius=r)
        txt = pal.ink
    target.blit(s, rect)
    text(target, fonts, label, size, txt, rect.center, "center", bold=primary)
    return rect


def disc(target, color, center, radius, alpha=255):
    radius = max(1, int(radius))
    s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    pygame.draw.circle(s, (*color, int(alpha)), (radius, radius), radius)
    target.blit(s, (int(center[0]) - radius, int(center[1]) - radius))


def ring(target, color, center, radius, width=2, alpha=255):
    radius = max(2, int(radius))
    s = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
    pygame.draw.circle(s, (*color, int(alpha)), (radius + 2, radius + 2), radius, width)
    target.blit(s, (int(center[0]) - radius - 2, int(center[1]) - radius - 2))