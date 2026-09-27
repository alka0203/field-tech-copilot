"""Warps a rendered+augmented error-screen panel onto the screen region of a
real remote-controller/inverter-display photo, via a 4-point homography.

Screen regions are hand-annotated once per background photo in
screen_regions.json (see SCHEMA below) — click the 4 corners of the visible
screen in an image viewer and record them; there's no auto-detector here
because getting this right by hand for ~20-30 backgrounds is faster than
training a detector.

SCHEMA (data/synth/screen_regions.json):
[
  {"photo": "data/synth/backgrounds/remote_1.jpg",
   "corners": [[120,80],[420,80],[420,260],[120,260]]}   // TL,TR,BR,BL in pixels
]

Ground truth for every composite comes for free: it's whatever code you asked
seven_segment.py to render.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from augment import augment_panel
from seven_segment import render_seven_segment

SCREEN_REGIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "synth" / "screen_regions.json"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "synth" / "composited"
LABELS_PATH = Path(__file__).resolve().parents[2] / "data" / "synth" / "composited_labels.jsonl"


def _find_homography(src_quad: list[tuple[float, float]], dst_quad: list[tuple[float, float]]) -> np.ndarray:
    """Solves for the 3x3 homography mapping src_quad -> dst_quad (4 point pairs)."""
    A = []
    for (x, y), (u, v) in zip(src_quad, dst_quad):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    A = np.array(A)
    _, _, vt = np.linalg.svd(A)
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2]


def warp_panel_onto_background(panel: Image.Image, background: Image.Image, corners: list[tuple[float, float]]) -> Image.Image:
    w, h = panel.size
    src_quad = [(0, 0), (w, 0), (w, h), (0, h)]
    # PIL's Image.transform(QUAD) wants the *inverse* map: for each dest pixel,
    # where in the source it comes from. We give it the homography mapping
    # dest(background quad) -> src(panel rect), i.e. corners -> src_quad.
    inv_h = _find_homography(corners, src_quad)
    coeffs = inv_h.flatten()[:8] / inv_h.flatten()[8]

    bg = background.convert("RGBA")
    layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    warped = panel.convert("RGBA").transform(bg.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)

    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    mask = Image.new("L", bg.size, 0)
    from PIL import ImageDraw

    ImageDraw.Draw(mask).polygon(corners, fill=255)
    layer.paste(warped, (0, 0), mask)
    return Image.alpha_composite(bg, layer).convert("RGB")


def main(codes: list[str], variants_per_code: int = 3) -> None:
    if not SCREEN_REGIONS_PATH.exists():
        print(
            f"No screen regions annotated at {SCREEN_REGIONS_PATH}. "
            "Annotate 4 screen corners per background photo first (see the schema "
            "in this file's docstring)."
        )
        return

    regions = json.loads(SCREEN_REGIONS_PATH.read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = []

    for code in codes:
        for variant in range(variants_per_code):
            region = random.choice(regions)
            bg_path = Path(__file__).resolve().parents[2] / region["photo"]
            if not bg_path.exists():
                print(f"[skip] missing background {bg_path}")
                continue
            background = Image.open(bg_path)
            panel = render_seven_segment(code)
            panel = augment_panel(panel, seed=hash((code, variant)) % (2**31))
            composite = warp_panel_onto_background(panel, background, [tuple(c) for c in region["corners"]])

            out_name = f"{code}_{bg_path.stem}_{variant}.jpg"
            composite.save(OUT_DIR / out_name, quality=90)
            labels.append({"file": str((OUT_DIR / out_name).relative_to(OUT_DIR.parents[0])), "code": code, "background": region["photo"], "synthetic": True})

    LABELS_PATH.write_text("\n".join(json.dumps(l) for l in labels))
    print(f"Wrote {len(labels)} composites to {OUT_DIR}, labels at {LABELS_PATH}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", nargs="+", default=["E1", "U4", "P9", "F28", "H6"])
    parser.add_argument("--variants-per-code", type=int, default=3)
    args = parser.parse_args()
    main(args.codes, args.variants_per_code)
