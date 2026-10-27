"""
Cuts the 8 animals (4 poses each) out of the two sprite sheets into  avatars/<id>/*.png

  python extract_avatars.py                       (uses the default sheet file names below)
  python extract_avatars.py sheet1.jpg sheet2.png

Each card row is a pose (01 .. 04).  POSES below says which pose is used for what, per animal:
  run1 / run2 = the two running frames,  jump = while in the air,  dead = after a crash,
  preview = pose 01 (the picture on the selection card).
Change POSES and run the script again to re-cast the animals.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = Path(__file__).resolve().parent
SHEETS = [
    ("Gemini_Generated_Image_vun6bpvun6bpvun6.jpg", ["wolf", "fox", "tiger", "lynx"],
     [(20, 308), (331, 620), (643, 933), (956, 1243)], [(19, 210), (226, 415), (431, 618), (634, 822)]),
    ("Neon_Cyber_Creature_Sprite_Sheet.png", ["panda", "unicorn", "dragon", "eagle"],
     [(25, 374), (403, 753), (782, 1133), (1162, 1510)], [(23, 255), (274, 504), (524, 751), (771, 998)]),
]
POSES = {
    "wolf":    dict(run=(3, 1), jump=3, dead=4),
    "fox":     dict(run=(1, 3), jump=2, dead=4),
    "tiger":   dict(run=(1, 3), jump=2, dead=4),
    "lynx":    dict(run=(1, 2), jump=2, dead=4),
    "panda":   dict(run=(1, 3), jump=3, dead=4),
    "unicorn": dict(run=(1, 2), jump=3, dead=4),
    "dragon":  dict(run=(1, 2), jump=2, dead=4),
    "eagle":   dict(run=(1, 2), jump=2, dead=4),
}
INSET = 12            # pixels trimmed from every side of a card (removes the frame lines)
THRESH = 40           # how much brighter than the dark background a pixel must be to count


def cut(cell: Image.Image) -> Image.Image:
    a = np.asarray(cell.convert("RGB")).astype(np.float32)
    bg = np.median(np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3)]), axis=0)
    strength = a.max(axis=2) - bg.max()
    mask = strength > THRESH
    mask[:INSET] = mask[-INSET:] = False
    mask[:, :INSET] = mask[:, -INSET:] = False
    joined = ndi.binary_dilation(mask, iterations=3)               # glue pixel-art gaps together
    labels, n = ndi.label(joined)
    if n == 0:
        raise ValueError("nothing found in this card")
    areas = ndi.sum(mask, labels, range(1, n + 1))
    keep = [i + 1 for i, ar in enumerate(areas) if ar >= 0.06 * areas.max()]
    body = np.isin(labels, keep) & ndi.binary_dilation(mask, iterations=1)
    body = ndi.binary_closing(body, iterations=2)
    # fill small holes only (black fur inside the outline) - not big decorative rings
    holes = ndi.binary_fill_holes(body) & ~body
    hl, hn = ndi.label(holes)
    small = [i + 1 for i, ar in enumerate(ndi.sum(holes, hl, range(1, hn + 1))) if ar < 0.05 * body.sum()]
    body = body | np.isin(hl, small)
    # throw away thin decorations (arcs, bars, speed lines): keep what is within 5 px of the thick core,
    # and only the biggest thick pieces
    core = ndi.binary_opening(body, iterations=3)
    cl, cn = ndi.label(core)
    if cn:
        sizes = ndi.sum(core, cl, range(1, cn + 1))
        core = np.isin(cl, [i + 1 for i, sz in enumerate(sizes) if sz >= 0.25 * sizes.max()])
        body = body & ndi.binary_dilation(core, iterations=5)
    alpha = ndi.gaussian_filter(body.astype(np.float32), 0.8)
    ys, xs = np.where(alpha > 0.1)
    box = (max(xs.min() - 2, 0), max(ys.min() - 2, 0), min(xs.max() + 3, a.shape[1]), min(ys.max() + 3, a.shape[0]))
    rgba = np.dstack([a, alpha * 255]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA").crop(box)


def main(out_dir: Path, sheet_paths=None):
    for k, (name, ids, cols, rows) in enumerate(SHEETS):
        path = Path(sheet_paths[k]) if sheet_paths else HERE / name
        sheet = Image.open(path).convert("RGB")
        for ci, aid in enumerate(ids):
            poses = {}
            for ri in range(4):
                x0, x1 = cols[ci]
                y0, y1 = rows[ri]
                poses[ri + 1] = cut(sheet.crop((x0, y0, x1 + 1, y1 + 1)))
            folder = out_dir / aid
            folder.mkdir(parents=True, exist_ok=True)
            m = POSES[aid]
            for fname, pose in (("run1", m["run"][0]), ("run2", m["run"][1]), ("jump", m["jump"]),
                                ("dead", m["dead"]), ("preview", 1)):
                poses[pose].save(folder / f"{fname}.png")
            print(aid, {p: im.size for p, im in poses.items()})


if __name__ == "__main__":
    args = sys.argv[1:]
    main(HERE / "avatars", args if len(args) == 2 else None)
