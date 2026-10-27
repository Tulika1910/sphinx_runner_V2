"""
Colour themes (no pygame in here - just numbers).

Every character gets a light and a dark Palette generated from one hue, so the whole
window (background, glass cards, text, sprites) matches the character you picked.
To change a character's colours, edit its hue / sat in avatars.py.
"""
import colorsys
from dataclasses import dataclass

Color = tuple


def hsl(h: float, s: float, l: float) -> Color:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, min(max(l, 0.0), 1.0), min(max(s, 0.0), 1.0))
    return (round(r * 255), round(g * 255), round(b * 255))


def lerp(a, b, t: float):
    """Blend two numbers or two colours."""
    t = min(max(t, 0.0), 1.0)
    if isinstance(a, (tuple, list)):
        return tuple(round(x + (y - x) * t) for x, y in zip(a, b))
    return a + (b - a) * t


def smoothstep(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


@dataclass(frozen=True)
class Palette:
    key: str                  # unique name, used for caching
    is_dark: bool
    bg_top: Color             # background gradient
    bg_bottom: Color
    blobs: tuple              # soft glows: ((colour, x, y, radius), ...) as fractions of the window
    glass: Color              # frosted glass tint
    glass_alpha: int
    edge: Color               # glass rim
    edge_alpha: int
    shadow_alpha: int
    ink: Color                # main text and sprite colour
    ink_soft: Color           # secondary text, clouds
    accent: Color
    on_accent: Color          # text on top of accent
    hole: Color               # "eye" colour inside sprites


def make_palette(key: str, hue: float, sat: float, dark: bool) -> Palette:
    h, s = hue, sat
    if not dark:
        return Palette(
            key=f"{key}-light", is_dark=False,
            bg_top=hsl(h, .60 * s, .94), bg_bottom=hsl(h + .05, .50 * s, .85),
            blobs=((hsl(h - .06, .75 * s, .80), .15, .20, .36),
                   (hsl(h + .10, .70 * s, .78), .85, .78, .42),
                   (hsl(h + .02, .65 * s, .90), .62, .08, .26)),
            glass=(255, 255, 255), glass_alpha=105, edge=(255, 255, 255), edge_alpha=150,
            shadow_alpha=40,
            ink=hsl(h, .30 * s, .20), ink_soft=hsl(h, .18 * s, .45),
            accent=hsl(h, .62 * s, .50), on_accent=(255, 255, 255),
            hole=(255, 255, 255),
        )
    return Palette(
        key=f"{key}-dark", is_dark=True,
        bg_top=hsl(h, .50 * s, .08), bg_bottom=hsl(h + .05, .45 * s, .15),
        blobs=((hsl(h - .04, .70 * s, .27), .15, .20, .38),
               (hsl(h + .12, .65 * s, .23), .85, .80, .42),
               (hsl(h, .60 * s, .20), .62, .08, .30)),
        glass=hsl(h, .25 * s, .78), glass_alpha=26, edge=(255, 255, 255), edge_alpha=60,
        shadow_alpha=95,
        ink=hsl(h, .22 * s, .93), ink_soft=hsl(h, .14 * s, .66),
        accent=hsl(h, .75 * s, .64), on_accent=hsl(h, .40 * s, .10),
        hole=hsl(h, .30 * s, .13),
    )


def make_pair(key: str, hue: float, sat: float = 1.0):
    return make_palette(key, hue, sat, False), make_palette(key, hue, sat, True)


# ---- automatic day / night ---------------------------------------------------------
NIGHT_EVERY = 700             # the theme flips every this many points
FADE_FRAMES = 120             # and fades over this many frames (2 s)


def night_target(score: int) -> bool:
    """True when the score is in an 'odd' block: 0-699 day, 700-1399 night, ..."""
    return (score // NIGHT_EVERY) % 2 == 1


def ease_level(level: float, target: bool) -> float:
    """Move the 0..1 night level one frame towards its target."""
    step = 1.0 / FADE_FRAMES
    goal = 1.0 if target else 0.0
    if level < goal:
        return min(goal, level + step)
    return max(goal, level - step)
