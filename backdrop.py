"""
Procedural backdrop in the spirit of the Sphinx storyboard: a rain-soaked city of towers, a glass monolith
with two glowing diamonds, light falling like waterfalls, fog.  It is drawn from scratch (not a copy of
any picture) and tinted by the character's palette: dark = neon night, light = misty daylight.

Built once per palette and window size (about 0.1 s) and cached by glass.py.  Needs Pillow + numpy.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from themes import lerp


def _col(c, a=255):
    return (int(c[0]), int(c[1]), int(c[2]), int(a))


def _vgradient(w, h, top, bottom):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    return np.broadcast_to(np.asarray(top, np.float32) * (1 - t) + np.asarray(bottom, np.float32) * t, (h, w, 3))


def _alpha_strip(w, h, color, a_top, a_bottom):
    """A w x h strip of one colour whose opacity fades from a_top to a_bottom."""
    a = np.linspace(a_top, a_bottom, h, dtype=np.float32)[:, None]
    arr = np.zeros((h, w, 4), np.uint8)
    arr[..., :3] = color
    arr[..., 3] = np.broadcast_to(a, (h, w)).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def make_backdrop_image(pal, size, seed=2026):
    W, H = size
    s = 2                                                    # drawn at half size, then scaled up (soft, hazy)
    w, h = max(80, W // s), max(60, H // s)
    rng = np.random.default_rng(seed)                        # same seed for every palette: day and night match
    dark, acc = pal.is_dark, pal.accent

    if dark:
        sky_top, sky_hor = lerp(pal.bg_top, (0, 0, 0), .35), lerp(pal.bg_bottom, acc, .20)
        fog, near = lerp(pal.bg_bottom, (110, 125, 160), .22), lerp(pal.bg_top, (0, 0, 0), .72)
        lit, neon = lerp(acc, (255, 255, 255), .6), lerp(acc, (255, 255, 255), .25)
        glow_a, rain_white = 95, (225, 235, 255)
    else:
        sky_top, sky_hor = pal.bg_top, lerp(pal.bg_bottom, (255, 255, 255), .30)
        fog = lerp(pal.bg_bottom, (255, 255, 255), .50)
        near = lerp(lerp(acc, (95, 110, 150), .65), pal.ink, .22)       # cool, misty towers in any hue
        lit, neon = lerp(acc, (255, 255, 255), .15), acc
        glow_a, rain_white = 50, (255, 255, 255)

    # ---- sky + glow on the horizon ----------------------------------------------------------
    horizon = 0.62
    top_h = int(h * horizon)
    sky = np.concatenate([_vgradient(w, top_h, sky_top, sky_hor), _vgradient(w, h - top_h, sky_hor, fog)], axis=0)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - 0.60 * w) / (0.55 * w)) ** 2 + ((yy - 0.55 * h) / (0.45 * h)) ** 2)
    g = (np.clip(1 - d, 0, 1) ** 2 * glow_a / 255.0)[..., None]
    sky = sky * (1 - g) + np.asarray(acc, np.float32) * g
    base = Image.fromarray(sky.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))           # neon things, blurred later
    gd = ImageDraw.Draw(glow)

    # ---- far to near layers of towers ----------------------------------------------------------
    layers = [  # base y, tower width, tower height, fog mix, lit-window chance
        (0.66, (8, 22), (0.10, 0.34), 0.62 if dark else 0.74, 0.10),
        (0.72, (12, 30), (0.14, 0.46), 0.42 if dark else 0.56, 0.07),
        (0.80, (16, 40), (0.18, 0.58), 0.22 if dark else 0.38, 0.045),
        (0.93, (24, 54), (0.10, 0.36), 0.0 if dark else 0.18, 0.02),
    ]
    for li, (by, (wmin, wmax), (hmin, hmax), mix, lit_p) in enumerate(layers):
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        color = lerp(near, fog, mix)
        x = -rng.integers(0, 12)
        while x < w:
            tw = int(rng.integers(wmin, wmax))
            th = int(rng.integers(int(hmin * h), int(hmax * h)))
            top = int(by * h) - th
            ld.rectangle([x, top, x + tw, h], fill=_col(color))
            if rng.random() < .5:                                        # stepped crown
                cw = int(tw * rng.uniform(.4, .8))
                ld.rectangle([x + (tw - cw) // 2, top - int(rng.integers(3, 12)), x + (tw + cw) // 2, top],
                             fill=_col(color))
            if rng.random() < .35:                                       # antenna
                ax = x + tw // 2
                ld.line([ax, top - int(rng.integers(8, 22)), ax, top], fill=_col(color), width=1)
            for wy in range(top + 4, min(h, int(by * h) + 18), 4):       # lit windows
                for wx in range(x + 2, x + tw - 2, 3):
                    if rng.random() < lit_p:
                        ld.rectangle([wx, wy, wx + 1, wy], fill=_col(lit, 150 if dark else 90))
            if li in (1, 2) and rng.random() < .3:                       # neon edge light
                ex = x + tw if rng.random() < .5 else x
                gd.line([ex, top + 2, ex, top + int(th * rng.uniform(.4, .9))], fill=_col(neon, 200 if dark else 120), width=1)
            x += tw + int(rng.integers(0, 5))
        base = Image.alpha_composite(base, layer)

    # ---- the monolith with two glowing diamonds ----------------------------------------------------
    cx = 0.62 * w
    mono = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    md = ImageDraw.Draw(mono)
    body = lerp(near, fog, .10)
    md.polygon([(cx - .18 * w, .74 * h), (cx - .105 * w, .02 * h), (cx + .105 * w, .02 * h), (cx + .18 * w, .74 * h)],
               fill=_col(body))
    for k, dx in enumerate((-.075, .075)):                                # the two diamonds
        px, py, rx, ry = cx + dx * w, .31 * h, .062 * w, .17 * h
        pts = [(px, py - ry), (px + rx, py), (px, py + ry), (px - rx, py)]
        inner = [(px, py - ry * .78), (px + rx * .78, py), (px, py + ry * .78), (px - rx * .78, py)]
        if dark:
            md.polygon(pts, fill=_col(lerp(body, (0, 0, 0), .45)))
            md.polygon(inner, fill=_col(lerp(lerp(acc, (0, 0, 0), .78), body, .2)))
        else:
            md.polygon(pts, fill=_col(lerp(body, (255, 255, 255), .45)))
            md.polygon(inner, fill=_col(lerp(lerp(acc, (255, 255, 255), .80), body, .1)))
        gd.polygon(pts, outline=_col(lit, 255 if dark else 190), width=3)
        gd.line([pts[0], pts[1]], fill=_col((255, 255, 255), 255 if dark else 220), width=3)
        gd.line([pts[3], pts[0]], fill=_col(neon, 160 if dark else 120), width=1)
    beam = _alpha_strip(max(2, int(.006 * w)), int(.5 * h), lit, 255 if dark else 190, 0)   # beam between the diamonds
    mono.paste(beam, (int(cx), int(.12 * h)), beam)
    for ex in (-.115, .115):                                              # tall light bars on the monolith's edges
        bar = _alpha_strip(max(2, int(.009 * w)), int(.55 * h), lit, 230 if dark else 150, 30)
        mono.paste(bar, (int(cx + ex * w), int(.04 * h)), bar)
    base = Image.alpha_composite(base, mono)

    # ---- bridges and light falling from the platforms -----------------------------------------------
    deck = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deck)
    dc = _col(lerp(near, fog, .15))
    dd.line([(0, .79 * h), (.55 * w, .70 * h)], fill=dc, width=3)
    dd.line([(0, .83 * h), (.60 * w, .73 * h)], fill=dc, width=2)
    dd.line([(.66 * w, .74 * h), (w, .81 * h)], fill=dc, width=3)
    for k in range(9):                                                    # lamps along the bridge
        t = k / 8
        lx, ly = t * .55 * w, (.79 - .09 * t) * h - 3
        gd.ellipse([lx - 1, ly - 1, lx + 1, ly + 1], fill=_col(lit, 220 if dark else 120))
    base = Image.alpha_composite(base, deck)
    falls = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for k in range(7):
        fx, fw = int(rng.uniform(.05, .95) * w), int(rng.integers(2, 6))
        fy = int(rng.uniform(.62, .72) * h)
        strip = _alpha_strip(fw, int(h * .9) - fy, rain_white, 120 if dark else 80, 0)
        falls.paste(strip, (fx, fy), strip)
    base = Image.alpha_composite(base, falls)

    # ---- wet street: a faint, blurred reflection of the skyline -----------------------------------
    y0, bh = int(.80 * h), int(.17 * h)
    refl = ImageOps.flip(base.crop((0, y0 - bh, w, y0))).filter(ImageFilter.GaussianBlur(2.2))
    fade = _alpha_strip(w, bh, (0, 0, 0), 120 if dark else 70, 0)
    refl.putalpha(Image.fromarray(np.asarray(fade)[..., 3], "L"))
    base.paste(refl, (0, y0), refl)

    # ---- neon glow, fog, readable top ----------------------------------------------------------------
    soft = glow.filter(ImageFilter.GaussianBlur(3 * (1 if s == 1 else .7)))
    base = Image.alpha_composite(base, soft)
    base = Image.alpha_composite(base, glow.filter(ImageFilter.GaussianBlur(.6)))
    mist = _alpha_strip(w, int(.34 * h), fog, 0, 150 if dark else 190)
    base.paste(mist, (0, h - mist.height), mist)
    scrim = _alpha_strip(w, int(.26 * h), sky_top, 120 if dark else 110, 0)
    base.paste(scrim, (0, 0), scrim)
    arr = np.asarray(base.convert("RGB")).astype(np.float32)
    v = 1 - 0.28 * np.clip(np.sqrt(((xx - w / 2) / (w * .75)) ** 2 + ((yy - h / 2) / (h * .75)) ** 2) - .25, 0, 1)[..., None]
    arr = arr * v if dark else arr * (0.94 + 0.06 * v) + 255 * (1 - (0.94 + 0.06 * v)) * 0.9
    out = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")
    return out.resize((W, H), Image.BICUBIC)


def make_rain_image(dark, size=256, drops=70, seed=11):
    """A tile of rain streaks that repeats seamlessly in both directions (RGBA)."""
    rng = np.random.default_rng(seed)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    color = (215, 228, 255) if dark else (70, 85, 120)
    for _ in range(drops):
        x, y = int(rng.integers(0, size)), int(rng.integers(0, size))
        length = int(rng.integers(12, 30))
        a = int(rng.integers(35, 95)) if dark else int(rng.integers(28, 70))
        for ox in (-size, 0, size):
            for oy in (-size, 0, size):
                d.line([(x + ox, y + oy), (x + ox - length * 0.18, y + oy + length)], fill=(*color, a), width=1)
    return tile