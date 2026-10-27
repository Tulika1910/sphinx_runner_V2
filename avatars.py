"""
Characters, their themes, and every picture the game draws (loading + recolouring).

CHARACTER ART  -  avatars/<id>/  (already filled by extract_avatars.py from your two sprite sheets)
    run1.png, run2.png, ...   running frames (any number, played in order)
    jump.png                  shown while in the air          (optional)
    dead.png                  shown after a crash             (optional)
    preview.png               picture on the selection card   (optional)
  Pictures keep their own colours.  They are drawn at full resolution, so they stay sharp.
  A character without a folder falls back to the recoloured T-Rex.

COIN       coin/coin_00.png ... (made by make_coin.py from your animated logo), or coin.gif / coin.png
OBSTACLES  obstacle1.png, obstacle2.png, ...  any number.  Pictures taller than ~130 px are shrunk to fit.
"""
import re
from pathlib import Path

import numpy as np
import pygame

from themes import make_pair, lerp

BASE = Path(__file__).resolve().parent
AVATAR_DIR = BASE / "avatars"
SPRITE_H = 34            # on-screen height of a character in game units (the game is 200 units tall)
COIN_SIZE = 26           # coin size in game units
OBSTACLE_SCALE = 0.36    # obstacle pictures are drawn at this fraction of their file size
DINO_SCALE = 0.37        # same for the original dino (only used if a character has no pictures)
MAX_OBSTACLE_H = 48      # obstacle pictures taller than this (in game units) are scaled down to 40
SHRINK = 3.2             # pictures are kept at up to this many pixels per game unit

# id, display name, hue (0-1) and saturation of its theme.  Rename / recolour freely.
AVATARS = [
    {"id": "wolf",    "name": "Wolf",    "hue": 0.54, "sat": 1.00, "tag": "Icy lone sprinter"},
    {"id": "fox",     "name": "Fox",     "hue": 0.05, "sat": 1.00, "tag": "Quick and a bit cheeky"},
    {"id": "tiger",   "name": "Tiger",   "hue": 0.12, "sat": 1.00, "tag": "Golden pounce machine"},
    {"id": "lynx",    "name": "Lynx",    "hue": 0.74, "sat": 1.00, "tag": "Silent night stalker"},
    {"id": "panda",   "name": "Panda",   "hue": 0.66, "sat": 0.30, "tag": "Chill, until snack time"},
    {"id": "unicorn", "name": "Unicorn", "hue": 0.88, "sat": 1.00, "tag": "Sparkles on every jump"},
    {"id": "dragon",  "name": "Dragon",  "hue": 0.61, "sat": 0.95, "tag": "Wings out, ego in"},
    {"id": "eagle",   "name": "Eagle",   "hue": 0.01, "sat": 0.60, "tag": "Sees the cactus first"},
]
_by_id = {a["id"]: a for a in AVATARS}
_pairs = {}


def avatar(avatar_id):
    return _by_id.get(avatar_id, AVATARS[0])


def palettes(avatar_id):
    """(light, dark) palettes of a character."""
    a = avatar(avatar_id)
    if a["id"] not in _pairs:
        _pairs[a["id"]] = make_pair(a["id"], a["hue"], a["sat"])
    return _pairs[a["id"]]


def palette(avatar_id, dark: bool):
    return palettes(avatar_id)[1 if dark else 0]


# =============================================================================
# sprites: a picture (any resolution) + the size it has in game units
# =============================================================================
class Sprite:
    __slots__ = ("surf", "lw", "lh")

    def __init__(self, surf, lw, lh):
        # keep big pictures at a sensible resolution (saves memory, scales down cleanly)
        if surf.get_height() > lh * SHRINK * 1.3:
            surf = pygame.transform.smoothscale(surf, (max(1, round(lw * SHRINK)), max(1, round(lh * SHRINK))))
        self.surf, self.lw, self.lh = surf, float(lw), float(lh)

    def like(self, surf):
        s = Sprite.__new__(Sprite)
        s.surf, s.lw, s.lh = surf, self.lw, self.lh
        return s


def _natkey(path: Path):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", path.name.lower())]


def load_raw(path: Path):
    return pygame.image.load(str(path)).convert_alpha()


def sprite_from_file(path: Path, scale=0.5, max_h=None):
    img = load_raw(path)
    lw, lh = img.get_width() * scale, img.get_height() * scale
    if max_h and lh > max_h:
        k = 40.0 / lh
        lw, lh = lw * k, 40.0
    return Sprite(img, lw, lh)


def fit_surface(surf, max_w, max_h):
    """Scale a picture down/up to fit inside a box, keeping its shape."""
    k = min(max_w / surf.get_width(), max_h / surf.get_height())
    return pygame.transform.smoothscale(surf, (max(2, round(surf.get_width() * k)), max(2, round(surf.get_height() * k))))


# =============================================================================
# recolouring (only used for grey artwork such as the original dino)
# =============================================================================
def is_grayscale(surf) -> bool:
    rgb = pygame.surfarray.array3d(surf).astype(np.int16)
    opaque = pygame.surfarray.array_alpha(surf) > 40
    if not opaque.any():
        return True
    spread = rgb.max(axis=2) - rgb.min(axis=2)
    return float((spread[opaque] < 14).mean()) > 0.97


def recolor(surf, ink, hole):
    """Dark pixels become `ink`, light pixels `hole`; the transparency is kept."""
    rgb = pygame.surfarray.array3d(surf).astype(np.float32)
    alpha = pygame.surfarray.array_alpha(surf)
    lum = rgb.mean(axis=2) / 255.0
    k = np.clip((1.0 - lum) / (1.0 - 83 / 255.0), 0.0, 1.0)[..., None]    # 83 = the dino's grey
    out = np.asarray(hole, np.float32) * (1 - k) + np.asarray(ink, np.float32) * k
    new = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    pygame.surfarray.blit_array(new, out.astype(np.uint8))
    px = pygame.surfarray.pixels_alpha(new)
    px[:, :] = alpha
    del px
    return new


_gray_cache = {}


def themed(sprite, pal, role="ink"):
    """A sprite recoloured for a palette if it is grey artwork; coloured artwork is returned unchanged."""
    key = id(sprite.surf)
    if key not in _gray_cache:
        _gray_cache[key] = (sprite.surf, is_grayscale(sprite.surf))      # keep surf alive so the id stays unique
    if not _gray_cache[key][1]:
        return sprite
    color = {"ink": pal.ink, "soft": pal.ink_soft, "accent": pal.accent}[role]
    return sprite.like(recolor(sprite.surf, color, pal.hole))


# =============================================================================
# coin
# =============================================================================
def make_glass_coin_frames(accent, size=96, n=14):
    """A little glass sphere with a sweeping gloss band - used only until your coin pictures exist."""
    d = size
    yy, xx = np.mgrid[0:d, 0:d].astype(np.float32)
    u = (xx - (d - 1) / 2) / (d / 2)
    v = (yy - (d - 1) / 2) / (d / 2)
    r = np.sqrt(u * u + v * v)
    inside = np.clip((1.0 - r) * (d / 2), 0, 1)
    z = np.sqrt(np.clip(1 - r * r, 0, 1))
    light = np.array([-0.4, -0.5, 0.77], np.float32)
    light /= np.linalg.norm(light)
    diffuse = np.clip(u * light[0] + v * light[1] + z * light[2], 0, 1)
    base = np.asarray(accent, np.float32)
    deep, bright = base * 0.55, base + (255 - base) * 0.55
    frames = []
    for i in range(n):
        pos = -1.5 + 3.0 * i / n
        band = np.exp(-(((u + v) / 1.414 - pos) ** 2) / 0.03) * 0.8 * (r < 1)
        spec = np.exp(-(((u + 0.35) ** 2 + (v + 0.4) ** 2) / 0.02)) * 0.9
        rim = np.clip((r - 0.82) / 0.18, 0, 1) * (r < 1) * 0.5
        col = deep[None, None, :] * (1 - diffuse[..., None]) + bright[None, None, :] * diffuse[..., None]
        col = col + 255 * (band + spec + rim)[..., None]
        alpha = (140 + 80 * r ** 3 + 120 * (band + spec)) * inside
        arr = np.dstack([np.clip(col, 0, 255), np.clip(alpha, 0, 255)]).astype(np.uint8)
        frames.append(pygame.image.frombuffer(arr.tobytes(), (d, d), "RGBA").convert_alpha())
    return frames


def load_gif_frames(path: Path, max_frames=40):
    """Frames of an animated GIF (needs Pillow).  Returns [] on failure."""
    try:
        from PIL import Image, ImageSequence
    except ImportError:
        return []
    frames = []
    try:
        with Image.open(path) as im:
            n = getattr(im, "n_frames", 1)
            keep = {int(i * n / max_frames) for i in range(min(n, max_frames))}
            for i, fr in enumerate(ImageSequence.Iterator(im)):
                if i in keep:
                    rgba = fr.convert("RGBA").resize((96, 96), Image.LANCZOS)
                    make = getattr(pygame.image, "frombytes", None) or pygame.image.fromstring
                    frames.append(make(rgba.tobytes(), rgba.size, "RGBA").convert_alpha())
    except Exception as e:
        print(f"[coin] couldn't read {path.name}: {e}")
        return []
    return frames


def load_coin_frames():
    """Your coin pictures as Sprites, or None to use the glass sphere."""
    folder = BASE / "coin"
    surfs = [load_raw(p) for p in sorted(folder.glob("*.png"), key=_natkey)] if folder.exists() else []
    if not surfs:
        for name in ("coin.gif", "coin.png"):
            path = BASE / name
            if path.exists():
                surfs = load_gif_frames(path) if path.suffix.lower() == ".gif" else [load_raw(path)]
                if surfs:
                    break
    return [Sprite(s, COIN_SIZE, COIN_SIZE) for s in surfs] or None


# =============================================================================
# assets
# =============================================================================
REQUIRED = ["trex1.png", "trex3.png", "trex4.png", "trex_collided.png", "ground2.png", "cloud.png",
            "gameOver.png", "restart.png"]


def load_base_assets():
    """Pictures from the game folder (call after pygame.display.set_mode)."""
    obstacle_files = sorted(BASE.glob("obstacle*.png"), key=_natkey)
    missing = [n for n in REQUIRED if not (BASE / n).exists()]
    if missing or not obstacle_files:
        raise SystemExit(f"Missing picture files in {BASE}:\n  " + ", ".join(missing or ["obstacle1.png ..."]))
    return {
        "trex_run": [sprite_from_file(BASE / n, DINO_SCALE) for n in ("trex1.png", "trex3.png", "trex4.png")],
        "trex_dead": sprite_from_file(BASE / "trex_collided.png", DINO_SCALE),
        "ground": sprite_from_file(BASE / "ground2.png", scale=1.0),
        "cloud": sprite_from_file(BASE / "cloud.png"),
        "obstacles": [sprite_from_file(p, OBSTACLE_SCALE, max_h=MAX_OBSTACLE_H) for p in obstacle_files],
        "game_over": sprite_from_file(BASE / "gameOver.png"),
        "restart": sprite_from_file(BASE / "restart.png"),
        "coin": load_coin_frames(),
    }


_art_cache = {}


def load_avatar_art(avatar_id, base):
    """{'run': [Sprite], 'jump': Sprite, 'dead': Sprite, 'preview': Surface, 'custom': bool, 'nominal': (w, h)}"""
    if avatar_id in _art_cache:
        return _art_cache[avatar_id]
    folder = AVATAR_DIR / avatar_id
    runs = sorted(folder.glob("run*.png"), key=_natkey) if folder.exists() else []
    if runs:
        raws = [load_raw(p) for p in runs]

        def pick(name):
            return load_raw(folder / name) if (folder / name).exists() else raws[0]

        jump, dead, prev = pick("jump.png"), pick("dead.png"), pick("preview.png")
        k = (sum(r.get_height() for r in raws) / len(raws)) / SPRITE_H      # pixels per game unit, shared by all poses

        def sp(img):
            return Sprite(img, img.get_width() / k, img.get_height() / k)

        run = [sp(r) for r in raws]
        nominal = (sum(r.lw for r in run) / len(run), float(SPRITE_H))
        art = {"run": run, "jump": sp(jump), "dead": sp(dead), "preview": prev, "custom": True, "nominal": nominal}
    else:
        run = base["trex_run"]
        art = {"run": run, "jump": run[0], "dead": base["trex_dead"], "preview": run[0].surf,
               "custom": False, "nominal": (run[0].lw, run[0].lh)}
    _art_cache[avatar_id] = art
    return art


_previews = {}


def preview(avatar_id, base, dark):
    """The picture on a character's selection card (full resolution, in the right colours)."""
    key = (avatar_id, dark)
    if key not in _previews:
        art = load_avatar_art(avatar_id, base)
        if art["custom"]:
            _previews[key] = art["preview"]
        else:
            _previews[key] = themed(art["run"][0], palette(avatar_id, dark), "accent").surf
    return _previews[key]


def build_world(avatar_id, base):
    """Everything the game draws, once for light and once for dark:
       {"light": {...}, "dark": {...}, "sizes": {...}}  (all pictures are Sprites)"""
    art = load_avatar_art(avatar_id, base)
    custom = art["custom"]
    out = {}
    for dark in (False, True):
        pal = palette(avatar_id, dark)
        role = "accent"
        if base["coin"]:
            coin = base["coin"]
        else:
            coin = [Sprite(s, COIN_SIZE, COIN_SIZE) for s in make_glass_coin_frames(pal.accent)]
        if custom:
            who = {"run": art["run"], "jump": art["jump"], "dead": art["dead"]}
        else:
            who = {"run": [themed(f, pal, role) for f in art["run"]], "jump": themed(art["jump"], pal, role),
                   "dead": themed(art["dead"], pal, role)}
        out["dark" if dark else "light"] = {
            "ground": themed(base["ground"], pal, "ink"),
            "cloud": themed(base["cloud"], pal, "soft"),
            "obstacles": [themed(o, pal, "ink") for o in base["obstacles"]],
            "game_over": themed(base["game_over"], pal, "ink"),
            "restart": themed(base["restart"], pal, "ink"),
            "coin": coin, **who,
        }
    nw, nh = art["nominal"]
    sizes = {
        "trex": (nw, nh),
        "cloud": (base["cloud"].lw, base["cloud"].lh),
        "coin": (COIN_SIZE, COIN_SIZE),
        "obstacles": [(o.lw, o.lh) for o in base["obstacles"]],
        "ground_w": base["ground"].lw,
    }
    if custom:                                    # animals are wide: only the body counts for collisions
        sizes["trex_hit"] = (min(38.0, max(24.0, 0.42 * nw)), 0.78 * nh)
    out["sizes"] = sizes
    return out