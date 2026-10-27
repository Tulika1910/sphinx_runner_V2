"""
Turns your animated Sphinx logo into the coin pictures the game uses:  coin/coin_00.png ...

  python make_coin.py                          (reads sphinx_loader_simulation.gif next to this file)
  python make_coin.py my_logo.gif

Each coin is a little dark glass token with the logo on it (blended like light on glass), so it reads on
both the light and the dark themes.  Needs Pillow + numpy.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageSequence

HERE = Path(__file__).resolve().parent
SIZE = 96                 # pixels of each coin picture (the game shows it at about 30-55 px)
FRAMES = 36               # how many frames of the animation to keep
LOGO_FRACTION = 0.80      # logo width as a share of the coin


def disc_base(size):
    """Dark glass token: soft radial shading, bright rim, anti-aliased edge (drawn at 4x then reduced)."""
    big = size * 4
    yy, xx = np.mgrid[0:big, 0:big].astype(np.float32)
    c = (big - 1) / 2
    r = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / (big / 2)
    shade = np.clip(1 - np.sqrt((xx - c * 0.72) ** 2 + (yy - c * 0.62) ** 2) / (big * 0.75), 0, 1)
    rgb = np.array([8, 12, 26], np.float32) + shade[..., None] * np.array([40, 48, 78], np.float32)
    rim = np.clip((r - 0.86) / 0.14, 0, 1) * (r < 1)
    rgb += rim[..., None] * np.array([120, 130, 170], np.float32)
    a = np.clip((1 - r) * (big / 2), 0, 1)
    img = Image.fromarray(np.dstack([rgb.clip(0, 255), a * 255]).astype(np.uint8), "RGBA")
    return img.resize((size, size), Image.LANCZOS)


def main(gif_path: Path, out_dir: Path):
    out_dir.mkdir(exist_ok=True)
    base = disc_base(SIZE)
    base_rgb = np.asarray(base)[..., :3].astype(np.float32)
    base_a = np.asarray(base)[..., 3]
    with Image.open(gif_path) as gif:
        n = gif.n_frames
        picks = sorted({int(i * n / FRAMES) for i in range(FRAMES)})
        for k, idx in enumerate(picks):
            gif.seek(idx)
            logo = gif.convert("RGB")
            w, h = logo.size
            m = int(min(w, h) * 0.03)
            logo = logo.crop((m, m, w - m, h - m)).resize((int(SIZE * LOGO_FRACTION),) * 2, Image.LANCZOS)
            canvas = np.zeros((SIZE, SIZE, 3), np.float32)
            o = (SIZE - logo.width) // 2
            canvas[o:o + logo.height, o:o + logo.width] = np.asarray(logo, np.float32)
            screen = 255 - (255 - base_rgb) * (255 - canvas) / 255            # light on glass
            out = np.dstack([screen.clip(0, 255), base_a]).astype(np.uint8)
            Image.fromarray(out, "RGBA").save(out_dir / f"coin_{k:02d}.png")
    print(f"wrote {len(picks)} coin pictures to {out_dir}")


if __name__ == "__main__":
    gif = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "sphinx_loader_simulation.gif"
    main(gif, HERE / "coin")
